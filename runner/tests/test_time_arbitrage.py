"""Tests for time_arbitrage module."""

import unittest
import sys
import os
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from runner.time_arbitrage import (
    get_window_score, best_windows, should_defer, optimal_schedule
)


class TestGetWindowScore(unittest.TestCase):
    def test_returns_float(self):
        self.assertIsInstance(get_window_score(10), float)

    def test_score_in_range(self):
        for h in range(24):
            s = get_window_score(h)
            self.assertGreaterEqual(s, 0.0)
            self.assertLessEqual(s, 1.0)

    def test_offpeak_better_than_peak(self):
        offpeak = get_window_score(8)  # UTC morning
        peak = get_window_score(20)    # UTC evening
        self.assertGreater(offpeak, peak)

    def test_handles_overflow(self):
        self.assertEqual(get_window_score(25), get_window_score(1))


class TestBestWindows(unittest.TestCase):
    def test_returns_list(self):
        result = best_windows()
        self.assertIsInstance(result, list)

    def test_top_n_respected(self):
        self.assertEqual(len(best_windows(5)), 5)

    def test_sorted_descending(self):
        windows = best_windows(5)
        scores = [w["score"] for w in windows]
        self.assertEqual(scores, sorted(scores, reverse=True))


class TestShouldDefer(unittest.TestCase):
    def test_returns_dict(self):
        result = should_defer()
        self.assertIn("execute_now", result)
        self.assertIn("current_score", result)
        self.assertIn("best_hour_utc", result)

    def test_with_specific_time(self):
        morning = datetime(2025, 1, 15, 9, 0, tzinfo=timezone.utc)
        result = should_defer(morning)
        self.assertIsInstance(result["execute_now"], bool)

    def test_high_threshold_may_defer(self):
        evening = datetime(2025, 1, 15, 22, 0, tzinfo=timezone.utc)
        result = should_defer(evening, threshold=0.9)
        # Evening is typically a worse window
        self.assertFalse(result["execute_now"])


class TestOptimalSchedule(unittest.TestCase):
    def test_empty_tasks(self):
        self.assertEqual(optimal_schedule([]), [])

    def test_assigns_all_tasks(self):
        tasks = [{"id": i} for i in range(5)]
        result = optimal_schedule(tasks)
        self.assertEqual(len(result), 5)

    def test_assignment_has_required_keys(self):
        tasks = [{"id": 1}]
        result = optimal_schedule(tasks)
        self.assertIn("task_id", result[0])
        self.assertIn("assigned_hour_utc", result[0])
        self.assertIn("score", result[0])

    def test_restricted_hours(self):
        tasks = [{"id": 1}]
        result = optimal_schedule(tasks, available_hours=[8, 9, 10])
        self.assertIn(result[0]["assigned_hour_utc"], [8, 9, 10])


if __name__ == "__main__":
    unittest.main()
