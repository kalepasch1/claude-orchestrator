#!/usr/bin/env python3
"""Tests for metaopt.py — loop cadence meta-optimization."""
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import metaopt


class TestRecommend(unittest.TestCase):

    @patch("metaopt._throughput_last_window", return_value=0)
    @patch("metaopt._recent_queue_stats", return_value=(0, 0, 0))
    def test_idle_returns_max_poll(self, _qs, _tp):
        rec = metaopt.recommend()
        self.assertEqual(rec["poll_interval_s"], metaopt.MAX_POLL_S)
        self.assertEqual(rec["max_parallel"], metaopt.MIN_PARALLEL)

    @patch("metaopt._throughput_last_window", return_value=0)
    @patch("metaopt._recent_queue_stats", return_value=(25, 3, 10))
    def test_high_pressure_returns_min_poll(self, _qs, _tp):
        rec = metaopt.recommend()
        self.assertEqual(rec["poll_interval_s"], metaopt.MIN_POLL_S)
        self.assertEqual(rec["max_parallel"], metaopt.MAX_PARALLEL)

    @patch("metaopt._throughput_last_window", return_value=0)
    @patch("metaopt._recent_queue_stats", return_value=(5, 1, 5))
    def test_light_pressure(self, _qs, _tp):
        rec = metaopt.recommend()
        self.assertEqual(rec["poll_interval_s"], 60)

    @patch("metaopt._throughput_last_window", return_value=15)
    @patch("metaopt._recent_queue_stats", return_value=(1, 0, 20))
    def test_high_throughput_overrides_idle(self, _qs, _tp):
        rec = metaopt.recommend()
        self.assertLessEqual(rec["poll_interval_s"], 30)

    @patch("metaopt._throughput_last_window", return_value=0)
    @patch("metaopt._recent_queue_stats", return_value=(10, 2, 5))
    def test_moderate_pressure(self, _qs, _tp):
        rec = metaopt.recommend()
        self.assertLessEqual(rec["poll_interval_s"], 30)
        self.assertGreaterEqual(rec["max_parallel"], 4)

    def test_recommend_returns_required_keys(self):
        with patch("metaopt._recent_queue_stats", return_value=(0, 0, 0)), \
             patch("metaopt._throughput_last_window", return_value=0):
            rec = metaopt.recommend()
        for key in ("poll_interval_s", "max_parallel", "reason", "queued", "running"):
            self.assertIn(key, rec)

    @patch("metaopt.recommend", return_value={"poll_interval_s": 30, "max_parallel": 4, "reason": "test", "computed_at": "now"})
    def test_apply_dry_run(self, _rec):
        result = metaopt.apply(dry_run=True)
        self.assertFalse(result["applied"])

    @patch("metaopt.db")
    @patch("metaopt.recommend", return_value={"poll_interval_s": 10, "max_parallel": 8, "reason": "high", "computed_at": "now"})
    def test_apply_writes_config(self, _rec, mock_db):
        mock_db.insert = MagicMock()
        result = metaopt.apply(dry_run=False)
        self.assertTrue(result["applied"])
        self.assertEqual(mock_db.insert.call_count, 3)

    @patch("metaopt.db")
    @patch("metaopt.recommend", return_value={"poll_interval_s": 10, "max_parallel": 8, "reason": "high", "computed_at": "now"})
    def test_apply_handles_db_error(self, _rec, mock_db):
        mock_db.insert = MagicMock(side_effect=Exception("db down"))
        result = metaopt.apply(dry_run=False)
        self.assertFalse(result["applied"])
        self.assertIn("error", result)

    @patch("metaopt.apply", return_value={"applied": True, "poll_interval_s": 10, "max_parallel": 8, "reason": "test"})
    def test_tick_no_crash(self, _apply):
        metaopt.tick()  # should not raise

    @patch("metaopt.apply", side_effect=Exception("boom"))
    def test_tick_failsoft(self, _apply):
        metaopt.tick()  # should not raise


if __name__ == "__main__":
    unittest.main()
