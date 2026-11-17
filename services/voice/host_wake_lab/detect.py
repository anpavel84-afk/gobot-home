"""Model-independent wake policy and strict PCM16 monotonic transport adapter.

PCM input: s16le mono 16 kHz, stream_epoch, first sample_index,
and received_monotonic_ns. Event output is a plain dict conforming to
the HOST-A contract (issue #5); no second shared type definition.
"""
from __future__ import annotations
from dataclasses import dataclass
import re
import time
from typing import Protocol

SAMPLE_RATE = 16000
WAKE_WORDS = {"гобот": "gobot", "габот": "gabot"}
PREFIXES = {"эй": "hey", "привет": "privet", "а": "a"}
PHRASE_IDS = ("gobot", "gabot", "hey_gobot", "hey_gabot",
              "privet_gobot", "privet_gabot", "a_gobot", "a_gabot")


class DiscontinuousAudio(ValueError):
    """Unsafe frame gaps, malformed PCM, or conflicting epoch positions."""


@dataclass(frozen=True)
class Hypothesis:
    text: str
    endpoint: bool = False
    confidence: float | None = None
    updated: bool = True  # only new decoder output counts as independent evidence


class Backend(Protocol):
    detector_id: str
    def feed_pcm(self, pcm_s16le: bytes) -> Hypothesis: ...
    def reset(self) -> None: ...


def match_address(text: str) -> str | None:
    """Exact Cyrillic word tokens only; no forced one-word grammar or fuzziness.

    Anchor to the opening (up to a supported salutation) so a mention
    of the brand inside unrelated conversation is not a wake.
    """
    tokens = re.findall(r"[а-яё]+", str(text).casefold())
    if not tokens:
        return None
    if tokens[0] in WAKE_WORDS:
        return WAKE_WORDS[tokens[0]]
    if len(tokens) > 1 and tokens[0] in PREFIXES and tokens[1] in WAKE_WORDS:
        return PREFIXES[tokens[0]] + "_" + WAKE_WORDS[tokens[1]]
    return None


class WakeMatcher:
    """Two temporally separated ASR updates before confirmation; latch per segment."""
    def __init__(self, min_stability_samples: int = 1600):
        if min_stability_samples < 1:
            raise ValueError("min_stability_samples")
        self.minimum = min_stability_samples
        self.reset()

    def reset(self) -> None:
        self.candidate: str | None = None
        self.first_at: int | None = None
        self.fired = False

    def observe(self, text: str, end_sample_index: int) -> str | None:
        if self.fired:
            return None
        phrase = match_address(text)
        if phrase is None:
            self.candidate = None
            self.first_at = None
            return None
        if phrase != self.candidate:
            self.candidate = phrase
            self.first_at = end_sample_index
            return None
        if self.first_at is None or end_sample_index - self.first_at < self.minimum:
            return None
        self.fired = True
        return phrase


class WakeLab:
    """One decoder per isolated lab instance. Never opens a paid conversation."""
    def __init__(self, backend: Backend, *, clock=time.monotonic_ns, matcher=None):
        self.backend = backend
        self.detector_id = backend.detector_id
        self.clock = clock
        self.matcher = matcher if matcher is not None else WakeMatcher()
        self.epoch: str | None = None
        self.expected: int | None = None
        self.last_receive: float | None = None
        self.last_text = ""
        self.decoded_frames = 0

    def reset(self) -> None:
        self.backend.reset()
        self.matcher.reset()
        self.epoch = None
        self.expected = None
        self.last_receive = None
        self.last_text = ""
        self.last_hypothesis = None
        self.decoded_frames = 0

    def feed(self, *, pcm_s16le: bytes, stream_epoch: str,
             sample_index: int, received_monotonic_ns: int,
             speaking: bool = False) -> list[dict]:
        if (not isinstance(pcm_s16le, bytes) or not 0 < len(pcm_s16le) <= 1920
                or len(pcm_s16le) % 2):
            raise DiscontinuousAudio("pcm_s16le_mono16_frame_limit")
        if (not isinstance(stream_epoch, str)
                or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", stream_epoch)):
            raise DiscontinuousAudio("stream_epoch_invalid_token")
        if type(sample_index) is not int or sample_index < 0:
            raise DiscontinuousAudio("invalid_sample_index")
        if type(received_monotonic_ns) is not int or received_monotonic_ns < 0:
            raise DiscontinuousAudio("invalid_receive_clock_ns")
        if self.epoch != stream_epoch:
            self.reset()
            self.epoch = stream_epoch
            self.expected = sample_index
        if self.expected != sample_index:
            self.reset()  # fail closed: no skipped/duplicated samples
            raise DiscontinuousAudio("pcm_discontinuity")
        if self.last_receive is not None and received_monotonic_ns < self.last_receive:
            self.reset()
            raise DiscontinuousAudio("nonmonotonic_receive_clock")
        end = sample_index + len(pcm_s16le) // 2
        self.expected = end
        self.last_receive = received_monotonic_ns
        result = self.backend.feed_pcm(pcm_s16le)
        self.last_hypothesis = result
        self.last_text = result.text
        self.decoded_frames += 1
        phrase = None if (speaking or not result.updated) else self.matcher.observe(result.text, end)
        if speaking:
            self.matcher.reset()
        event = []
        if phrase:
            event.append({
                "stream_epoch": stream_epoch,
                "end_sample_index": end,
                "phrase_id": phrase,
                "detector_id": self.detector_id,
                "confidence": result.confidence,
                "detected_monotonic_ns": self.clock(),
            })
        if result.endpoint:
            self.matcher.reset()
        return event
