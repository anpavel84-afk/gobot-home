"""HOST-B V3 Sophia automatic wake source-only publication guard."""
from pathlib import Path
import re
import unittest
ROOT=Path(__file__).resolve().parent.parent
PATCH=ROOT/"integration"/"sophia_v3_active_wake_SOURCE_ONLY.patch"
REPORT=ROOT/"HARDWARE_SOPHIA_V3_2026-11-17.md"

class ActiveV3Safety(unittest.TestCase):
    def test_exact_six_reviewable_paths(self):
        s=PATCH.read_text(encoding="utf8")
        old=[x[6:] for x in s.splitlines() if x.startswith("--- a/")]
        self.assertEqual(set(old),{
            "main/audio/audio_service.h",
            "main/audio/audio_service.cc",
            "main/application.cc",
            "main/host_rc1_app.inc",
            "main/gobot_build_info.h",
            "CMakeLists.txt",
        })
        self.assertEqual(len(old),6)

    def test_default_enabled_and_wake_event_wiring(self):
        s=PATCH.read_text(encoding="utf8")
        self.assertIn("sophia_diagnostic_requested_{true}",s)
        self.assertIn("ConsumeSophiaWakePending()",s)
        self.assertIn('on_wake_word_detected("София")',s)
        self.assertIn("StartGoBotTurn",s)
        self.assertIn("sophia_wake_pending_.store(true)",s)
        self.assertIn("local_hold_.store(true)",s)
        self.assertIn("sophia_buffer_handoff_.store(true)",s)

    def test_pre_roll_and_single_local_i2s_and_fallback(self):
        s=PATCH.read_text(encoding="utf8")
        self.assertIn("kSophiaPrefixSamples=32000",s)
        self.assertIn("sophia_question.Observe",s)
        self.assertIn("sophia_question.Append",s)
        self.assertIn("sophia_question.Take",s)
        self.assertIn("SOPHIA_WAKE_PREFIX_OVERFLOW",s)
        self.assertIn("EnableSophiaDiagnostic(true)",s)
        self.assertIn("EnableSophiaDiagnostic(false)",s)
        self.assertNotIn("i2s_driver_install",s)
        self.assertNotIn("erase_flash",s)
        self.assertNotIn("nvs_set",s)

    def test_report_does_not_promise_human_acceptance(self):
        r=REPORT.read_text(encoding="utf8")
        self.assertIn("INSTALLED_SOPHIA_V3 = YES",r)
        self.assertIn("LIVE_USER_SPOKEN_SOFIA_WAKE = NOT_ACCEPTED",r)
        self.assertIn("0d7bd0f65ff4a649eff16660f8bd1ee441a16314ca5bb4ecf7135e0dbd22fadd",r)
        self.assertIn("PARTITION_AND_OTADATA_COMPARE = PASS",r)
        self.assertIn("PERSONAL_AUDIO_RECORDED = NO",r)
        self.assertIn("prior B",r)
if __name__=="__main__":
    unittest.main()
