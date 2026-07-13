"""Tests for cx_calibration_budget — calibration-aware budget advisor."""
import os
import sys
import json
import unittest
from unittest.mock import patch, MagicMock, call

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Stub db before importing the module
fake_db = MagicMock()
with patch.dict(sys.modules, {"db": fake_db}):
    import cx_calibration_budget


class TestAdjustmentForBrier(unittest.TestCase):
    """Test the _adjustment_for_brier pure function."""

    def test_none_returns_1(self):
        self.assertEqual(cx_calibration_budget._adjustment_for_brier(None), 1.0)

    def test_perfect_calibration(self):
        result = cx_calibration_budget._adjustment_for_brier(0.0)
        self.assertEqual(result, cx_calibration_budget.MIN_BUDGET)

    def test_low_brier_returns_min_budget(self):
        result = cx_calibration_budget._adjustment_for_brier(0.05)
        self.assertEqual(result, cx_calibration_budget.MIN_BUDGET)

    def test_at_low_threshold(self):
        result = cx_calibration_budget._adjustment_for_brier(0.1)
        self.assertEqual(result, cx_calibration_budget.MIN_BUDGET)

    def test_high_brier_returns_max(self):
        result = cx_calibration_budget._adjustment_for_brier(0.5)
        self.assertEqual(result, 1.5)

    def test_at_high_threshold(self):
        result = cx_calibration_budget._adjustment_for_brier(0.4)
        self.assertEqual(result, 1.5)

    def test_midpoint_interpolation(self):
        # Midpoint between 0.1 and 0.4 is 0.25
        result = cx_calibration_budget._adjustment_for_brier(0.25)
        expected = round(0.6 + 0.5 * (1.5 - 0.6), 3)
        self.assertEqual(result, expected)

    def test_monotonic_increase(self):
        prev = cx_calibration_budget._adjustment_for_brier(0.0)
        for b in [0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.5]:
            cur = cx_calibration_budget._adjustment_for_brier(b)
            self.assertGreaterEqual(cur, prev)
            prev = cur


class TestMinBudgetConstant(unittest.TestCase):
    def test_min_budget_value(self):
        self.assertEqual(cx_calibration_budget.MIN_BUDGET, 0.6)

    def test_min_budget_less_than_one(self):
        self.assertLess(cx_calibration_budget.MIN_BUDGET, 1.0)


class TestRun(unittest.TestCase):
    def setUp(self):
        fake_db.reset_mock()

    def test_no_scoreboard_data(self):
        fake_db.select.return_value = []
        result = cx_calibration_budget.run()
        self.assertEqual(result["adjustment"], 1.0)
        self.assertEqual(result["reason"], "no data")

    def test_no_brier_scores(self):
        fake_db.select.return_value = [
            {"committee": "alpha", "calls": 10, "brier": None},
        ]
        result = cx_calibration_budget.run()
        self.assertEqual(result["adjustment"], 1.0)

    def test_too_few_calls_filtered(self):
        fake_db.select.return_value = [
            {"committee": "alpha", "calls": 2, "brier": 0.3},
        ]
        result = cx_calibration_budget.run()
        self.assertEqual(result["adjustment"], 1.0)

    def test_single_committee_good_brier(self):
        fake_db.select.return_value = [
            {"committee": "alpha", "calls": 20, "brier": 0.05},
        ]
        fake_db.upsert.return_value = None
        result = cx_calibration_budget.run()
        self.assertEqual(result["adjustment"], cx_calibration_budget.MIN_BUDGET)
        self.assertEqual(result["weighted_brier"], 0.05)
        self.assertEqual(result["committees_sampled"], 1)

    def test_single_committee_bad_brier(self):
        fake_db.select.return_value = [
            {"committee": "alpha", "calls": 20, "brier": 0.45},
        ]
        fake_db.upsert.return_value = None
        result = cx_calibration_budget.run()
        self.assertEqual(result["adjustment"], 1.5)

    def test_weighted_brier_multi_committee(self):
        fake_db.select.return_value = [
            {"committee": "alpha", "calls": 30, "brier": 0.1},
            {"committee": "beta", "calls": 10, "brier": 0.4},
        ]
        fake_db.upsert.return_value = None
        result = cx_calibration_budget.run()
        # Weighted: (30/40)*0.1 + (10/40)*0.4 = 0.075 + 0.1 = 0.175
        self.assertEqual(result["weighted_brier"], 0.175)
        self.assertEqual(result["committees_sampled"], 2)
        self.assertEqual(result["total_calls"], 40)

    def test_writes_advisory_to_controls(self):
        fake_db.select.return_value = [
            {"committee": "alpha", "calls": 20, "brier": 0.2},
        ]
        fake_db.upsert.return_value = None
        cx_calibration_budget.run()
        fake_db.upsert.assert_called_once()
        args = fake_db.upsert.call_args[0]
        self.assertEqual(args[0], "controls")
        payload = args[1]
        self.assertEqual(payload["key"], "calibration_budget_advisory")
        advisory = json.loads(payload["value"])
        self.assertIn("weighted_brier", advisory)
        self.assertIn("adjustment", advisory)

    def test_upsert_failure_does_not_raise(self):
        fake_db.select.return_value = [
            {"committee": "alpha", "calls": 20, "brier": 0.2},
        ]
        fake_db.upsert.side_effect = Exception("db down")
        # Should not raise
        result = cx_calibration_budget.run()
        self.assertIn("adjustment", result)


if __name__ == "__main__":
    unittest.main()
