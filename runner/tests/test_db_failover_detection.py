#!/usr/bin/env python3
"""Tests for db.py DB failover detection: _reset_db_failure_count, _increment_db_failure_count, is_db_down."""
import os
import sys
import unittest
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import db


class DbFailoverDetectionTest(unittest.TestCase):
    """Test DB failover state tracking for sentinel offline mode."""

    def setUp(self):
        """Reset failure count before each test."""
        db._reset_db_failure_count()

    def tearDown(self):
        """Clean up: reset state after test."""
        db._reset_db_failure_count()

    def test_initial_state_is_db_up(self):
        """DB should start in UP state (failure count = 0)."""
        self.assertFalse(db.is_db_down(), "DB should start in UP state")

    def test_single_failure_not_down(self):
        """One failure should not trigger offline mode."""
        db._increment_db_failure_count()
        self.assertFalse(db.is_db_down(), "Single failure should not trigger DB down")

    def test_failure_increment_returns_count(self):
        """_increment_db_failure_count should return new count."""
        count1 = db._increment_db_failure_count()
        self.assertEqual(count1, 1, "First increment should return 1")
        count2 = db._increment_db_failure_count()
        self.assertEqual(count2, 2, "Second increment should return 2")

    def test_at_threshold_triggers_down(self):
        """Reaching threshold should trigger DB down state."""
        threshold = db.DB_DOWN_THRESHOLD
        for _ in range(threshold - 1):
            db._increment_db_failure_count()
        self.assertFalse(db.is_db_down(), "Should not be down before threshold")
        db._increment_db_failure_count()
        self.assertTrue(db.is_db_down(), "Should be down at/above threshold")

    def test_reset_clears_failure_count(self):
        """Reset should clear the failure counter."""
        db._increment_db_failure_count()
        db._increment_db_failure_count()
        db._increment_db_failure_count()
        self.assertTrue(db.is_db_down(), "Should be down before reset")
        db._reset_db_failure_count()
        self.assertFalse(db.is_db_down(), "Should be up after reset")

    def test_recovery_after_threshold_crossed(self):
        """Reset should recover from down state back to up."""
        for _ in range(db.DB_DOWN_THRESHOLD + 5):
            db._increment_db_failure_count()
        self.assertTrue(db.is_db_down(), "Should be down")
        db._reset_db_failure_count()
        self.assertFalse(db.is_db_down(), "Should be up after reset")

    def test_threshold_configuration(self):
        """DB_DOWN_THRESHOLD should be configurable via env var."""
        self.assertGreater(db.DB_DOWN_THRESHOLD, 0, "Threshold should be positive")
        self.assertEqual(db.DB_DOWN_THRESHOLD, int(os.environ.get("SENTINEL_DB_DOWN_THRESHOLD", "3")),
                         "Threshold should match env var or default to 3")

    def test_thread_safety_concurrent_increments(self):
        """Concurrent increments should be serialized (no lost updates)."""
        results = []
        def increment_n_times(n):
            for _ in range(n):
                result = db._increment_db_failure_count()
                results.append(result)

        threads = [threading.Thread(target=increment_n_times, args=(3,)) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(results), 12, "Should have 12 results from 4 threads × 3 increments")
        expected = set(range(1, 13))
        self.assertEqual(set(results), expected, "All counts 1-12 should appear (no duplicates/loss)")

    def test_thread_safety_concurrent_reads(self):
        """Concurrent is_db_down() calls should be safe."""
        db._db_failure_count = db.DB_DOWN_THRESHOLD
        results = []
        def read_status():
            results.append(db.is_db_down())

        threads = [threading.Thread(target=read_status) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(results), 10, "Should have 10 results")
        self.assertTrue(all(results), "All reads should see consistent TRUE (at threshold)")

    def test_thread_safety_concurrent_read_write(self):
        """Concurrent increments and resets should be safe."""
        results = []
        def increment_once():
            count = db._increment_db_failure_count()
            results.append(("inc", count))

        def reset_once():
            db._reset_db_failure_count()
            results.append(("reset", 0))

        threads = []
        for i in range(5):
            if i % 2 == 0:
                threads.append(threading.Thread(target=increment_once))
            else:
                threads.append(threading.Thread(target=reset_once))
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(results), 5, "Should have 5 results")
        final_state = db.is_db_down()
        self.assertIsInstance(final_state, bool, "is_db_down should return bool")


class DbFailoverCustomThresholdTest(unittest.TestCase):
    """Test DB failover with custom threshold."""

    def setUp(self):
        db._reset_db_failure_count()
        self._saved_threshold = db.DB_DOWN_THRESHOLD
        self._saved_env = os.environ.get("SENTINEL_DB_DOWN_THRESHOLD")

    def tearDown(self):
        db._reset_db_failure_count()
        db.DB_DOWN_THRESHOLD = self._saved_threshold
        if self._saved_env:
            os.environ["SENTINEL_DB_DOWN_THRESHOLD"] = self._saved_env
        else:
            os.environ.pop("SENTINEL_DB_DOWN_THRESHOLD", None)

    def test_custom_threshold_value(self):
        """DB_DOWN_THRESHOLD should use value from env var if set."""
        self.assertIsInstance(db.DB_DOWN_THRESHOLD, int, "Threshold should be int")
        self.assertGreater(db.DB_DOWN_THRESHOLD, 0, "Threshold should be positive")
        # Verify default of 3 if not in env
        if "SENTINEL_DB_DOWN_THRESHOLD" not in os.environ:
            self.assertEqual(db.DB_DOWN_THRESHOLD, 3, "Default threshold should be 3")


if __name__ == "__main__":
    unittest.main()
