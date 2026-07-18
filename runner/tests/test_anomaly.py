#!/usr/bin/env python3
"""Tests for runner/anomaly.py — _rate helper and check() logic."""
import os, sys, unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import anomaly


class TestRate(unittest.TestCase):
    def test_empty_rows_returns_zero(self):
        self.assertEqual(anomaly._rate([], lambda r: True), 0.0)

    def test_all_match(self):
        rows = [{"x": 1}, {"x": 2}, {"x": 3}]
        self.assertAlmostEqual(anomaly._rate(rows, lambda r: True), 1.0)

    def test_none_match(self):
        rows = [{"x": 1}, {"x": 2}]
        self.assertAlmostEqual(anomaly._rate(rows, lambda r: False), 0.0)

    def test_partial_match(self):
        rows = [{"v": True}, {"v": False}, {"v": True}, {"v": False}]
        self.assertAlmostEqual(anomaly._rate(rows, lambda r: r["v"]), 0.5)


class TestCheck(unittest.TestCase):
    def test_returns_ok_when_not_enough_data(self):
        mock_db = MagicMock()
        mock_db.select.return_value = [{"tests_passed": True}] * 10
        with patch.object(anomaly, "db", mock_db):
            result = anomaly.check()
            self.assertTrue(result["ok"])
            self.assertIn("not enough data", result.get("note", ""))

    def test_returns_ok_on_db_error(self):
        mock_db = MagicMock()
        mock_db.select.side_effect = RuntimeError("connection refused")
        with patch.object(anomaly, "db", mock_db):
            result = anomaly.check()
            self.assertTrue(result["ok"])
            self.assertIn("unavailable", result.get("note", ""))

    def test_detects_spike_in_fail_rate(self):
        """When recent fail rate is much higher than baseline, alerts fire."""
        recent = [{"tests_passed": False, "rate_limited": False, "usd": "0.01"}] * 30
        # Baseline has ~10% fail rate; recent has 100% — a clear spike above SPIKE=1.75x
        baseline_pass = [{"tests_passed": True, "rate_limited": False, "usd": "0.01"}] * 243
        baseline_fail = [{"tests_passed": False, "rate_limited": False, "usd": "0.01"}] * 27
        baseline = baseline_pass + baseline_fail
        all_rows = recent + baseline
        mock_db = MagicMock()
        mock_db.select.return_value = all_rows
        with patch.object(anomaly, "db", mock_db):
            result = anomaly.check()
            self.assertFalse(result["ok"])
            self.assertTrue(len(result["alerts"]) > 0)
            self.assertTrue(any("fail_rate" in a for a in result["alerts"]))

    def test_no_alert_when_rates_stable(self):
        """When recent and baseline have similar rates, no alerts."""
        row = {"tests_passed": True, "rate_limited": False, "usd": "0.02"}
        all_rows = [row] * 300
        mock_db = MagicMock()
        mock_db.select.return_value = all_rows
        with patch.object(anomaly, "db", mock_db):
            result = anomaly.check()
            self.assertTrue(result["ok"])
            self.assertEqual(len(result.get("alerts", [])), 0)


if __name__ == "__main__":
    unittest.main()
