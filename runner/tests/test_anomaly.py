"""Tests for anomaly.py — self-loop vitals monitoring."""
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

fake_db = MagicMock()
with patch.dict(sys.modules, {"db": fake_db}):
    import anomaly


class TestRate(unittest.TestCase):
    def test_empty_list_returns_zero(self):
        self.assertEqual(anomaly._rate([], lambda r: True), 0.0)

    def test_all_match(self):
        rows = [{"x": 1}, {"x": 2}]
        self.assertAlmostEqual(anomaly._rate(rows, lambda r: True), 1.0)

    def test_half_match(self):
        rows = [{"v": True}, {"v": False}]
        self.assertAlmostEqual(anomaly._rate(rows, lambda r: r["v"]), 0.5)


class TestCheck(unittest.TestCase):
    def test_not_enough_data(self):
        fake_db.select = MagicMock(return_value=[{"tests_passed": True}] * 10)
        result = anomaly.check()
        self.assertTrue(result["ok"])
        self.assertIn("not enough data", result.get("note", ""))

    def test_db_error_returns_ok(self):
        fake_db.select = MagicMock(side_effect=Exception("conn refused"))
        result = anomaly.check()
        self.assertTrue(result["ok"])
        self.assertIn("unavailable", result.get("note", ""))

    def test_no_alerts_when_stable(self):
        base = [{"tests_passed": True, "rate_limited": False, "usd": 0.01}] * 270
        recent = [{"tests_passed": True, "rate_limited": False, "usd": 0.01}] * 30
        fake_db.select = MagicMock(return_value=recent + base)
        fake_db.insert = MagicMock()
        result = anomaly.check()
        self.assertTrue(result["ok"])
        self.assertEqual(result["alerts"], [])

    def test_spike_triggers_alert(self):
        base = [{"tests_passed": True, "rate_limited": False, "usd": 0.01}] * 270
        recent = [{"tests_passed": False, "rate_limited": False, "usd": 0.01}] * 30
        fake_db.select = MagicMock(return_value=recent + base)
        fake_db.insert = MagicMock()
        result = anomaly.check()
        self.assertFalse(result["ok"])
        self.assertTrue(len(result["alerts"]) > 0)
        self.assertTrue(any("fail_rate" in a for a in result["alerts"]))


if __name__ == "__main__":
    unittest.main()
