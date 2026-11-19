"""Compile the actual public patch's pure C++ state and capture boundaries."""
from pathlib import Path
import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HOST = ROOT/"firmware/spotpear/host"


class SophiaFirmwareNativeTests(unittest.TestCase):
    def test_patch_state_clock_cancel_and_physical_fences(self):
        if not shutil.which("g++"):
            self.skipTest("native C++ compiler unavailable")
        manifest = json.loads((HOST/"sophia_unified_v4_manifest.json").read_text())
        patch = HOST/"sophia_unified_v4.patch"
        self.assertEqual(hashlib.sha256(patch.read_bytes()).hexdigest(),
                         manifest["patch_sha256"])
        self.assertEqual(manifest["detector_mode"], "DET_MODE_95")
        protected = ("main/embedded_sophia_engine.hpp", "main/sophia_pcm_tap.hpp",
                     "main/audio/engines/afe_audio_engine.cc",
                     "main/audio/engines/lite_audio_engine.cc", "dependencies.lock")
        for relative in protected:
            self.assertNotIn(relative, manifest["candidate_sources"])
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            (workspace/"main").mkdir()
            for name in ("host_rc1_state.h", "host_client_state.h"):
                raw = (HOST/name).read_bytes()
                expected = manifest["baseline_sources"]["main/"+name]
                if hashlib.sha256(raw).hexdigest() != expected:
                    # The installed V4 sources omit the final newline; the
                    # public legacy fixture contains that one text newline.
                    self.assertTrue(raw.endswith(b"\n"))
                    raw = raw[:-1]
                self.assertEqual(hashlib.sha256(raw).hexdigest(), expected)
                (workspace/"main"/name).write_bytes(raw)
            command = ["git", "apply",
                       "--include=main/host_rc1_state.h",
                       "--include=main/host_output_receipts.h",
                       "--include=main/sophia_host_capture.h", str(patch)]
            subprocess.run(command, cwd=workspace, check=True, capture_output=True)
            executable = workspace/"test"
            subprocess.run(["g++", "-std=c++17", "-Wall", "-Wextra", "-Werror",
                            "-pthread", "-I", str(workspace/"main"),
                            str(HOST/"test_sophia_unified_v4.cc"), "-o", str(executable)],
                           check=True, capture_output=True)
            result = subprocess.run([str(executable)], check=True, capture_output=True, text=True)
            self.assertIn("PASS", result.stdout)


if __name__ == "__main__":
    unittest.main()
