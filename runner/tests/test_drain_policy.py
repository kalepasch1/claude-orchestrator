import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import drain_policy


class DrainPolicyTest(unittest.TestCase):
    def test_explicit_drain_skips_improve_but_allows_prewarm(self):
        with patch.dict(os.environ, {"ORCH_DRAIN_MODE": "true"}, clear=False):
            self.assertTrue(drain_policy.should_skip("spec"))
            self.assertFalse(drain_policy.should_skip("prewarm"))

    def test_explicit_true_enables(self):
        with patch.dict(os.environ, {"ORCH_DRAIN_MODE": "true"}, clear=False):
            self.assertTrue(drain_policy.enabled())

    def test_explicit_false_disables(self):
        with patch.dict(os.environ, {"ORCH_DRAIN_MODE": "false"}, clear=False):
            self.assertFalse(drain_policy.enabled())

    def test_explicit_yes_enables(self):
        with patch.dict(os.environ, {"ORCH_DRAIN_MODE": "yes"}, clear=False):
            self.assertTrue(drain_policy.enabled())

    def test_explicit_no_disables(self):
        with patch.dict(os.environ, {"ORCH_DRAIN_MODE": "no"}, clear=False):
            self.assertFalse(drain_policy.enabled())

    def test_explicit_1_enables(self):
        with patch.dict(os.environ, {"ORCH_DRAIN_MODE": "1"}, clear=False):
            self.assertTrue(drain_policy.enabled())

    def test_explicit_0_disables(self):
        with patch.dict(os.environ, {"ORCH_DRAIN_MODE": "0"}, clear=False):
            self.assertFalse(drain_policy.enabled())

    def test_garbage_value_disables(self):
        with patch.dict(os.environ, {"ORCH_DRAIN_MODE": "banana"}, clear=False):
            self.assertFalse(drain_policy.enabled())

    def test_case_insensitive(self):
        with patch.dict(os.environ, {"ORCH_DRAIN_MODE": "TRUE"}, clear=False):
            self.assertTrue(drain_policy.enabled())

    def test_auto_mode_below_floor(self):
        with patch.dict(os.environ, {"ORCH_DRAIN_MODE": "auto", "ORCH_DRAIN_QUEUE_FLOOR": "10"}, clear=False):
            self.assertFalse(drain_policy.enabled(queue_depth=9))

    def test_auto_mode_at_floor(self):
        with patch.dict(os.environ, {"ORCH_DRAIN_MODE": "auto", "ORCH_DRAIN_QUEUE_FLOOR": "10"}, clear=False):
            self.assertTrue(drain_policy.enabled(queue_depth=10))

    def test_auto_mode_above_floor(self):
        with patch.dict(os.environ, {"ORCH_DRAIN_MODE": "auto", "ORCH_DRAIN_QUEUE_FLOOR": "10"}, clear=False):
            self.assertTrue(drain_policy.enabled(queue_depth=100))


class DrainPolicySkipTest(unittest.TestCase):
    """Tests for should_skip() job filtering."""

    def test_skip_job_in_default_skip_list(self):
        with patch.dict(os.environ, {"ORCH_DRAIN_MODE": "true"}, clear=False):
            self.assertTrue(drain_policy.should_skip("scout"))

    def test_allow_job_in_default_allow_list(self):
        with patch.dict(os.environ, {"ORCH_DRAIN_MODE": "true"}, clear=False):
            self.assertFalse(drain_policy.should_skip("prewarm"))
            self.assertFalse(drain_policy.should_skip("merge_train.py"))
            self.assertFalse(drain_policy.should_skip("autopilot"))

    def test_unknown_job_not_skipped(self):
        with patch.dict(os.environ, {"ORCH_DRAIN_MODE": "true"}, clear=False):
            self.assertFalse(drain_policy.should_skip("some_random_job_xyz"))

    def test_custom_skip_list_via_env(self):
        with patch.dict(os.environ, {
            "ORCH_DRAIN_MODE": "true",
            "ORCH_DRAIN_SKIP_JOBS": "myjob1,myjob2"
        }, clear=False):
            self.assertTrue(drain_policy.should_skip("myjob1"))
            self.assertFalse(drain_policy.should_skip("scout"))

    def test_custom_allow_list_via_env(self):
        with patch.dict(os.environ, {
            "ORCH_DRAIN_MODE": "true",
            "ORCH_DRAIN_ALLOW_JOBS": "scout"
        }, clear=False):
            self.assertFalse(drain_policy.should_skip("scout"))

    def test_allow_takes_precedence_over_skip(self):
        with patch.dict(os.environ, {
            "ORCH_DRAIN_MODE": "true",
            "ORCH_DRAIN_SKIP_JOBS": "overlap_job",
            "ORCH_DRAIN_ALLOW_JOBS": "overlap_job",
        }, clear=False):
            self.assertFalse(drain_policy.should_skip("overlap_job"))

    def test_skip_disabled_when_drain_off(self):
        with patch.dict(os.environ, {"ORCH_DRAIN_MODE": "false"}, clear=False):
            self.assertFalse(drain_policy.should_skip("scout"))

    def test_queue_depth_passthrough(self):
        with patch.dict(os.environ, {"ORCH_DRAIN_MODE": "auto", "ORCH_DRAIN_QUEUE_FLOOR": "5"}, clear=False):
            self.assertFalse(drain_policy.should_skip("scout", queue_depth=4))
            self.assertTrue(drain_policy.should_skip("scout", queue_depth=5))


class DrainPolicyReasonTest(unittest.TestCase):

    def test_reason_when_explicit(self):
        with patch.dict(os.environ, {"ORCH_DRAIN_MODE": "true"}, clear=False):
            reason = drain_policy.skip_reason("scout")
            self.assertIn("drain_mode=true", reason)

    def test_reason_when_auto(self):
        with patch.dict(os.environ, {"ORCH_DRAIN_MODE": "auto", "ORCH_DRAIN_QUEUE_FLOOR": "5"}, clear=False):
            reason = drain_policy.skip_reason("scout", queue_depth=10)
            self.assertIn("auto", reason)

    def test_no_reason_when_not_skipped(self):
        with patch.dict(os.environ, {"ORCH_DRAIN_MODE": "false"}, clear=False):
            self.assertEqual("", drain_policy.skip_reason("scout"))


class DrainPolicyStatusTest(unittest.TestCase):

    def test_status_returns_dict(self):
        with patch.dict(os.environ, {"ORCH_DRAIN_MODE": "false"}, clear=False):
            s = drain_policy.status()
            self.assertIn("enabled", s)
            self.assertIn("mode", s)
            self.assertIn("floor", s)
            self.assertIn("skip_jobs", s)
            self.assertIn("allow_jobs", s)

    def test_status_floor_default(self):
        env = dict(os.environ)
        env.pop("ORCH_DRAIN_QUEUE_FLOOR", None)
        with patch.dict(os.environ, env, clear=True):
            s = drain_policy.status()
            self.assertEqual(s["floor"], 800)

    def test_status_floor_custom(self):
        with patch.dict(os.environ, {"ORCH_DRAIN_QUEUE_FLOOR": "42"}, clear=False):
            s = drain_policy.status()
            self.assertEqual(s["floor"], 42)

    def test_floor_negative_clamped(self):
        with patch.dict(os.environ, {"ORCH_DRAIN_QUEUE_FLOOR": "-10"}, clear=False):
            self.assertEqual(drain_policy._floor(), 0)

    def test_floor_garbage_uses_default(self):
        with patch.dict(os.environ, {"ORCH_DRAIN_QUEUE_FLOOR": "xyz"}, clear=False):
            self.assertEqual(drain_policy._floor(), 800)

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
            self.assertFalse(drain_policy.should_skip("spec", queue_depth=9))
            self.assertTrue(drain_policy.should_skip("spec", queue_depth=10))

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
