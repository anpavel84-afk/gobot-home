"""HOST-A / HOST-B interface v1. Pure PCM metadata; no audio persistence or cloud calls.

Canonical capture audio is PCM s16le, mono, 16000 Hz. Timestamp is the PLAN
receiver's monotonic nanoseconds; it is NOT an ESP32 or wall-clock timestamp.
The detector returns an event only; it must not start a conversation or play
a cue. The sole activation owner is HostCore in the authenticated gateway.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Protocol

CONTRACT_VERSION = 1
SAMPLE_RATE = 16000
FRAME_SAMPLES = 960
MAX_PCM_BYTES = FRAME_SAMPLES * 2
_TOKEN = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")
_DETECTOR_TOKEN = re.compile(r"[A-Za-z0-9_.-]{1,64}\Z")


def _token(value: str) -> bool:
    return isinstance(value, str) and _TOKEN.fullmatch(value) is not None


@dataclass(frozen=True, slots=True)
class AudioChunk:
    pcm_s16le: bytes
    stream_epoch: str
    sample_index: int
    received_monotonic_ns: int

    def __post_init__(self) -> None:
        if (not isinstance(self.pcm_s16le, bytes) or
                not 0 < len(self.pcm_s16le) <= MAX_PCM_BYTES or
                len(self.pcm_s16le) % 2):
            raise ValueError("invalid_pcm_chunk")
        if not _token(self.stream_epoch):
            raise ValueError("invalid_stream_epoch")
        if (type(self.sample_index) is not int or self.sample_index < 0 or
                type(self.received_monotonic_ns) is not int or
                self.received_monotonic_ns < 0):
            raise ValueError("invalid_pcm_position")

    @property
    def end_sample_index(self) -> int:
        return self.sample_index + len(self.pcm_s16le) // 2


@dataclass(frozen=True, slots=True)
class WakeEvent:
    stream_epoch: str
    end_sample_index: int
    phrase_id: str
    detector_id: str
    detected_monotonic_ns: int
    confidence: float | None = None

    def __post_init__(self) -> None:
        if (not _token(self.stream_epoch) or not _token(self.phrase_id) or
                not isinstance(self.detector_id, str) or
                not _DETECTOR_TOKEN.fullmatch(self.detector_id)):
            raise ValueError("invalid_wake_identity")
        if (type(self.end_sample_index) is not int or
                self.end_sample_index < 0 or
                type(self.detected_monotonic_ns) is not int or
                self.detected_monotonic_ns < 0):
            raise ValueError("invalid_wake_position")
        if self.confidence is not None:
            if (isinstance(self.confidence, bool) or
                    not isinstance(self.confidence, (int, float)) or
                    not math.isfinite(self.confidence) or
                    not 0 <= self.confidence <= 1):
                raise ValueError("invalid_wake_confidence")


class HostWakeDetector(Protocol):
    """HOST-B supplies a factory returning this protocol after model selection."""

    def feed_chunk(self, chunk: AudioChunk) -> WakeEvent | None:
        """Consume exactly this canonical PCM frame and optionally detect a wake."""
        ...

    def reset(self) -> None:
        """Drop per-utterance decoder state without persisting captured speech."""
        ...
