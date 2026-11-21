"""HOST-A experimental streaming-first cloud STT controller.

A one-turn owner with a bounded PCM queue, offline wake-only trigger and
finite OpenAI session. Opens the paid WSS as soon as the existing local
Monika WakeEvent is accepted, queues ongoing 60 ms Spotpear PCM immediately,
then commits on the single A-owned end-of-utterance event. No cloud standby
and no disk audio/transcript. PCM discontinuity/reconnect fails closed.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
import time
from typing import Callable

from host_a_cloud_transcribe import CloudTranscriber
from host_a_paid_budget import HostPaidTrialBudget
from host_wake_contract import AudioChunk, WakeEvent
from host_local_command import classify_command
from host_a_natural_time_voice import OpenAITimeVoice


class LiveTurnFault(RuntimeError):
    pass


class HostAStreamingTurn:
    """One per authenticated Spotpear connection, never shared across epochs."""

    def __init__(self, gate, budget: HostPaidTrialBudget, *,
                 key_loader: Callable[[], str],
                 voice_cache: OpenAITimeVoice | None = None,
                 client_factory=None, max_frames: int = 96,
                 max_cloud_seconds: int = 30, clock=time.monotonic):
        if not 8 <= max_frames <= 128:
            raise ValueError("bounded_cloud_live_buffer_required")
        if not 5 <= max_cloud_seconds <= 30:
            raise ValueError("bounded_cloud_trial_duration_required")
        self.gate = gate
        self.budget = budget
        self.voice_cache = voice_cache
        self.key_loader = key_loader
        self.client_factory = client_factory or (
            lambda: CloudTranscriber(budget, key_loader=key_loader)
        )
        self.clock = clock
        self.buffer = asyncio.Queue(maxsize=max_frames)
        self.max_cloud_seconds = max_cloud_seconds
        self.task = None
        self.active = False
        self.ended = False
        self.aborted = False
        self.expected_cursor = None
        self.epoch = None
        self.start_at = None
        self.end_at = None
        self.fault = None
        self.frames_forwarded = 0
        self.max_live_frames_buffered = 0

    def _abort(self, reason):
        self.fault = reason
        self.active = False
        self.ended = True
        self.aborted = True
        if self.task is not None and not self.task.done():
            self.task.cancel()
        print("HOST_A_CLOUD_LIVE_ABORT=" + reason, flush=True)

    async def on_wake(self, event):
        """Called only by A after HostCore accepted an actual Monika wake."""
        if event.get("source") != "host_wake" or event.get("event") != "wake":
            return False
        if self.task is not None:
            # One Owner-paid worker per active hardware turn.
            raise LiveTurnFault("duplicate_cloud_wake_in_one_turn")
        item = self.gate.take()
        if item is None or len(item) != 3:
            raise LiveTurnFault("no_local_wake_event_for_streaming")
        candidate, start, replay = item
        if (not isinstance(candidate, WakeEvent)
                or candidate.phrase_id != "monika"
                or candidate.stream_epoch != self.gate.epoch
                or candidate.end_sample_index !=
                    start + len(replay) // 2):
            raise LiveTurnFault("local_wake_stream_position_mismatch")

        self.epoch = candidate.stream_epoch
        self.expected_cursor = candidate.end_sample_index
        self.start_at = self.clock()
        self.active = True
        self.ended = False
        self.task = asyncio.create_task(self.client_factory().transcribe(
            candidate=candidate, epoch=candidate.stream_epoch,
            replay_start=start, replay_pcm16=replay,
            next_frames=self._frames(), max_session_seconds=self.max_cloud_seconds,
        ))
        # Task creation does not block audio receive; it opens paid STT on
        # next event loop iteration, overlapping subsequent human speech.
        print("HOST_A_CLOUD_STREAMING_START_AFTER_WAKE", flush=True)
        return True

    async def on_followup(self, *, permit, conversation_id,
                          epoch, replay_start: int, replay_pcm16: bytes):
        """Open one finite STT only after local VAD detects new user speech.

        This does not invent a WakeEvent. A one-shot permit is derived from
        the previously OpenAI-confirmed first 'Моника' and expires locally.
        Reuse the same single CloudTranscriber and live PCM queue as initial.
        """
        if self.task is not None:
            raise LiveTurnFault("followup_duplicate_cloud_session")
        if (not isinstance(replay_pcm16, bytes)
                or not 0 < len(replay_pcm16) <= 32000
                or len(replay_pcm16) % 1920
                or type(replay_start) is not int or replay_start < 0):
            raise LiveTurnFault("invalid_followup_audio")
        self.epoch = epoch
        self.expected_cursor = replay_start + len(replay_pcm16)//2
        self.start_at = self.clock()
        self.active = True
        self.ended = False
        self.task = asyncio.create_task(
            self.client_factory().transcribe_followup(
                permit=permit, conversation_id=conversation_id,
                epoch=epoch, replay_start=replay_start,
                replay_pcm16=replay_pcm16, next_frames=self._frames(),
                max_session_seconds=self.max_cloud_seconds))
        print("HOST_A_CLOUD_FOLLOWUP_LOCAL_SPEECH_START", flush=True)
        return True

    async def _frames(self):
        while True:
            chunk = await self.buffer.get()
            if chunk is None:
                return
            yield chunk

    def offer(self, chunk: AudioChunk):
        """Non-blocking on the hardware 60 ms audio receive path."""
        if not self.active:
            return
        if (not isinstance(chunk, AudioChunk)
                or chunk.stream_epoch != self.epoch
                or chunk.sample_index != self.expected_cursor):
            self._abort("pcm_epoch_or_sample_gap")
            return
        try:
            self.buffer.put_nowait(chunk)
        except asyncio.QueueFull:
            self._abort("bounded_cloud_live_queue_overflow")
            return
        self.expected_cursor = chunk.end_sample_index
        self.frames_forwarded += 1
        self.max_live_frames_buffered = max(
            self.max_live_frames_buffered, self.buffer.qsize()
        )

    async def finish(self):
        """Exactly one client-owned end-of-turn; no second VAD in the API."""
        if self.task is None or self.ended:
            return
        self.ended = True
        self.active = False
        self.end_at = self.clock()
        try:
            self.buffer.put_nowait(None)
        except asyncio.QueueFull:
            self._abort("no_room_for_cloud_audio_commit")
            return
        print("HOST_A_CLOUD_STREAMING_COMMIT_REQUESTED", flush=True)

    async def verified_result(self):
        """Final real cloud audio-verification for shared Browser/Spotpear pipe."""
        if self.task is None or self.aborted:
            return None
        try:
            outcome = await asyncio.wait_for(
                self.task, timeout=self.max_cloud_seconds + 1)
            # Never print/store private transcript; only metadata.
            print("HOST_A_CLOUD_LIVE_VERDICT=" + outcome.verdict +
                  " PARTIAL_MS=" + str(outcome.first_partial_ms) +
                  " FINAL_MS=" + str(outcome.final_ms) +
                  " AUDIO_S=" + str(outcome.audio_seconds), flush=True)
            return outcome
        except asyncio.CancelledError:
            return None
        except Exception as exc:
            print("HOST_A_STREAMING_FAILED=" + type(exc).__name__, flush=True)
            return None

    async def reply(self):
        """Existing physical local-time path. Browser REAL uses verified_result."""
        outcome = await self.verified_result()
        if outcome is None:
            return None
        try:
            if outcome.verdict != "CONFIRMED":
                return None
            if classify_command(outcome.question or "") != "local_time":
                print("HOST_A_CLOUD_LIVE_NO_LOCAL_TIME_COMMAND", flush=True)
                return None
            if self.voice_cache is None:
                print("HOST_A_NATURAL_VOICE_UNAVAILABLE", flush=True)
                return None
            packets, hit = await asyncio.to_thread(self.voice_cache.get)
            if not hit:
                print("HOST_A_NATURAL_TIME_NOT_PREGENERATED", flush=True)
                return None
            print("HOST_A_NATURAL_TIME_CACHED_PLAYBACK", flush=True)
            return packets
        except asyncio.CancelledError:
            return None
        except Exception as exc:
            print("HOST_A_STREAMING_FAILED=" + type(exc).__name__, flush=True)
            return None

    async def cancel(self):
        self.active = False
        self.ended = True
        if self.task is not None and not self.task.done():
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        # Do not reuse this epoch, audio queue, or result.
        self.aborted = True
