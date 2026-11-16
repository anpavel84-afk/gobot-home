"""One-way HOST-A integration port, intentionally no network or gateway imports.

Accept a mapping/object from HOST-A's canonical AudioChunk contract. Do not
duplicate AudioChunk/WakeEvent dataclasses: the A-owned source of truth wins.
Activation is *off by default*, regardless of detected candidates.
"""
from __future__ import annotations

from typing import Any, Callable, Mapping

from .detect import WakeLab


def _read(chunk: Any, key: str) -> Any:
    if isinstance(chunk, Mapping):
        return chunk[key]
    return getattr(chunk, key)


class ShadowWakePort:
    """Return shadow candidates and optionally call A's callback after acceptance."""

    def __init__(self, lab: WakeLab, *, on_event: Callable[[dict], None] | None = None,
                 host_a_accepted: bool = False):
        if host_a_accepted and on_event is None:
            raise ValueError("event_sink_required_for_activation")
        self.lab = lab
        self.on_event = on_event
        self.accepted = bool(host_a_accepted)

    def feed_audio_chunk(self, audio_chunk, *, speaking: bool = False) -> list[dict]:
        """AudioChunk: pcm_s16le, stream_epoch, sample_index, receive_monotonic."""
        events = self.lab.feed(
            pcm_s16le=_read(audio_chunk, "pcm_s16le"),
            stream_epoch=_read(audio_chunk, "stream_epoch"),
            sample_index=_read(audio_chunk, "sample_index"),
            receive_monotonic=_read(audio_chunk, "receive_monotonic"),
            speaking=speaking,
        )
        if self.accepted and self.on_event is not None:
            for event in events:
                self.on_event(dict(event))
        return events

    def reset(self) -> None:
        self.lab.reset()
