"""HOST-B harness gates: prohibit synthetic->human claims and unstated data."""
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import wave

from services.voice.host_wake_lab.harness import (
    load_manifest, nearest_ranks, MIN_LATENCY_TRIALS,
)
from services.voice.host_wake_lab.local_command import parse_local_intent, time_answer


class LocalIntentTests(unittest.TestCase):
    def test_russian_time_intents(self):
        self.assertEqual(parse_local_intent("Гобот, который час?").kind, "time")
        self.assertEqual(parse_local_intent("Сколько времени сейчас?").kind, "time")
        self.assertIsNone(parse_local_intent("Какое сегодня время года?"))

    def test_timer_has_real_local_spec(self):
        x = parse_local_intent("Гобот поставь таймер на 3 минуты")
        self.assertIsNotNone(x)
        self.assertEqual((x.kind, x.seconds), ("timer", 180))
        self.assertEqual(parse_local_intent("таймер 15 секунд").seconds, 15)
        self.assertIsNone(parse_local_intent("таймер на 999 минут"))
        self.assertIsNone(parse_local_intent("таймер на пять минут"))

    def test_time_answer_is_deterministic(self):
        from datetime import datetime
        self.assertEqual(time_answer(datetime(2026, 11, 16, 15, 7)),
                         "Сейчас 15 часов 7 минут.")


class CorpusGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        with wave.open(str(self.root / "sample.wav"), "wb") as f:
            f.setnchannels(1)
            f.setframerate(16000)
            f.setsampwidth(2)
            f.writeframes(b"\0\0" * 16000)
        self.sample = {
            "id": "one", "source": "synthetic", "kind": "positive",
            "path": "sample.wav", "expected_phrase": "gobot",
        }

    def manifest(self, **updates):
        sample = {**self.sample, **updates}
        path = self.root / "manifest.json"
        path.write_text(json.dumps({"samples": [sample]}, ensure_ascii=False),
                        encoding="utf-8")
        return path

    def test_synthetic_loaded_but_not_human_latency(self):
        clips, fingerprint = load_manifest(self.manifest())
        self.assertEqual(clips[0]["source"], "synthetic")
        self.assertEqual(len(fingerprint), 64)

    def test_consented_requires_explicit_flag(self):
        with self.assertRaises(PermissionError):
            load_manifest(self.manifest(source="consented"))

    def test_no_unlabeled_private_fixture(self):
        with self.assertRaises(ValueError):
            load_manifest(self.manifest(source="private"))

    def test_reject_wrong_pcm_digest(self):
        with self.assertRaises(ValueError):
            load_manifest(self.manifest(pcm_sha256="0" * 64))

    def test_reject_unannotated_positive(self):
        with self.assertRaises(ValueError):
            load_manifest(self.manifest(expected_phrase=None))

    def test_quantiles_gated_until_20_annotated_trials(self):
        self.assertIsNone(nearest_ranks([50] * (MIN_LATENCY_TRIALS - 1))["p95_ms"])
        p = nearest_ranks(list(range(20)))
        self.assertEqual(p["p50_ms"], 9.5)
        self.assertEqual(p["p95_ms"], 18.1)


if __name__ == "__main__":
    unittest.main()
