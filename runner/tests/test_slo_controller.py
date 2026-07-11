"""Tests for slo_controller — especially the UNKNOWN fail-safe (T5 hardening)."""
import unittest
from unittest.mock import patch, MagicMock

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestCheckMergeRate(unittest.TestCase):
    @patch("slo_controller.db")
    def test_green_when_above_threshold(self, mock_db):
        mock_db.select.return_value = [
            {"tests_passed": True, "integrated": True} for _ in range(10)
        ]
        import slo_controller
        result = slo_controller._check_merge_rate()
        self.assertTrue(result["ok"])
        self.assertGreaterEqual(result["value"], 0.9)

    @patch("slo_controller.db")
    def test_red_when_below_threshold(self, mock_db):
        outcomes = [{"tests_passed": True, "integrated": True} for _ in range(3)]
        outcomes += [{"tests_passed": True, "integrated": False} for _ in range(7)]
        mock_db.select.return_value = outcomes
        import slo_controller
        result = slo_controller._check_merge_rate()
        # 3/10 = 0.3, below 0.9 and completed >= 5
        self.assertFalse(result["ok"])

    @patch("slo_controller.db")
    def test_unknown_on_db_failure(self, mock_db):
        mock_db.select.side_effect = ConnectionError("DB down")
        import slo_controller
        result = slo_controller._check_merge_rate()
        self.assertIsNone(result["ok"])
        self.assertEqual(result.get("state"), "UNKNOWN")
        self.assertIn("DB down", result.get("reason", ""))


class TestCheckMissingBranches(unittest.TestCase):
    @patch("slo_controller.db")
    def test_unknown_on_db_failure(self, mock_db):
        mock_db.select.side_effect = RuntimeError("timeout")
        import slo_controller
        result = slo_controller._check_missing_branches()
        self.assertIsNone(result["ok"])
        self.assertEqual(result.get("state"), "UNKNOWN")


class TestCheckRecoveryBacklog(unittest.TestCase):
    @patch("slo_controller.db")
    def test_unknown_on_db_failure(self, mock_db):
        mock_db.select.side_effect = RuntimeError("timeout")
        import slo_controller
        result = slo_controller._check_recovery_backlog()
        self.assertIsNone(result["ok"])
        self.assertEqual(result.get("state"), "UNKNOWN")


class TestCheckFleetUtilization(unittest.TestCase):
    @patch("slo_controller.db")
    def test_unknown_on_db_failure(self, mock_db):
        mock_db.select.side_effect = RuntimeError("timeout")
        import slo_controller
        result = slo_controller._check_fleet_utilization()
        self.assertIsNone(result["ok"])
        self.assertEqual(result.get("state"), "UNKNOWN")


class TestRunSkipsUnknown(unittest.TestCase):
    """UNKNOWN SLOs must NOT trigger remediation actions."""

    @patch("slo_controller.db")
    def test_unknown_slos_no_remediation(self, mock_db):
        # Make all DB calls fail
        mock_db.select.side_effect = ConnectionError("DB down")
        mock_db.insert.return_value = None
        import slo_controller
        result = slo_controller.run()
        # No actions should be taken when all SLOs are UNKNOWN
        self.assertEqual(result["actions"], 0)
        # Nothing passes
        self.assertEqual(result["passing"], 0)


if __name__ == "__main__":
    unittest.main()
