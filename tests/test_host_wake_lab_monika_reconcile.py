"""No mic: test that display name never corrupts true Monika hit counts."""
import copy
import unittest

from services.voice.host_wake_lab.gobi_guided_live import catalog, summarize
from services.voice.host_wake_lab.monika_human_reconcile import correct_metadata


def raw_fixture():
    def one(i,kind,primary,shadow,condition="continuous"):
        return {
            "id":i,"kind":kind,"condition":condition,"owner_confirmed":True,
            "primary_event_count":primary,"shadow_event_count":shadow,
            "capture_duration_s":6.0,"mic_peak_dbfs":-22.3,
        }
    return {
        "schema":"gobot_host_b_gobi_live_v1",
        "candidate":"monika","spelling":"Моника",
        "one_candidate_only":True,
        "primary_engine_live":"vosk","shadow_engine_postcapture":"t-one",
        "audio_saved":False,"trace_hypothesis_text_persisted":False,
        "paid_calls":0,"excluded":[],"capture_errors":[],
        "actual_background_exposure_s":12.0,
        "cue_api_proxies":[{"phrase_id":"monika"},{"phrase_id":"monika"}],
        "trials":[
            one("monika-isolated1","positive",0,1,"isolated"),
            one("monika-weather","positive",1,1),
            one("monika-time","positive",1,1),
            one("negative-monitor","negative",0,0,"near"),
            one("negative-room","negative",0,0,"conversation"),
            one("tv","negative",0,0,"TV_background"),
        ],
    }


class MonikaReclassificationTests(unittest.TestCase):
    def test_catalog_expected_is_id_not_human_readable_display(self):
        for name in ("monika","gobi","hey_gobi","globi"):
            positive,_=catalog(name)
            for prompt in positive:
                self.assertEqual(prompt[3],name)  # used for scoring
                self.assertIsInstance(prompt[4],str)  # displayed UI
        expected=catalog("monika")[0][0][3]
        self.assertEqual(expected,"monika")
        matched=summarize("positive",expected,[{"phrase_id":"monika"}])
        self.assertTrue(matched["hit"])

    def test_recover_actual_counts_from_one_candidate_event_counts(self):
        data=raw_fixture()
        data["actual_background_exposure_s"]=12.0
        result=correct_metadata(data)
        self.assertEqual(result["models"]["vosk"]["wake_events_detected"],2)
        self.assertEqual(result["models"]["vosk"]["misses"],1)
        self.assertEqual(result["models"]["t-one"]["wake_events_detected"],3)
        self.assertEqual(result["models"]["t-one"]["misses"],0)
        self.assertEqual(result["models"]["vosk"]["false_events"],0)
        self.assertIsNone(result["models"]["vosk"]["false_wakes_per_hour"])
        self.assertFalse(result["activation_approved"])

    def test_reject_unverified_candidate_or_cue_or_exclusion(self):
        data=raw_fixture()
        cases=[]
        bad=copy.deepcopy(data);bad["candidate"]="gobi";cases.append(bad)
        bad=copy.deepcopy(data);bad["one_candidate_only"]=False;cases.append(bad)
        bad=copy.deepcopy(data);bad["cue_api_proxies"]=[{"phrase_id":"gobi"},{"phrase_id":"monika"}];cases.append(bad)
        bad=copy.deepcopy(data);bad["cue_api_proxies"]=[];cases.append(bad)
        bad=copy.deepcopy(data);bad["trials"][0]["owner_confirmed"]=False;cases.append(bad)
        bad=copy.deepcopy(data);bad["excluded"]=[{"id":"monika-time"}];cases.append(bad)
        bad=copy.deepcopy(data);bad["trials"][0]["primary_event_count"]=2;cases.append(bad)
        for case in cases:
            with self.subTest(case=str(case)[:45]),self.assertRaises(ValueError):
                correct_metadata(case)


if __name__=="__main__":
    unittest.main()
