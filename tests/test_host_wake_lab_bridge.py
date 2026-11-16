"""HOST-A adapter remains shadow-only until explicit integration approval."""
from dataclasses import dataclass
import unittest

from services.voice.host_wake_lab.bridge import ShadowWakePort
from services.voice.host_wake_lab.detect import Hypothesis, WakeLab


class Fake:
    detector_id = "fake"
    def feed_pcm(self, pcm): return Hypothesis("Гобот какая погода")
    def reset(self): pass


@dataclass
class CanonicalAChunk:
    pcm_s16le: bytes
    stream_epoch: str
    sample_index: int
    receive_monotonic: float


class BridgeTest(unittest.TestCase):
    def test_default_shadow_cannot_emit_action(self):
        delivered = []
        adapter = ShadowWakePort(WakeLab(Fake()), on_event=delivered.append)
        found = []
        for i in range(3):
            found += adapter.feed_audio_chunk(CanonicalAChunk(
                b"\0\0" * 960, "epoch1", i * 960, 100.0 + i))
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["phrase_id"], "gobot")
        self.assertEqual(delivered, [])

    def test_approved_sink_receives_exactly_one_event(self):
        delivered = []
        adapter = ShadowWakePort(WakeLab(Fake()),
                                 on_event=delivered.append, host_a_accepted=True)
        for i in range(6):
            adapter.feed_audio_chunk({
                "pcm_s16le": b"\0\0" * 960, "stream_epoch": "e",
                "sample_index": i * 960, "receive_monotonic": 100.0 + i,
            })
        self.assertEqual(len(delivered), 1)
        self.assertEqual(delivered[0]["end_sample_index"], 2880)

    def test_no_approval_without_sink(self):
        with self.assertRaises(ValueError):
            ShadowWakePort(WakeLab(Fake()), host_a_accepted=True)


if __name__ == "__main__":
    unittest.main()
