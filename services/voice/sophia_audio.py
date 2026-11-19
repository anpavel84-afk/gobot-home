"""Capture-clock PCM history and one burst-to-live cursor for Sophia protocol v2.

No detector, cloud client, credentials or disk audio are owned here.  The same
ordered Opus decoder serves the whole device stream; history contains decoded
PCM, never independently decoded historical Opus packets.  Positions are in
the unchanged V4 pre-AFE mono 16 kHz capture clock.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from fractions import Fraction
from typing import Callable
import time


class AudioContinuityError(ValueError):
    """The caller must terminate this input and negotiate a fresh stream epoch."""


@dataclass(frozen=True)
class PcmBlock:
    stream_epoch: str
    frame_id: int
    sample_start: int
    sample_count: int
    pcm: bytes

    @property
    def end(self):
        return self.sample_start + self.sample_count


@dataclass
class InputCursor:
    wake_id: str
    stream_epoch: str
    position: int
    detector_sample: int
    selected_start: int
    pre_roll_flushed: bool = False
    sent_samples: int = 0


class PcmRing:
    """Bounded RAM history with fail-closed discontinuities and privacy floors.

    ``read_available`` advances exactly one cursor.  Calling it after each
    append handles arbitrarily long live questions; ring capacity is a limit on
    unsent history, not on question duration.  A wake that precedes its matching
    packet remains pending until the detector position is present.
    """

    def __init__(self, seconds=10, *, sample_rate=16000, clock=time.monotonic,
                 on_event: Callable[[dict], None] | None = None):
        if sample_rate != 16000 or not 1 <= seconds <= 60:
            raise ValueError('invalid_sophia_ring_bounds')
        self.rate = sample_rate
        self.capacity = int(seconds * sample_rate)
        self.clock = clock
        self.on_event = on_event
        self.events = deque(maxlen=256)
        self.blocks: deque[PcmBlock] = deque()
        self.epoch: str | None = None
        self.next_frame: int | None = None
        self.end = 0
        self.floor = 0
        self.blocked = False
        self.cursor: InputCursor | None = None
        self.seen_wakes = deque(maxlen=128)
        self.frames = deque(maxlen=128)

    def event(self, event, **fields):
        obj = {'event': event, 'plan_monotonic': self.clock(), **fields}
        self.events.append(obj)
        if self.on_event:
            self.on_event(obj)
        return obj

    def reset(self, stream_epoch: str, *, sample_start=0):
        if not isinstance(stream_epoch, str) or not 1 <= len(stream_epoch) <= 128:
            raise ValueError('invalid_stream_epoch')
        if type(sample_start) is not int or sample_start < 0:
            raise ValueError('invalid_sample_position')
        previous = self.epoch
        self.blocks.clear()
        self.frames.clear()
        self.cursor = None
        self.next_frame = None
        self.epoch = stream_epoch
        self.end = self.floor = sample_start
        self.event('stream_epoch_started', stream_epoch=stream_epoch,
                   previous_epoch=previous, sample_start=sample_start)

    @property
    def oldest(self):
        return self.blocks[0].sample_start if self.blocks else self.end

    @staticmethod
    def metadata(metadata):
        values = [metadata.get(k) for k in ('frame_id', 'sample_start', 'sample_count')]
        if any(type(v) is not int for v in values):
            raise ValueError('invalid_frame_position')
        frame, start, count = values
        if frame < 0 or start < 0 or count != 960:
            raise ValueError('invalid_60ms_frame_position')
        epoch = metadata.get('stream_epoch')
        if not isinstance(epoch, str) or not 1 <= len(epoch) <= 128:
            raise ValueError('invalid_stream_epoch')
        return epoch, frame, start, count

    def classify(self, metadata):
        """Validate *before* decoding, so duplicate Opus never advances a codec."""
        epoch, frame, start, count = self.metadata(metadata)
        if epoch != self.epoch:
            raise AudioContinuityError('stream_epoch_not_negotiated')
        if (frame, start, count) in self.frames:
            self.event('duplicate_frame', stream_epoch=epoch, frame_id=frame)
            return 'duplicate'
        if self.next_frame is not None and frame != self.next_frame:
            self.event('frame_gap', expected_frame=self.next_frame, actual_frame=frame)
            raise AudioContinuityError('frame_gap_requires_new_epoch')
        if start != self.end:
            self.event('sample_gap', expected_sample=self.end, actual_sample=start)
            raise AudioContinuityError('sample_gap_requires_new_epoch')
        return 'new'

    def append(self, metadata, pcm: bytes):
        if self.classify(metadata) == 'duplicate':
            return False
        epoch, frame, start, count = self.metadata(metadata)
        if not isinstance(pcm, bytes) or len(pcm) != count * 2:
            raise ValueError('decoded_sample_count_mismatch')
        self.end = start + count
        self.next_frame = frame + 1
        self.frames.append((frame, start, count))
        if self.blocked:
            self.floor = max(self.floor, self.end)
            return True
        self.blocks.append(PcmBlock(epoch, frame, start, count, pcm))
        minimum = max(self.floor, self.end - self.capacity)
        while self.blocks and self.blocks[0].end <= minimum:
            self.blocks.popleft()
        if self.blocks and self.blocks[0].sample_start < minimum:
            first = self.blocks.popleft()
            skip = minimum - first.sample_start
            self.blocks.appendleft(PcmBlock(epoch, first.frame_id, minimum,
                                           first.sample_count - skip, first.pcm[skip * 2:]))
        if self.cursor and self.cursor.position < self.oldest:
            self.event('input_overrun', wake_id=self.cursor.wake_id,
                       unsent_start=self.cursor.position, oldest_sample=self.oldest)
            self.cursor = None
            raise AudioContinuityError('input_cursor_overrun')
        return True

    def begin(self, wake, *, pre_roll_seconds=1.0):
        if self.blocked:
            raise PermissionError('microphone_blocked')
        if not .0 <= pre_roll_seconds <= 2.0:
            raise ValueError('invalid_pre_roll')
        epoch = wake.get('stream_epoch')
        wake_id = wake.get('wake_id')
        detector = wake.get('detector_sample')
        if epoch != self.epoch:
            raise AudioContinuityError('wake_epoch_mismatch')
        if not isinstance(wake_id, str) or not 1 <= len(wake_id) <= 128:
            raise ValueError('invalid_wake_id')
        if type(detector) is not int or detector < self.floor:
            raise ValueError('wake_before_allowed_audio')
        if detector > self.end + self.rate * 2:
            raise ValueError('wake_too_far_ahead')
        if wake_id in self.seen_wakes:
            self.event('duplicate_wake', wake_id=wake_id)
            return False
        if self.cursor:
            raise ValueError('input_cursor_already_active')
        desired = max(self.floor, detector - int(pre_roll_seconds * self.rate))
        start = max(desired, self.oldest)
        if start > desired:
            self.event('pre_roll_shortfall', wake_id=wake_id,
                       missing_samples=start - desired)
        self.seen_wakes.append(wake_id)
        self.cursor = InputCursor(wake_id, epoch, start, detector, start)
        self.event('wake_detected', wake_id=wake_id, stream_epoch=epoch,
                   detector_sample=detector,
                   detector_monotonic_us=wake.get('detector_monotonic_us'),
                   selected_start=start, clock_domain='capture_16k')
        return True

    def read_available(self, *, max_samples=8000):
        """Return ordered (sample_start, PCM) chunks, with no real-time pacing."""
        cursor = self.cursor
        if not cursor or self.blocked or self.end < cursor.detector_sample:
            return []
        if max_samples < 1 or max_samples > self.rate:
            raise ValueError('invalid_input_chunk_bound')
        if cursor.position < max(self.floor, self.oldest):
            raise AudioContinuityError('input_cursor_range_missing')
        output = []
        while cursor.position < self.end:
            limit = min(self.end, cursor.position + max_samples)
            first = cursor.position
            raw = bytearray()
            for block in self.blocks:
                if block.end <= cursor.position:
                    continue
                if block.sample_start >= limit:
                    break
                lo = max(cursor.position, block.sample_start)
                hi = min(limit, block.end)
                if lo != cursor.position + len(raw) // 2:
                    raise AudioContinuityError('input_cursor_internal_gap')
                raw.extend(block.pcm[(lo-block.sample_start)*2:(hi-block.sample_start)*2])
            if len(raw) != (limit-first)*2:
                raise AudioContinuityError('input_cursor_range_missing')
            output.append((first, bytes(raw)))
            cursor.position = limit
            cursor.sent_samples += len(raw)//2
        return output

    def acknowledge_sent(self, sample_end):
        """Local WS send completion only; never implies a provider append ACK."""
        cursor = self.cursor
        if cursor and not cursor.pre_roll_flushed and sample_end >= cursor.detector_sample:
            cursor.pre_roll_flushed = True
            self.event('pre_roll_flushed', wake_id=cursor.wake_id,
                       selected_start=cursor.selected_start, sample_end=sample_end,
                       receipt='client_send_completed_not_provider_ack')

    def stop(self, reason='input_finished'):
        if self.cursor:
            self.event(reason, wake_id=self.cursor.wake_id,
                       sent_samples=self.cursor.sent_samples)
        self.cursor = None

    def set_blocked(self, blocked: bool, *, sample_floor=None, reason='mute'):
        if type(blocked) is not bool:
            raise ValueError('invalid_microphone_gate')
        if sample_floor is not None and (type(sample_floor) is not int or sample_floor < self.end):
            raise ValueError('invalid_capture_floor')
        self.stop('input_cancelled')
        self.blocked = blocked
        self.blocks.clear()
        self.floor = max(self.floor, self.end, sample_floor or 0)
        self.event('audio_gate_changed', blocked=blocked, reason=reason,
                   eligible_sample_start=self.floor)


class ContinuousPcm24:
    """One stateful high-quality resampler per *utterance*, never per chunk."""

    def __init__(self):
        import av
        self.av = av
        self.resampler = av.AudioResampler(format='s16', layout='mono', rate=24000)
        self.input_samples = 0
        self.output_samples = 0
        self.closed = False

    def feed(self, pcm: bytes):
        if self.closed or len(pcm) % 2:
            raise ValueError('invalid_resampler_input')
        if not pcm:
            return b''
        frame = self.av.AudioFrame(format='s16', layout='mono', samples=len(pcm)//2)
        frame.planes[0].update(pcm)
        frame.sample_rate = 16000
        frame.time_base = Fraction(1, 16000)
        frame.pts = self.input_samples
        self.input_samples += frame.samples
        data = b''.join(f.to_ndarray().astype('<i2', copy=False).tobytes()
                        for f in self.resampler.resample(frame))
        self.output_samples += len(data)//2
        return data

    def finish(self):
        if self.closed:
            return b''
        self.closed = True
        data = b''.join(f.to_ndarray().astype('<i2', copy=False).tobytes()
                        for f in self.resampler.resample(None))
        self.output_samples += len(data)//2
        return data


class OrderedOpus:
    """The existing 60 ms decoder, scoped to exactly one capture epoch."""

    def __init__(self, ring: PcmRing, decoder_factory=None):
        if decoder_factory is None:
            from host_stream import StreamOpus
            decoder_factory = StreamOpus
        self.ring = ring
        self.decoder_factory = decoder_factory
        self.decoder = None

    def reset(self, epoch, *, sample_start=0):
        if self.decoder:
            self.decoder.close()
        self.ring.reset(epoch, sample_start=sample_start)
        self.decoder = self.decoder_factory()

    def feed(self, metadata, packet):
        if self.ring.classify(metadata) == 'duplicate':
            return False
        if self.decoder is None:
            raise AudioContinuityError('decoder_epoch_missing')
        # A codec failure is terminal for this epoch; never silently skip a packet.
        try:
            pcm = self.decoder.feed(packet)
            return self.ring.append(metadata, pcm)
        except Exception:
            self.decoder.close()
            self.decoder = None
            self.ring.stop('decoder_discontinuity')
            raise

    def close(self):
        if self.decoder:
            self.decoder.close()
        self.decoder = None
        self.ring.stop('stream_closed')
        self.ring.blocks.clear()
