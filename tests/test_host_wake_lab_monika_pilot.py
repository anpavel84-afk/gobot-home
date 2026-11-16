"""One-shot physical pilot safety gates; never opens COM, mic, TLS or LAN."""
import contextlib
import io
import sys
import unittest
from unittest.mock import patch
from services.voice.host_wake_lab.monika_host_pilot import (
    physical_test_gates, safe_runtime_paths, main,
)


class PilotGuardsTest(unittest.TestCase):
    def test_only_isolated_host_a_port(self):
        for port in (18082, 8765, 18798, 18800, 0):
            with self.subTest(port=port), self.assertRaises(PermissionError):
                physical_test_gates(allow_events=True,isolated_port=port,
                                    trial_seconds=60)

    def test_finite_short_test_only(self):
        for seconds in (0, 5, 14, 181, 2000):
            with self.subTest(seconds=seconds), self.assertRaises(ValueError):
                physical_test_gates(allow_events=False,isolated_port=18799,
                                    trial_seconds=seconds)
        self.assertEqual(physical_test_gates(
            allow_events=False,isolated_port=18799,trial_seconds=120),
            "SHADOW_ONLY")
        self.assertEqual(physical_test_gates(
            allow_events=True,isolated_port=18799,trial_seconds=120),
            "EXPERIMENTAL_TEST_ONLY")

    def test_refuses_wrong_port_before_any_model_or_private_file(self):
        with patch.object(sys,"argv",[
              "pilot","--models-root","nonexistent",
              "--port","18798","--preflight-only"]), \
             self.assertRaises(PermissionError):
            main()


if __name__=="__main__":
    unittest.main()
