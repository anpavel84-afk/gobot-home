"""Browser Voice Lab in-dialogue local VAD/turn segmentation.

After a real confirmed wake and actual audio playback drain, a 16-second
finite listening window accepts the next spoken turn WITHOUT saying the
wake name again. No paid cloud standby: OpenAI is opened only after >=180ms
of local speech; silence ~0.8s commits; 10s caps each spoken turn.

No sound is persisted. This is deterministic audio gating on the very same
canonical PCM16/16k frames passed to HOST-A HostCore and Vosk.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import math

FRAME_SAMPLES = 960
BYTES_PER_FRAME = 1920
DIALOGUE_IDLE_SECONDS = 16.0
SPEAKER_ECHO_GUARD_SECONDS = .40
SILENCE_FRAMES = 14  # 14*60ms == 840ms
MAX_UTTERANCE_FRAMES = 160  # 9.6 seconds
START_VOICE_FRAMES = 3  # 180ms
PREROLL_FRAMES = 5
MIN_RMS = 235.0  # ~ -43 dBFS
MAX_RMS = 32768.0


@dataclass(frozen=True)
class VADDecision:
    kind: str
    replay_start: int | None = None
    replay_pcm: bytes | None = None
    rms: float | None = None
    threshold: float | None = None


class LocalFollowupVAD:
    def __init__(self, *, deadline: float, armed_at: float,
                 sample_cursor: int):
        if not 0 < deadline-armed_at <= DIALOGUE_IDLE_SECONDS+.01:
            raise ValueError("followup_window_not_finite")
        if type(sample_cursor) is not int or sample_cursor < 0:
            raise ValueError("followup_sample_cursor_invalid")
        self.deadline = deadline
        self.armed_at = armed_at
        self.expected = sample_cursor
        self.preroll = deque(maxlen=PREROLL_FRAMES)
        self.noise_floor = 70.0
        self.consecutive_speech = 0
        self.silent = 0
        self.voice_frames = 0
        self.total_active_frames = 0
        self.active = False
        self.complete = False

    def feed(self, *, pcm: bytes, index: int, now: float,
             rms: float) -> VADDecision | None:
        if self.complete:
            return None
        # The browser playback ACK may arrive while Core.feed runs in a
        # worker thread. An already in-flight frame predating the ACK must
        # be skipped; the NEXT canonical frame begins at self.expected.
        if (index == self.expected-FRAME_SAMPLES
                and 0 <= self.armed_at-now <= .5):
            return None
        if (index == self.expected
                and 0 < self.armed_at-now <= .5):
            self.expected += FRAME_SAMPLES
            return None
        if (not isinstance(pcm, bytes) or len(pcm) != BYTES_PER_FRAME
                or type(index) is not int or index != self.expected
                or not isinstance(now, (float, int))
                or not math.isfinite(now) or now < self.armed_at
                or not isinstance(rms, (float, int))
                or not math.isfinite(rms)
                or not 0 <= rms <= MAX_RMS):
            self.complete = True
            raise ValueError("followup_audio_position_or_level_invalid")
        self.expected += FRAME_SAMPLES
        threshold = max(MIN_RMS, self.noise_floor*2.8)
        speech = rms >= threshold
        if not self.active and now >= self.deadline:
            self.complete = True
            return VADDecision("expired", rms=rms, threshold=threshold)
        if not self.active and now-self.armed_at < SPEAKER_ECHO_GUARD_SECONDS:
            self.preroll.clear()
            self.consecutive_speech = 0
            return None
        self.preroll.append((index, pcm))
        if not self.active:
            if speech:
                self.consecutive_speech += 1
            else:
                self.consecutive_speech = 0
                self.noise_floor = .94*self.noise_floor+.06*rms
            if self.consecutive_speech < START_VOICE_FRAMES:
                return None
            self.active = True
            self.voice_frames = self.consecutive_speech
            self.total_active_frames = 0
            self.silent = 0
            # Whole 960-sample frames, no sample reorder/duplicate.
            replay = b"".join(p for _,p in self.preroll)
            self.preroll.clear()
            return VADDecision("start", index-
                               (len(replay)//BYTES_PER_FRAME-1)*FRAME_SAMPLES,
                               replay, rms=rms, threshold=threshold)
        self.total_active_frames += 1
        if speech:
            self.voice_frames += 1
            self.silent = 0
        else:
            self.silent += 1
        if self.total_active_frames >= MAX_UTTERANCE_FRAMES:
            self.complete = True
            return VADDecision("commit_max_duration", rms=rms,
                               threshold=threshold)
        if self.silent >= SILENCE_FRAMES:
            self.complete = True
            return VADDecision("commit_silence", rms=rms, threshold=threshold)
        return None

    @property
    def speech_active(self):
        return self.active and not self.complete
