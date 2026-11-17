"""Static-only tests: never load microphone, model, speaker audio or GPU."""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent


class SourceSafety(unittest.TestCase):
    def test_python_training_modules_parse(self):
        for filename in ("synthesize.py", "synthesize_v2.py",
                         "train_monika.py", "train_monika_v2.py",
                         "evaluate_heldout.py", "synthesize_v3_holdout.py",
                     "merge_v3.py", "train_monika_v3.py",
                     "evaluate_v3.py"):
            with self.subTest(module=filename):
                ast.parse((ROOT/filename).read_text(encoding="utf-8"))

    def test_private_model_data_never_in_public_git(self):
        excluded={".tflite", ".pcm", ".wav", ".flac", ".bin",
                  ".npy", ".npz", ".h5", ".elf"}
        for path in ROOT.rglob("*"):
            if path.is_file():
                self.assertNotIn(path.suffix.lower(),excluded)
        ignores=(ROOT/".gitignore").read_text()
        for pattern in ("*.tflite","*.pcm","*.h5","*.bin"):
            self.assertIn(pattern,ignores)

    def test_seven_voice_split_and_confusables(self):
        src=(ROOT/"synthesize.py").read_text(encoding="utf-8")
        for item in ('"denis":"train"', '"dmitri":"train"',
                     '"anna":"train"', '"irina":"train"',
                     '"espeak-ru":"train"',
                     '"aleksandr":"validation"','"elena":"test"'):
            self.assertIn(item,src)
        for name in ("Моник","Моня","Монику","монитор","лимонника","маньяка"):
            self.assertIn(name,src)

    def test_no_H0_mutation_or_paid_provider_in_source(self):
        text=(ROOT/"README.md").read_text(encoding="utf-8")
        self.assertIn("READ ONLY",text)
        self.assertIn("exclusively HOST-A",text)
        modules=(ROOT/"train_monika.py").read_text(encoding="utf-8")
        self.assertIn('CUDA_VISIBLE_DEVICES","-1"',modules)
        self.assertIn("tf.config.set_visible_devices([],\"GPU\")",modules)
        self.assertNotIn("OpenAI(",modules)
        self.assertNotIn("esptool",modules)

    def test_actual_public_results_do_not_mark_models_accepted(self):
        import json
        r=json.loads((ROOT/"PUBLIC_MODEL_COMPARISON.json").read_text(encoding="utf8"))
        self.assertFalse(r["native_device_wake_accepted"])
        self.assertFalse(r["user_recorded_audio_used"])
        self.assertEqual(r["paid_calls"],0)
        expected={"v1":(39,35),"v2":(45,57),"v3":(29,9)}
        for v,(tp,fp) in expected.items():
            model=r["versions"][v]
            self.assertFalse(model["human_accepted"])
            self.assertEqual(len(model["model_sha256"]),64)
            if v=="v3":
                got=model["heldout"]["elena"]
                self.assertEqual(model["heldout"]["aleksandr-hq"]["detected"],4)
            else:
                got=model["heldout_elena"]
            self.assertEqual(got["detected"],tp)
            self.assertEqual(got["false_events"],fp)

    def test_private_firmware_manifest_is_metadata_only(self):
        import json
        doc=json.loads((ROOT/"PUBLIC_MCU_BUILD_MANIFEST.json").read_text(encoding="utf8"))
        self.assertFalse(doc["current_device_flashed"])
        self.assertFalse(doc["includes_HOST_A_RC1_firmware"])
        self.assertFalse(doc["human_acoustic_accepted"])
        self.assertFalse(doc["embedded_model_partition_required"])
        self.assertEqual(doc["standalone_initial_full_build_steps"],1332)
        self.assertEqual(doc["artifacts_private_sha256_only"]["model_v3"]["size_bytes"],47416)
        self.assertEqual(doc["artifacts_private_sha256_only"]["standalone_v3"]["size_bytes"],378352)
        self.assertFalse(list(ROOT.rglob("*.bin")))
        self.assertFalse(list(ROOT.rglob("*.tflite")))

    def test_standalone_app_not_an_installer(self):
        main=(ROOT/"esp32_standalone"/"main"/"main.cpp").read_text(encoding="utf-8")
        self.assertIn("NO_DEVICE_AUDIO",main)
        self.assertIn("FrontendProcessSamples",main)
        self.assertIn("MicroInterpreter",main)
        self.assertIn("monika_int8_tflite_start",main)
        self.assertFalse((ROOT/"esp32_standalone"/"main"/"monika_int8.tflite").is_file())


if __name__=="__main__":
    unittest.main()
