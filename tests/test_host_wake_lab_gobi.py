"""No-microphone, no-model correctness tests: four distinct named wake policies."""
import contextlib
import io
import sys
import unittest
from unittest.mock import patch

from services.voice.host_wake_lab.detect import Hypothesis, WakeLab
from services.voice.host_wake_lab.gobi_policy import (
    CANDIDATES, CandidateMatcher, candidate_for,
)
from services.voice.host_wake_lab.gobi_guided_live import catalog, main
from services.voice.host_wake_lab.bridge import HostWakeDetectorAdapter
from services.voice.host_wake_lab.gobi_background_watch import rate_per_hour
from services.voice.host_wake_lab.gobi_reconcile import classify, summarize_run
from services.voice.host_wake_lab.gobi_synthetic import P, NEG


class FakeDecoder:
    detector_id = "fake-gobi-cyrillic"
    def __init__(self, text):
        self.text=text
        self.reset_count=0
    def reset(self):
        self.reset_count += 1
    def feed_pcm(self, pcm):
        return Hypothesis(self.text, updated=True)


def feed(lab, i, *, text=None):
    if text is not None:
        lab.backend.text=text
    return lab.feed(
        pcm_s16le=b"\0\0"*960,stream_epoch="gobi_test",
        sample_index=i*960,
        received_monotonic_ns=1000000000+i*60000000)


class SeparateCandidateTests(unittest.TestCase):
    def test_cyrillic_whole_word_only_and_separate_prefix(self):
        pairs={
            "Гоби, какая сегодня погода?": "gobi",
            "Глоби": "globi",
            "Эй, Гоби": "hey_gobi",
        }
        for utterance,candidate in pairs.items():
            for query in CANDIDATES:
                with self.subTest(text=utterance,detector=query):
                    expected=candidate if candidate==query else None
                    self.assertEqual(candidate_for(utterance,query),expected)

    def test_A_Gobi_is_not_an_active_candidate_or_alias(self):
        self.assertNotIn("a_gobi",CANDIDATES)
        for candidate in CANDIDATES:
            self.assertIsNone(candidate_for("А, Гоби, сколько времени?",candidate))
        with self.assertRaises(ValueError):
            CandidateMatcher("a_gobi")

    def test_false_words_and_background_mentions(self):
        negatives=("гобот","робот","губы","глобус","гобиус",
                   "говорили про Гоби","в пустыне Гоби","гобиный",
                   "Глобальная история","А гобот","Эй робот")
        for name in CANDIDATES:
            for phrase in negatives:
                with self.subTest(name=name,phrase=phrase):
                    self.assertIsNone(candidate_for(phrase,name))

    def test_partial_is_not_success_and_consecutive_updates_required(self):
        b=FakeDecoder("Гоби")
        l=WakeLab(b, matcher=CandidateMatcher("gobi"),clock=lambda:1230000000)
        self.assertEqual(feed(l,0),[])
        self.assertEqual(feed(l,1),[])
        out=feed(l,2)
        self.assertEqual(len(out),1)
        self.assertEqual(out[0]["phrase_id"],"gobi")
        self.assertEqual(out[0]["detected_monotonic_ns"],1230000000)
        self.assertEqual(out[0]["end_sample_index"],2880)
        self.assertEqual(feed(l,3),[])

    def test_other_names_cannot_activate_in_this_detector(self):
        l=WakeLab(FakeDecoder("А Гоби"),matcher=CandidateMatcher("gobi"))
        for i in range(5):
            self.assertEqual(feed(l,i),[])
        self.assertEqual(l.backend.reset_count,1)

    def test_phrase_switch_resets_candidate_stability(self):
        l=WakeLab(FakeDecoder("Гоби"),matcher=CandidateMatcher("gobi"))
        feed(l,0)
        feed(l,1,text="глобус")
        self.assertEqual(feed(l,2,text="гоби"),[])
        self.assertEqual(feed(l,3),[])
        self.assertEqual(len(feed(l,4)),1)

    def test_reconnect_isolated(self):
        l=WakeLab(FakeDecoder("Гоби"),matcher=CandidateMatcher("gobi"))
        feed(l,0)
        feed(l,1)
        out=l.feed(pcm_s16le=b"\0\0"*960,stream_epoch="new",
                   sample_index=0,received_monotonic_ns=1_500_000_000)
        self.assertEqual(out,[])

    def test_A_v1_bridge_gobi_shadow_is_disabled_by_default(self):
        adapter=HostWakeDetectorAdapter(FakeDecoder("Гоби"),candidate_id="gobi",
                                        clock=lambda:55)
        for i in range(4):
            chunk=type("AudioChunk",(),{
                "pcm_s16le":b"\0\0"*960,"stream_epoch":"e",
                "sample_index":i*960,
                "received_monotonic_ns":i*60_000_000})()
            self.assertIsNone(adapter.feed_chunk(chunk))
        self.assertEqual(adapter.shadow_candidate_count,1)
        self.assertEqual(adapter.last_shadow_candidate["phrase_id"],"gobi")

    def test_A_v1_bridge_acceptance_requires_opt_in(self):
        adapter=HostWakeDetectorAdapter(
            FakeDecoder("Глоби"),candidate_id="globi",
            activation_approved=True,wake_event_type=lambda **kw:kw,
            clock=lambda:55)
        event=None
        for i in range(3):
            chunk=type("Chunk",(),{
                "pcm_s16le":b"\0\0"*960,"stream_epoch":"e",
                "sample_index":i*960,
                "received_monotonic_ns":i*60_000_000})()
            event=adapter.feed_chunk(chunk) or event
        self.assertEqual(event["phrase_id"],"globi")
        self.assertEqual(event["end_sample_index"],2880)

    def test_no_auto_activation_when_speaking(self):
        l=WakeLab(FakeDecoder("Гоби"),matcher=CandidateMatcher("gobi"))
        for i in range(5):
            self.assertEqual(l.feed(
                pcm_s16le=b"\0\0"*960,stream_epoch="e",
                sample_index=i*960,received_monotonic_ns=1_000_000_000+i*60_000_000,
                speaking=True),[])


class CatalogTests(unittest.TestCase):
    def test_identical_synthetic_clip_list_and_no_aliasing(self):
        self.assertEqual(len(P),4)  # HISTORICAL frozen PCM corpus, not active names
        self.assertEqual(set(CANDIDATES),{"gobi","hey_gobi","globi","monika"})
        self.assertEqual({len(x) for x in P.values()},{6})
        self.assertEqual(len(NEG),14)
        self.assertNotEqual(P["gobi"][0],P["globi"][0])

    def test_human_lab_single_candidate_only(self):
        for candidate in CANDIDATES:
            positives,negatives=catalog(candidate)
            self.assertEqual(len(positives),6)
            self.assertTrue(all(p[0].startswith(candidate+"-") for p in positives))
            # Never treat the candidate itself as a 'negative cross name'
            self.assertNotIn("negative-"+candidate,[n[0] for n in negatives])
            self.assertTrue(any("robot" in n[0] for n in negatives))
            self.assertFalse(any("a_gobi" in n[0] for n in negatives))

    def test_historical_A_Gobi_is_cross_variant_not_ambient_false(self):
        self.assertEqual(classify("a_gobi_02","gobi"),"historical_address_A_Gobi")
        self.assertEqual(classify("negative_lips","gobi"),"unrelated_speech")
        self.assertEqual(classify("globi_02","gobi"),"other_distinct_address")
        self.assertEqual(classify("gobi_02","gobi"),"target")
        with self.assertRaises(ValueError):
            classify("a_gobi_02","a_gobi")

    def test_historical_fp_reclassification(self):
        run={"candidate_id":"gobi","engine":"t-one","status":"FREE_TESTED_NOT_HUMAN_ACCEPTED",
             "events":[
               {"id":"gobi_00","events":[]},
               {"id":"a_gobi_02","events":[{"phrase_id":"gobi"}]},
               {"id":"negative_robot","events":[]},
               {"id":"negative_gobot","events":[]}
             ]}
        result=summarize_run(run)
        self.assertEqual(result["unrelated_speech_false_events"],0)
        self.assertEqual(result["historical_A_Gobi_variant_events"],1)
        self.assertEqual(result["target_misses"],1)

    def test_false_wakes_hour_requires_independent_background_exposure(self):
        self.assertIsNone(rate_per_hour(0, 1799.99, owner_confirmed=True))
        self.assertIsNone(rate_per_hour(1, 1800, owner_confirmed=False))
        self.assertEqual(rate_per_hour(3, 1800, owner_confirmed=True), 6.0)
        self.assertEqual(rate_per_hour(0, 1800, owner_confirmed=True), 0.0)

    def test_default_no_owner_permission_never_starts_mic(self):
        output=io.StringIO()
        with patch.object(sys,"argv",["gobi_guided_live","--candidate","gobi",
                                    "--models-root","does-not-exist"]):
            with contextlib.redirect_stdout(output):
                main()
        self.assertIn("NOT_RUN_CONSENT_REQUIRED",output.getvalue())

    def test_mic_time_guard_before_owner_consent(self):
        with patch.object(sys,"argv",["gobi_guided_live","--candidate","gobi",
                                    "--models-root","none","--seconds","9",
                                    "--owner-consent-live"]):
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    main()


if __name__=="__main__":
    unittest.main()
