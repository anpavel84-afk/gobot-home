"""No-model, no-microphone, no-provider deterministic contract checks."""
import unittest

from services.voice.host_wake_lab.detect import (
    DiscontinuousAudio, Hypothesis, WakeLab, WakeMatcher, match_address,
)
from services.voice.host_wake_lab.engines import Decimate2


class FakeBackend:
    detector_id = "fake-pcm"
    def __init__(self, text): self.text, self.resets = text, 0
    def feed_pcm(self, pcm_s16le): return Hypothesis(self.text)
    def reset(self): self.resets += 1


def emit(lab, index, text=None, epoch="e1", speaking=False):
    if text is not None:
        lab.backend.text = text
    return lab.feed(
        pcm_s16le=b"\x00\x00" * 960, stream_epoch=epoch,
        sample_index=index, receive_monotonic=index / 16000 + 1,
        speaking=speaking,
    )


class MatcherTests(unittest.TestCase):
    def test_exact_variants(self):
        expected = {
            "Гобот": "gobot", "ГАБОТ": "gabot", "Эй, Гобот": "hey_gobot",
            "Привет, Гобот": "privet_gobot", "А-Гобот": "a_gobot",
            "Гобот, какая сегодня погода?": "gobot",
            "Габот сколько времени?": "gabot",
        }
        for phrase, got in expected.items():
            with self.subTest(phrase=phrase):
                self.assertEqual(match_address(phrase), got)

    def test_near_misses_and_mentions(self):
        for phrase in ("робот", "работа", "гоп", "габарит", "гобота",
                       "поговорим о гоботе", "телевизор сказал гобот",
                       "эй работа", "поговорим, Гобот"):
            with self.subTest(phrase=phrase):
                self.assertIsNone(match_address(phrase))

    def test_two_updates_then_latch(self):
        m = WakeMatcher()
        self.assertIsNone(m.observe("гобот", 960))
        self.assertIsNone(m.observe("гобот какой", 1920))
        self.assertEqual(m.observe("гобот какая погода", 2880), "gobot")
        self.assertIsNone(m.observe("гобот какая погода", 3840))

    def test_no_update_not_evidence(self):
        b = FakeBackend("гобот")
        l = WakeLab(b)
        emit(l, 0)
        b.feed_pcm = lambda pcm: Hypothesis("гобот", updated=False)
        for index in (960, 1920, 2880):
            self.assertEqual(emit(l, index), [])


class PcmContractTests(unittest.TestCase):
    def test_event_position_and_no_paid_side_effect(self):
        l = WakeLab(FakeBackend("гобот какая сегодня погода"), clock=lambda: 25.5)
        self.assertEqual(emit(l, 0), [])
        self.assertEqual(emit(l, 960), [])
        e = emit(l, 1920)
        self.assertEqual(len(e), 1)
        self.assertEqual(e[0], dict(
            stream_epoch="e1", end_sample_index=2880,
            phrase_id="gobot", detector_id="fake-pcm",
            confidence=None, detected_monotonic=25.5,
        ))
        self.assertEqual(emit(l, 2880), [])

    def test_speaking_does_not_activate(self):
        l = WakeLab(FakeBackend("гобот"))
        for i in range(4):
            self.assertFalse(emit(l, i * 960, speaking=True))

    def test_epoch_resets_and_discontinuous_frame_fail_closed(self):
        l = WakeLab(FakeBackend("гобот"))
        emit(l, 0)
        with self.assertRaises(DiscontinuousAudio):
            emit(l, 1920)
        self.assertFalse(emit(l, 0, epoch="e2"))
        self.assertFalse(emit(l, 960, epoch="e2"))
        self.assertEqual(len(emit(l, 1920, epoch="e2")), 1)

    def test_invalid_payload(self):
        l = WakeLab(FakeBackend(""))
        with self.assertRaises(DiscontinuousAudio):
            l.feed(pcm_s16le=b"\x00", stream_epoch="e", sample_index=0,
                   receive_monotonic=0.0)

    def test_decimation_statefulness(self):
        import numpy as np
        pcm = np.arange(4000, dtype=np.int16).tobytes()
        full = Decimate2().feed(pcm)
        one = Decimate2()
        split = np.concatenate((one.feed(pcm[:1920]), one.feed(pcm[1920:])))
        np.testing.assert_allclose(full, split, atol=1e-6)
        self.assertEqual(len(full), 2000)


if __name__ == "__main__":
    unittest.main()
