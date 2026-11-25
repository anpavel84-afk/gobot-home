"""HOST-B source-only guarded Sophia RC1-r3 regression, no device I/O."""
from pathlib import Path
import unittest

BASE=Path(__file__).resolve().parent
PATCH=BASE/"sophia_rc1_diagnostic_SOURCE_ONLY.patch"
HANDOFF=BASE/"HOST_A_SOPHIA_DIAGNOSTIC_HANDOFF.md"


class SophiaRC1DiagnosticStatic(unittest.TestCase):
    def test_exact_six_source_paths_only(self):
        value=PATCH.read_text(encoding="utf8")
        old=[x[6:] for x in value.splitlines() if x.startswith("--- a/")]
        assert len(old)==6,old
        self.assertEqual(set(old),{
            "main/CMakeLists.txt",
            "main/idf_component.yml",
            "main/audio/audio_service.cc",
            "main/audio/audio_service.h",
            "main/application.cc",
            "main/host_rc1_app.inc",
        })
        for item in ("gobot_ca.pem","gobot_host_rc1_private.h",
                     "sdkconfig","partitions/v2/16m.csv","nvs.bin"):
            self.assertFalse(any(path.endswith("/"+item) for path in old))

    def test_default_off_and_idle_only(self):
        s=PATCH.read_text(encoding="utf8")
        self.assertIn("sophia_diagnostic_requested_{false}",s)
        self.assertIn('GOBOT_SOPHIA_TEST_ON',s)
        self.assertIn('GOBOT_SOPHIA_TEST_OFF',s)
        self.assertIn("GetDeviceState()!=kDeviceStateIdle",s)
        self.assertIn("IsAudioProcessorRunning()",s)
        self.assertIn("IsSophiaDiagnosticEnabled()",s)

    def test_cooldown_fix_and_cleanup_present(self):
        s=PATCH.read_text(encoding="utf8")
        self.assertIn("sophia_cooldown_us && now<sophia_cooldown_us",s)
        self.assertIn("sophia_cooldown_us && now>=sophia_cooldown_us",s)
        self.assertIn("if(sophia_ready) {sophia.close(); sophia_ready=false;}",s)
        self.assertIn("SOPHIA_DIAG_MEMORY",s)
        self.assertIn("SOPHIA_LOCAL_DETECTED",s)

    def test_one_existing_pcm_reader(self):
        s=PATCH.read_text(encoding="utf8")
        self.assertIn("pcm.data(),pcm.size(),now,sophia_log,nullptr",s)
        self.assertNotIn("+            if (!ReadAudioData",s)
        self.assertIn("sophia.ingest_existing_pcm",s)
        for item in ("i2s_driver_install", "uart_driver_install",
                     "nvs_set", "nvs_erase", "esp_partition_write",
                     "esp_ota_set_boot_partition"):
            self.assertNotIn(item,s)

    def test_explicit_not_installed_handoff(self):
        t=HANDOFF.read_text(encoding="utf8")
        self.assertIn("3,667,024",t)
        self.assertIn("53b6521146cde1f64e6499d46ba9315218eacb808d6e8ea5208c66faa8187462",t)
        self.assertIn("INSTALLED_ON_SPOTPEAR = NO",t)
        self.assertIn("HOST-A is the sole",t)
        self.assertIn("NOT INSTALLED",t)
        self.assertIn("CONFIG_SR_WN_WN10_SOPHIA=y",t)
        self.assertIn("NVS",t)


if __name__=="__main__":
    unittest.main()
