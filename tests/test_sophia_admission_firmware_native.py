"""Compile the actual incremental patch's fixed native admission UI state."""
from pathlib import Path
import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HOST = ROOT/"firmware/spotpear/host"


class SophiaAdmissionFirmwareNativeTests(unittest.TestCase):
    def test_incremental_manifest_preserves_exact_installed_wake_sources(self):
        manifest = json.loads((HOST/"sophia_admission_v417_manifest.json").read_text())
        parent = HOST/"sophia_unified_v4_manifest.json"
        self.assertEqual(hashlib.sha256(parent.read_bytes()).hexdigest(), manifest["parent_manifest_sha256"])
        baseline = json.loads(parent.read_text())
        self.assertEqual(manifest["baseline_app_sha256"], baseline["candidate_app_sha256"])
        self.assertEqual(manifest["baseline_app_size"], baseline["candidate_app_size"])
        self.assertEqual(manifest["baseline_version"], "0.4.16-dev-sophia-unified-v4")
        self.assertEqual(manifest["candidate_version"], "0.4.17-dev-sophia-ui-v4")
        self.assertEqual(manifest["model"], "wn10_sophia")
        self.assertEqual(manifest["detector_mode"], "DET_MODE_95")
        self.assertEqual(manifest["protected_binary_hashes"], baseline["protected_binary_hashes"])
        self.assertEqual(manifest["sdkconfig_sha256"], baseline["sdkconfig_sha256"])
        changed = set(manifest["candidate_sources"])
        self.assertEqual(changed, {"CMakeLists.txt", "main/gobot_build_info.h", "main/application.cc",
            "main/application.h", "main/host_rc1_app.inc", "main/host_admission_ui.h", "main/touch_lcd.h"})
        for name in ("main/embedded_sophia_engine.hpp", "main/sophia_pcm_tap.hpp",
                "main/audio/audio_service.cc", "main/audio/engines/afe_audio_engine.cc",
                "main/audio/engines/lite_audio_engine.cc", "main/sophia_host_capture.h",
                "main/host_output_receipts.h", "main/protocols/websocket_protocol.cc", "dependencies.lock"):
            self.assertIn(name, manifest["protected_source_paths"])
            self.assertNotIn(name, changed)

    def test_real_cpp_helper_scope_types_persistence_priority_and_render_receipts(self):
        if not shutil.which("g++"):
            self.skipTest("native C++ compiler unavailable")
        manifest = json.loads((HOST/"sophia_admission_v417_manifest.json").read_text())
        patch = HOST/"sophia_admission_v417.patch"
        self.assertEqual(hashlib.sha256(patch.read_bytes()).hexdigest(), manifest["patch_sha256"])
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            (workspace/"main").mkdir()
            subprocess.run(["git", "apply", "--include=main/host_admission_ui.h", str(patch)],
                cwd=workspace, check=True, capture_output=True)
            self.assertEqual(hashlib.sha256((workspace/"main/host_admission_ui.h").read_bytes()).hexdigest(),
                manifest["candidate_sources"]["main/host_admission_ui.h"])
            executable = workspace/"test"
            subprocess.run(["g++", "-std=c++17", "-Wall", "-Wextra", "-Werror", "-I", str(workspace/"main"),
                str(HOST/"test_sophia_admission_v417.cc"), "-o", str(executable)], check=True, capture_output=True)
            result = subprocess.run([str(executable)], check=True, capture_output=True, text=True)
            self.assertIn("PASS admission scope/types/enums/persistence/native receipts", result.stdout)


if __name__ == "__main__":
    unittest.main()
