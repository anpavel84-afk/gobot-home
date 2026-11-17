"""Free, no-microphone tests for the bounded human self-annotation harness."""
import contextlib
import io
import sys
import unittest
from unittest import mock

from services.voice.host_wake_lab.detect import Hypothesis
from services.voice.host_wake_lab.guided_live import (
    TRIALS, make_summary, process_pcm, score_trial, prompt_confirm,
    pcm_signal_levels, main,
)


class FakeBackend:
    detector_id = "fake_guided"
    model_version = "fake"
    license = "test-only"
    native_rate = 16000
    streaming = True
    def __init__(self):
        self.resets = 0
    def feed_pcm(self, pcm):
        return Hypothesis("Гобот какая сегодня погода")
    def reset(self):
        self.resets += 1


class ScoringTests(unittest.TestCase):
    def test_positive_exact_and_wrong_candidate(self):
        got = score_trial("positive", "gobot",
                          [{"phrase_id": "gabot"}, {"phrase_id": "gobot"}])
        self.assertEqual(got, {"hit": True, "wrong_candidates": 1,
                               "false_events": 0})
        miss = score_trial("positive", "gobot", [{"phrase_id": "gabot"}])
        self.assertFalse(miss["hit"])
        self.assertEqual(miss["wrong_candidates"], 1)

    def test_background_false_events_are_counted_not_per_hour(self):
        self.assertEqual(score_trial("negative", None,
                         [{"phrase_id": "gobot"}])["false_events"], 1)
        self.assertEqual(score_trial("tv_background", None,
                         [])["false_events"], 0)
        with self.assertRaises(ValueError):
            score_trial("positive", None, [])

    def test_stable_human_prompt_catalog(self):
        targets = {x[0]: (x[1], x[2], x[3]) for x in TRIALS}
        self.assertEqual(len(TRIALS), 13)
        self.assertEqual(targets["gobot-weather"][1], "gobot")
        self.assertIn("БЕЗ ПАУЗЫ", targets["gobot-weather"][2])
        self.assertEqual(targets["vot-weather"][0], "negative")

    def test_model_summary_has_no_fake_latency(self):
        report = make_summary("fake", FakeBackend())
        self.assertIsNone(report["name_end_to_ack_p95_ms"])
        self.assertIsNone(report["false_wakes_per_hour"])

    def test_shadow_replay_respects_sample_indexes_and_resets(self):
        backend = FakeBackend()
        pcm = bytearray(b"\0\0" * 960 * 5)
        got = process_pcm(backend, pcm, "trial-123")
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["phrase_id"], "gobot")
        self.assertEqual(got[0]["end_sample_index"], 2880)
        self.assertGreaterEqual(backend.resets, 2)

    def test_empty_enter_reprompts_not_silent_skip(self):
        inputs = iter(["", "yes"])
        warnings = []
        accepted = prompt_confirm(input_fn=lambda _: next(inputs),
                                  output_fn=warnings.append)
        self.assertTrue(accepted)
        self.assertEqual(len(warnings), 1)
        self.assertIn("НЕ засчитывает", warnings[0])

    def test_confirmation_accepts_yes_and_russian_da(self):
        for word in ("y", "yes", "да", "д", "YES", " ДА "):
            with self.subTest(word=word):
                self.assertTrue(prompt_confirm(input_fn=lambda _, w=word: w))
        for word in ("n", "no", "нет", "НЕТ"):
            with self.subTest(word=word):
                self.assertFalse(prompt_confirm(input_fn=lambda _, w=word: w))

    def test_signal_levels_only_not_original_pcm(self):
        import numpy as np
        pcm = bytearray(np.array([16384] * 16000, dtype="<i2").tobytes())
        metric = pcm_signal_levels(pcm)
        self.assertEqual(metric, {"rms_dbfs": -6.0, "peak_dbfs": -6.0})
        silent = pcm_signal_levels(bytearray(b"\x00\x00" * 500))
        self.assertLess(silent["peak_dbfs"], -100.0)
        self.assertIsInstance(metric["rms_dbfs"], float)

    def test_default_consent_gate_exits_before_models_or_mic(self):
        output = io.StringIO()
        with mock.patch.object(sys, "argv", [
                "guided_live", "--models-root", "not-installed"]):
            with contextlib.redirect_stdout(output):
                main()
        self.assertIn("NOT_RUN_CONSENT_REQUIRED", output.getvalue())

    def test_bound_guard_before_consent(self):
        with mock.patch.object(sys, "argv", [
                "guided_live", "--models-root", "not-installed",
                "--trial-seconds", "8", "--rounds", "3",
                "--owner-consent-live"]):
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as ctx:
                    main()
        self.assertEqual(ctx.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
