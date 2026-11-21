"""Shared HOST-A local Monika wake adapter for both physical and browser inputs.

Both sources supply canonical AudioChunk(PCM16 mono 16k, epoch, sample index).
Exact HOST-B Vosk detector and HOST-A HostCore are reused, never forked.
RAM-only pre-roll: 2 seconds by default for physical A; Browser Lab can opt into 5 seconds for late-final Vosk hypotheses. One wake per transport epoch.
"""
from __future__ import annotations

from collections import deque
import threading

from host_wake_contract import AudioChunk, WakeEvent


class WakeGate:
    def __init__(self, *, capacity_samples: int = 32000):
        # Physical A remains at the original 2s default; Browser Lab may
        # request up to 5s so late-final Vosk name audio is not lost.
        if (type(capacity_samples) is not int or
                not 32000 <= capacity_samples <= 80000):
            raise ValueError("wake_preroll_capacity_invalid")
        self.capacity_samples = capacity_samples
        self.lock = threading.Lock()
        self.frame_window = deque()
        self.window_samples = 0
        self.epoch = None
        self.pending = None
        self.observed = 0

    def feed(self, chunk: AudioChunk, event: WakeEvent | None):
        with self.lock:
            if self.epoch != chunk.stream_epoch:
                self.epoch = chunk.stream_epoch
                self.frame_window.clear()
                self.window_samples = 0
                self.pending = None  # no replay across reconnect/epochs
            self.frame_window.append(chunk)
            self.window_samples += len(chunk.pcm_s16le) // 2
            while self.window_samples > self.capacity_samples and len(self.frame_window) > 1:
                old = self.frame_window.popleft()
                self.window_samples -= len(old.pcm_s16le) // 2
            if event is not None:
                if not isinstance(event, WakeEvent) or event.phrase_id != "monika":
                    raise RuntimeError("unexpected_non_monika_detector_event")
                if self.pending is None:
                    self.observed += 1
                    self.pending = (
                        event, self.frame_window[0].sample_index,
                        b"".join(c.pcm_s16le for c in self.frame_window)
                    )

    def take(self):
        with self.lock:
            item = self.pending
            self.pending = None
            return item

    def clear(self):
        with self.lock:
            self.frame_window.clear()
            self.window_samples = 0
            self.pending = None
            self.epoch = None


class DetectorAdapter:
    """A-owned observer around the same B-model MonikaEndpointAdapter."""

    def __init__(self, delegate, gate):
        self.inner = delegate
        self.gate = gate
        self.inner.suppress_events = False

    @property
    def suppress_events(self):
        return self.inner.suppress_events

    @suppress_events.setter
    def suppress_events(self, value):
        self.inner.suppress_events = bool(value)

    @property
    def frames(self):
        return self.inner.frames

    @property
    def events(self):
        return self.inner.events

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def feed_chunk(self, chunk):
        event = self.inner.feed_chunk(chunk)
        self.gate.feed(chunk, event)
        return event

    def reset(self):
        self.inner.reset()
