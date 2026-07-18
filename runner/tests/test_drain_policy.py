import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import drain_policy


class DrainPolicyTest(unittest.TestCase):
    def test_explicit_drain_skips_improve_but_allows_prewarm(self):
        with patch.dict(os.environ, {"ORCH_DRAIN_MODE": "true"}, clear=False):
            self.assertTrue(drain_policy.should_skip("improve"))
            self.assertFalse(drain_policy.should_skip("prewarm"))

    def test_auto_mode_uses_queue_floor(self):
        with patch.dict(
            os.environ,
            {"ORCH_DRAIN_MODE": "auto", "ORCH_DRAIN_QUEUE_FLOOR": "10"},
            clear=False,
        ):
            self.assertFalse(drain_policy.should_skip("improve", queue_depth=9))
            self.assertTrue(drain_policy.should_skip("improve", queue_depth=10))

    def test_non_generator_is_not_skipped(self):
        with patch.dict(os.environ, {"ORCH_DRAIN_MODE": "true"}, clear=False):
            self.assertFalse(drain_policy.should_skip("merge_train.py"))

    # --- skip_reason coverage ---

    def test_skip_reason_returns_mode_when_explicit(self):
        with patch.dict(os.environ, {"ORCH_DRAIN_MODE": "true"}, clear=False):
            reason = drain_policy.skip_reason("scout")
            self.assertIn("drain_mode=true", reason)

    def test_skip_reason_returns_auto_with_floor(self):
        with patch.dict(
            os.environ,
            {"ORCH_DRAIN_MODE": "auto", "ORCH_DRAIN_QUEUE_FLOOR": "5"},
            clear=False,
        ):
            reason = drain_policy.skip_reason("scout", queue_depth=10)
            self.assertIn("auto", reason)
            self.assertIn("5", reason)

    def test_skip_reason_empty_when_not_skipped(self):
        with patch.dict(os.environ, {"ORCH_DRAIN_MODE": "false"}, clear=False):
            self.assertEqual(drain_policy.skip_reason("scout"), "")

    # --- enabled coverage ---

    def test_enabled_false_when_off(self):
        with patch.dict(os.environ, {"ORCH_DRAIN_MODE": "off"}, clear=False):
            self.assertFalse(drain_policy.enabled())

    def test_enabled_true_when_on(self):
        with patch.dict(os.environ, {"ORCH_DRAIN_MODE": "on"}, clear=False):
            self.assertTrue(drain_policy.enabled())

    def test_enabled_false_for_unknown_mode(self):
        with patch.dict(os.environ, {"ORCH_DRAIN_MODE": "bananas"}, clear=False):
            self.assertFalse(drain_policy.enabled())

    # --- status coverage ---

    def test_status_returns_expected_keys(self):
        with patch.dict(os.environ, {"ORCH_DRAIN_MODE": "false"}, clear=False):
            s = drain_policy.status()
            self.assertIn("enabled", s)
            self.assertIn("mode", s)
            self.assertIn("floor", s)
            self.assertIn("skip_jobs", s)
            self.assertIn("allow_jobs", s)
            self.assertFalse(s["enabled"])
            self.assertEqual(s["mode"], "false")
            self.assertIsInstance(s["skip_jobs"], list)
            self.assertIsInstance(s["allow_jobs"], list)


if __name__ == "__main__":
    unittest.main()
