"""Monika integration is shadow by default; events only for explicit A-owned test."""
from dataclasses import dataclass
import unittest
from unittest.mock import patch

from services.voice.host_wake_lab.detect import Hypothesis
from services.voice.host_wake_lab.monika_bridge import make_monika_detector, make_monika_factory


class FakeVosk:
    detector_id="fake-vosk-monika"
    word_ids={"моника":57908}
    def reset(self): pass
    def feed_pcm(self, pcm):
        return Hypothesis("моника какая погода", updated=True)


@dataclass(frozen=True)
class FakeWakeEvent:
    stream_epoch: str
    end_sample_index: int
    phrase_id: str
    detector_id: str
    detected_monotonic_ns: int
    confidence: float | None = None


class FactoryTests(unittest.TestCase):
    def feed_three(self, detector):
        results=[]
        for idx in range(3):
            chunk=type("AudioChunk", (), {
                "pcm_s16le":b"\0\0"*960,
                "stream_epoch":"pilot_test",
                "sample_index":idx*960,
                "received_monotonic_ns":idx*60_000_000,
            })()
            results.append(detector.feed_chunk(chunk))
        return results

    def test_shadow_factory_default_always_refuses_event(self):
        with patch("services.voice.host_wake_lab.monika_bridge.make_candidate_backend",
                   return_value=FakeVosk()) as provider:
            f=make_monika_factory("unused")
            detector=f()
        provider.assert_called_once()
        self.assertFalse(detector.activation_approved)
        self.assertEqual(self.feed_three(detector),[None,None,None])
        self.assertEqual(detector.shadow_candidate_count,1)
        self.assertEqual(detector.last_shadow_candidate["phrase_id"],"monika")

    def test_armed_only_in_isolated_hardware_acceptance(self):
        with self.assertRaises(PermissionError), \
             patch("services.voice.host_wake_lab.monika_bridge.make_candidate_backend",
                   return_value=FakeVosk()):
            make_monika_detector("unused",allow_experimental_events=True)
        with patch("services.voice.host_wake_lab.monika_bridge.make_candidate_backend",
                   return_value=FakeVosk()):
            detector=make_monika_detector(
                "unused",allow_experimental_events=True,
                isolated_hardware_test=True,wake_event_type=FakeWakeEvent)
        events=[x for x in self.feed_three(detector) if x is not None]
        self.assertEqual(len(events),1)
        self.assertIsInstance(events[0],FakeWakeEvent)
        self.assertEqual(events[0].phrase_id,"monika")
        self.assertEqual(events[0].end_sample_index,2880)

    def test_vosk_vocabulary_gate_fails_closed(self):
        backend=FakeVosk()
        backend.word_ids={"моника":-1}
        with patch("services.voice.host_wake_lab.monika_bridge.make_candidate_backend",
                   return_value=backend):
            with self.assertRaisesRegex(ValueError,"out_of_vocabulary"):
                make_monika_detector("unused")

    def test_no_invalid_cpu_thread_count(self):
        for n in (-1,0,3,1.0,True):
            with self.subTest(n=n), self.assertRaises(ValueError):
                make_monika_detector("unused",threads=n)


if __name__=="__main__":
    unittest.main()
