"""Canonical HOST-A v1 adapter is shadow by default, no shared type vendored."""
from dataclasses import dataclass
import unittest

from services.voice.host_wake_lab.bridge import HostWakeDetectorAdapter
from services.voice.host_wake_lab.detect import Hypothesis


class FakeRecognizer:
    detector_id = "fake"
    def feed_pcm(self, pcm): return Hypothesis("Гобот какая погода")
    def reset(self): pass


@dataclass(frozen=True)
class AAudioChunk:
    pcm_s16le: bytes
    stream_epoch: str
    sample_index: int
    received_monotonic_ns: int


@dataclass(frozen=True)
class AWakeEvent:
    stream_epoch: str
    end_sample_index: int
    phrase_id: str
    detector_id: str
    detected_monotonic_ns: int
    confidence: float | None = None


class BridgeTest(unittest.TestCase):
    def test_default_shadow_cannot_emit_action(self):
        adapter = HostWakeDetectorAdapter(FakeRecognizer(), clock=lambda: 42)
        outputs = []
        for i in range(6):
            outputs.append(adapter.feed_chunk(AAudioChunk(
                b"\0\0" * 960, "epoch1", i * 960, 100_000_000_000 + i * 60_000_000,
            )))
        self.assertEqual(outputs, [None] * 6)
        self.assertEqual(adapter.shadow_candidate_count, 1)
        self.assertEqual(adapter.last_shadow_candidate["phrase_id"], "gobot")

    def test_A_approved_event_exact_ns_and_one_only(self):
        adapter = HostWakeDetectorAdapter(
            FakeRecognizer(), activation_approved=True,
            wake_event_type=AWakeEvent, clock=lambda: 25_500_000_000,
        )
        outputs = []
        for i in range(6):
            outputs.append(adapter.feed_chunk(AAudioChunk(
                b"\0\0" * 960, "epoch1", i * 960, 1_000_000_000 + i * 60_000_000,
            )))
        fired = [o for o in outputs if o is not None]
        self.assertEqual(fired, [AWakeEvent(
            "epoch1", 2880, "gobot", "fake", 25_500_000_000, None,
        )])
        adapter.reset()
        self.assertIsNone(adapter.last_shadow_candidate)

    def test_monotonic_ns_must_be_int(self):
        adapter = HostWakeDetectorAdapter(FakeRecognizer())
        with self.assertRaises(ValueError):
            adapter.feed_chunk(AAudioChunk(b"\0\0" * 960, "e", 0, 1.5))


if __name__ == "__main__":
    unittest.main()
