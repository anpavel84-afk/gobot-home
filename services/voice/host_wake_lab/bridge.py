"""HOST-B adapter for HOST-A's authoritative contract_v1.

A owns AudioChunk, WakeEvent and single activation in HostCore.
This adapter does not create a second shared contract type, gateway or Brain.
It is shadow-only by default: feed_chunk returns None until acceptance.
"""
from __future__ import annotations

import importlib
import time
from typing import Any

from .detect import WakeLab


def _host_a_event_type():
    # HOST-A's sanitized branch owns this module. Do not vendor a duplicate.
    for module_name in ("host_wake_contract", "services.voice.host_wake_contract"):
        try:
            return importlib.import_module(module_name).WakeEvent
        except ModuleNotFoundError as exc:
            if exc.name not in (module_name, module_name.split(".")[0]):
                raise
    raise RuntimeError("HOST_A_CONTRACT_NOT_INSTALLED")


class HostWakeDetectorAdapter:
    """Implements HostWakeDetector.feed_chunk(AudioChunk)->WakeEvent|None, reset()."""

    def __init__(self, backend, *, activation_approved: bool = False,
                 wake_event_type=None, clock=time.monotonic_ns,
                 candidate_id: str | None = None):
        if candidate_id is None:
            matcher = None  # legacy GoBot words, retained only for old tests
        else:
            from .gobi_policy import CandidateMatcher
            matcher = CandidateMatcher(candidate_id)
        self.lab = WakeLab(backend, clock=clock, matcher=matcher)
        self.candidate_id = candidate_id
        self.activation_approved = bool(activation_approved)
        self.wake_event_type = wake_event_type
        self.last_shadow_candidate = None
        self.shadow_candidate_count = 0

    def feed_chunk(self, chunk: Any):
        """Consume the actual A-owned AudioChunk fields, no time conversion."""
        events = self.lab.feed(
            pcm_s16le=chunk.pcm_s16le,
            stream_epoch=chunk.stream_epoch,
            sample_index=chunk.sample_index,
            received_monotonic_ns=chunk.received_monotonic_ns,
        )
        if not events:
            return None
        if len(events) != 1:
            raise RuntimeError("multiple_wake_events_on_single_frame")
        event = events[0]
        self.shadow_candidate_count += 1
        self.last_shadow_candidate = event
        if not self.activation_approved:
            return None  # An unaccepted recognizer may never activate A.
        cls = self.wake_event_type or _host_a_event_type()
        return cls(**event)

    def reset(self):
        self.lab.reset()
        self.last_shadow_candidate = None
