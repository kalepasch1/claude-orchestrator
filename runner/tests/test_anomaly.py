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

    def test_a_single_failure_against_a_clean_baseline_stays_quiet(self):
        """The floor's job: emergence must not mean 'alert on any non-zero value'.

        One failure in a 30-task window is 0.033, below the 0.10 fail_rate floor.
        Without the floor the zero-baseline branch would page on every flake.
        """
        base = [{"tests_passed": True, "rate_limited": False, "usd": 0.01}] * 270
        recent = ([{"tests_passed": False, "rate_limited": False, "usd": 0.01}]
                  + [{"tests_passed": True, "rate_limited": False, "usd": 0.01}] * 29)
        fake_db.select = MagicMock(return_value=recent + base)
        fake_db.insert = MagicMock()
        result = anomaly.check()
        self.assertTrue(result["ok"], result["alerts"])

    def test_rate_limiting_appearing_from_zero_alerts(self):
        """Same emergence hole, a different metric: no baseline rate-limiting at all."""
        base = [{"tests_passed": True, "rate_limited": False, "usd": 0.01}] * 270
        recent = [{"tests_passed": True, "rate_limited": True, "usd": 0.01}] * 30
        fake_db.select = MagicMock(return_value=recent + base)
        fake_db.insert = MagicMock()
        result = anomaly.check()
        self.assertFalse(result["ok"])
        self.assertTrue(any("rate_limit_rate" in a for a in result["alerts"]))

    def test_the_floor_is_env_overridable(self):
        base = [{"tests_passed": True, "rate_limited": False, "usd": 0.01}] * 270
        recent = ([{"tests_passed": False, "rate_limited": False, "usd": 0.01}]
                  + [{"tests_passed": True, "rate_limited": False, "usd": 0.01}] * 29)
        fake_db.select = MagicMock(return_value=recent + base)
        fake_db.insert = MagicMock()
        with patch.dict(os.environ, {"ANOMALY_FLOOR_FAIL_RATE": "0.01"}):
            self.assertFalse(anomaly.check()["ok"])

    def test_a_bad_floor_value_falls_back_to_the_default(self):
        with patch.dict(os.environ, {"ANOMALY_FLOOR_FAIL_RATE": "not a number"}):
            self.assertEqual(anomaly._floor("fail_rate"), 0.10)


if __name__ == "__main__":
    unittest.main()
