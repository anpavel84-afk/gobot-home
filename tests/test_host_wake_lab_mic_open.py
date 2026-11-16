"""No-microphone regression: trace first frame & report capture-open errors safely."""
import unittest
from unittest.mock import patch

from services.voice.host_wake_lab.detect import Hypothesis
from services.voice.host_wake_lab.guided_live import capture_live


class FakeBackend:
    detector_id = "fake-mic"
    def feed_pcm(self, pcm):
        return Hypothesis("гоби", updated=True)
    def reset(self):
        pass


class FakeRawInputStream:
    def __init__(self, *, callback, **kwargs):
        self.callback = callback
        self.kwargs = kwargs
    def __enter__(self):
        self.callback(b"\x00\x00" * 960, 960, None, None)
        return self
    def __exit__(self, *_):
        return False


def bounded_clock():
    values = iter((1.0, 2.0, 4.0))
    return lambda: next(values, 4.0)


class MicOpenRegression(unittest.TestCase):
    def test_first_raw_frame_with_live_trace_does_not_crash(self):
        updates = []
        with patch("sounddevice.RawInputStream", FakeRawInputStream), \
             patch("time.monotonic", side_effect=bounded_clock()):
            pcm, events, epoch, lag = capture_live(
                FakeBackend(), device=1, seconds=2.0, candidate_id="gobi",
                on_hypothesis=lambda hyp, idx: updates.append((hyp.text, idx)),
            )
        self.assertEqual(len(pcm), 1920)
        self.assertEqual(updates, [("гоби", 960)])
        self.assertEqual(events, [])
        self.assertTrue(epoch)
        self.assertGreaterEqual(lag, 0)

    def test_low_level_device_failure_propagates_without_capture(self):
        class FailingRawInputStream:
            def __init__(self, **kwargs):
                pass
            def __enter__(self):
                raise OSError("simulated device unavailable")
            def __exit__(self, *_):
                return False
        with patch("sounddevice.RawInputStream", FailingRawInputStream):
            with self.assertRaisesRegex(OSError, "device unavailable"):
                capture_live(FakeBackend(), device=21, seconds=2.0,
                             candidate_id="gobi")


if __name__ == "__main__":
    unittest.main()
