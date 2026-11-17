"""Owner selected Моника; no-mic model/contract/false-word tests."""
import contextlib
import io
import sys
import unittest
from unittest import mock

from services.voice.host_wake_lab.bridge import HostWakeDetectorAdapter
from services.voice.host_wake_lab.detect import Hypothesis
from services.voice.host_wake_lab.gobi_policy import (
    CANDIDATES, CANDIDATE_DISPLAY, candidate_for, CandidateMatcher
)
from services.voice.host_wake_lab.gobi_guided_live import catalog, main


class FakeMonika:
    detector_id = "fake-monika"
    def feed_pcm(self, _: bytes):
        return Hypothesis("Моника какая сегодня погода", updated=True)
    def reset(self):
        pass


class MonikaTests(unittest.TestCase):
    def test_distinct_explicit_initial_word_only(self):
        self.assertEqual(CANDIDATES["monika"],("моника",))
        self.assertEqual(CANDIDATE_DISPLAY["monika"],"Моника")
        for phrase in ("Моника", "Моника, сколько времени?",
                       "Моника какая сегодня погода"):
            self.assertEqual(candidate_for(phrase, "monika"),"monika")
        for phrase in ("монитор", "мониторинг", "моник", "монику", "монике",
                       "Моня", "монтировка", "Гоби", "Эй Моника",
                       "Мы с Моникой встретились",
                       "Комика", "Моникаша", "монетарный"):
            with self.subTest(phrase=phrase):
                self.assertIsNone(candidate_for(phrase,"monika"))
        self.assertFalse("monika" in CANDIDATES["gobi"])

    def test_single_candidate_latches_only_after_two_updates(self):
        m=CandidateMatcher("monika",min_stability_samples=1600)
        self.assertIsNone(m.observe("Моника",960))
        self.assertIsNone(m.observe("Моника",1920))
        self.assertEqual(m.observe("Моника",2880),"monika")
        self.assertIsNone(m.observe("Моника",3840))
        m.reset()
        self.assertIsNone(m.observe("Монитор",960))
        self.assertIsNone(m.observe("Моника",1920))

    def test_actual_HOST_A_adapter_shadow_is_default(self):
        bridge=HostWakeDetectorAdapter(FakeMonika(),candidate_id="monika")
        for i in range(4):
            chunk=type("Chunk",(),{
                "pcm_s16le":b"\0\0"*960, "stream_epoch":"monika_test",
                "sample_index":960*i,
                "received_monotonic_ns":1_000_000_000+60_000_000*i})()
            self.assertIsNone(bridge.feed_chunk(chunk))
        self.assertEqual(bridge.shadow_candidate_count,1)
        self.assertEqual(bridge.last_shadow_candidate["phrase_id"],"monika")

    def test_catalog_includes_realistic_negative_words(self):
        positives,negatives=catalog("monika")
        self.assertEqual(len(positives),6)
        self.assertTrue(all(p[3]=="monika" for p in positives))
        self.assertTrue(all("Моника" in p[4] for p in positives))
        negids={n[0] for n in negatives}
        for name in ("negative-monitor","negative-monik","negative-monya",
                     "negative-monika-mention", "negative-room"):
            self.assertIn(name,negids)
        self.assertFalse(any(t[0].startswith("a_gobi") for t in positives))

    def test_live_runner_without_owner_flag_refuses_capture(self):
        output=io.StringIO()
        with mock.patch.object(sys,"argv",[
             "lab", "--candidate", "monika", "--models-root","none",
             "--quick","--trace-all","--background-tv"]), \
             contextlib.redirect_stdout(output):
            main()
        self.assertIn("NOT_RUN_CONSENT_REQUIRED",output.getvalue())


if __name__=="__main__":
    unittest.main()
