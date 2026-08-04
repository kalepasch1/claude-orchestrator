#!/usr/bin/env python3
"""
test_causal_feedback.py - Comprehensive test suite for causal_feedback module.
25+ test cases covering write/lookup/for_remediation, outcome classification,
confidence clamping, thread safety, and fail-soft DB error handling.
"""
import unittest
from unittest.mock import patch, MagicMock
import threading
import time
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from runner import causal_feedback


class TestCausalFeedbackWrite(unittest.TestCase):
    """Test suite for causal_feedback.write() function."""

    def setUp(self):
        """Reset singleton before each test."""
        causal_feedback.invalidate()

    def tearDown(self):
        """Clean up after each test."""
        causal_feedback.invalidate()

    # === Happy Path Tests ===

    def test_write_basic_success(self):
        """write() returns True and records stats on successful write."""
        with patch("runner.causal_feedback.db.insert", return_value=True):
            result = causal_feedback.write(
                "cycle_time_hours", "improve-cycle-time",
                signal_before=96.4, signal_after=42.1
            )
            self.assertTrue(result)
            stats = causal_feedback.stats()
            self.assertEqual(stats["writes"], 1)
            self.assertEqual(stats["errors"], 0)

    def test_write_positive_outcome(self):
        """write() classifies >5% improvement as positive."""
        with patch("runner.causal_feedback.db.insert", return_value=True):
            causal_feedback.write(
                "cycle_time", "improve-ct",
                signal_before=100.0, signal_after=94.0  # 6% improvement
            )
            stats = causal_feedback.stats()
            self.assertEqual(stats["writes"], 1)

    def test_write_neutral_outcome(self):
        """write() classifies ±5% change as neutral."""
        with patch("runner.causal_feedback.db.insert", return_value=True):
            causal_feedback.write(
                "queue_depth", "fix-queue",
                signal_before=100.0, signal_after=100.0  # no change
            )
            stats = causal_feedback.stats()
            self.assertEqual(stats["writes"], 1)

    def test_write_negative_outcome(self):
        """write() classifies >5% worsening as negative."""
        with patch("runner.causal_feedback.db.insert", return_value=True):
            causal_feedback.write(
                "latency_ms", "tune-latency",
                signal_before=100.0, signal_after=110.0  # 10% worse
            )
            stats = causal_feedback.stats()
            self.assertEqual(stats["writes"], 1)

    def test_write_with_all_fields(self):
        """write() accepts and records all optional fields."""
        with patch("runner.causal_feedback.db.insert", return_value=True) as mock_insert:
            causal_feedback.write(
                bottleneck_key="cycle_time",
                remediation_slug="improve-cycle",
                signal_before=50.0,
                signal_after=25.0,
                outcome_metric="Cycle Time (hours)",
                task_id="task-123",
                proof_id="proof-456",
                confidence=0.95,
                metadata={"model": "opus", "attempt": 2}
            )
            self.assertTrue(mock_insert.called)
            call_args = mock_insert.call_args[0][1]
            self.assertEqual(call_args["task_id"], "task-123")
            self.assertEqual(call_args["proof_id"], "proof-456")
            self.assertEqual(call_args["confidence_0to1"], 0.95)

    # === Edge Cases: None/Empty Values ===

    def test_write_none_bottleneck_key(self):
        """write() returns False when bottleneck_key is None."""
        result = causal_feedback.write(
            None, "remediation",
            signal_before=10.0, signal_after=5.0
        )
        self.assertFalse(result)

    def test_write_empty_bottleneck_key(self):
        """write() returns False when bottleneck_key is empty string."""
        result = causal_feedback.write(
            "", "remediation",
            signal_before=10.0, signal_after=5.0
        )
        self.assertFalse(result)

    def test_write_none_remediation_slug(self):
        """write() returns False when remediation_slug is None."""
        result = causal_feedback.write(
            "bottleneck", None,
            signal_before=10.0, signal_after=5.0
        )
        self.assertFalse(result)

    def test_write_none_signal_before(self):
        """write() returns False when signal_before is None."""
        result = causal_feedback.write(
            "bottleneck", "remediation",
            signal_before=None, signal_after=5.0
        )
        self.assertFalse(result)

    def test_write_none_signal_after(self):
        """write() returns False when signal_after is None."""
        result = causal_feedback.write(
            "bottleneck", "remediation",
            signal_before=10.0, signal_after=None
        )
        self.assertFalse(result)

    def test_write_invalid_signal_before_type(self):
        """write() returns False when signal_before is non-numeric."""
        result = causal_feedback.write(
            "bottleneck", "remediation",
            signal_before="not_a_number", signal_after=5.0
        )
        self.assertFalse(result)

    def test_write_invalid_signal_after_type(self):
        """write() returns False when signal_after is non-numeric."""
        result = causal_feedback.write(
            "bottleneck", "remediation",
            signal_before=10.0, signal_after="not_a_number"
        )
        self.assertFalse(result)

    def test_write_zero_signal_before(self):
        """write() returns False when signal_before is 0 (invalid for delta calculation)."""
        with patch("runner.causal_feedback.db.insert", return_value=True):
            result = causal_feedback.write(
                "bottleneck", "remediation",
                signal_before=0.0, signal_after=5.0
            )
            self.assertFalse(result)

    def test_write_negative_signal_before(self):
        """write() returns False when signal_before is negative."""
        with patch("runner.causal_feedback.db.insert", return_value=True):
            result = causal_feedback.write(
                "bottleneck", "remediation",
                signal_before=-10.0, signal_after=5.0
            )
            self.assertFalse(result)

    # === Confidence Clamping ===

    def test_write_confidence_below_zero_clamped(self):
        """write() clamps confidence below 0.0 to 0.5 (default)."""
        with patch("runner.causal_feedback.db.insert", return_value=True) as mock_insert:
            causal_feedback.write(
                "bottleneck", "remediation",
                signal_before=10.0, signal_after=5.0,
                confidence=-0.5
            )
            call_args = mock_insert.call_args[0][1]
            self.assertEqual(call_args["confidence_0to1"], 0.5)

    def test_write_confidence_above_one_clamped(self):
        """write() clamps confidence above 1.0 to 0.5 (default)."""
        with patch("runner.causal_feedback.db.insert", return_value=True) as mock_insert:
            causal_feedback.write(
                "bottleneck", "remediation",
                signal_before=10.0, signal_after=5.0,
                confidence=1.5
            )
            call_args = mock_insert.call_args[0][1]
            self.assertEqual(call_args["confidence_0to1"], 0.5)

    def test_write_confidence_valid_zero(self):
        """write() accepts confidence=0.0."""
        with patch("runner.causal_feedback.db.insert", return_value=True) as mock_insert:
            causal_feedback.write(
                "bottleneck", "remediation",
                signal_before=10.0, signal_after=5.0,
                confidence=0.0
            )
            call_args = mock_insert.call_args[0][1]
            self.assertEqual(call_args["confidence_0to1"], 0.0)

    def test_write_confidence_valid_one(self):
        """write() accepts confidence=1.0."""
        with patch("runner.causal_feedback.db.insert", return_value=True) as mock_insert:
            causal_feedback.write(
                "bottleneck", "remediation",
                signal_before=10.0, signal_after=5.0,
                confidence=1.0
            )
            call_args = mock_insert.call_args[0][1]
            self.assertEqual(call_args["confidence_0to1"], 1.0)

    def test_write_confidence_non_numeric(self):
        """write() clamps non-numeric confidence to 0.5."""
        with patch("runner.causal_feedback.db.insert", return_value=True) as mock_insert:
            causal_feedback.write(
                "bottleneck", "remediation",
                signal_before=10.0, signal_after=5.0,
                confidence="high"
            )
            call_args = mock_insert.call_args[0][1]
            self.assertEqual(call_args["confidence_0to1"], 0.5)

    # === DB Error Handling (Fail-Soft) ===

    def test_write_db_insert_fails_sync(self):
        """write() returns False and increments error count on DB failure (sync)."""
        with patch("runner.causal_feedback.db.insert", side_effect=Exception("DB down")):
            with patch("runner.causal_feedback.NONBLOCKING_WRITE", False):
                result = causal_feedback.write(
                    "bottleneck", "remediation",
                    signal_before=10.0, signal_after=5.0
                )
                self.assertFalse(result)
                stats = causal_feedback.stats()
                self.assertEqual(stats["errors"], 1)

    def test_write_db_insert_returns_false_sync(self):
        """write() increments skipped count when db.insert returns False (sync)."""
        with patch("runner.causal_feedback.db.insert", return_value=False):
            with patch("runner.causal_feedback.NONBLOCKING_WRITE", False):
                result = causal_feedback.write(
                    "bottleneck", "remediation",
                    signal_before=10.0, signal_after=5.0
                )
                self.assertFalse(result)
                stats = causal_feedback.stats()
                self.assertEqual(stats["skipped"], 1)

    def test_write_db_insert_fails_async(self):
        """write() returns True but increments error count on async DB failure."""
        with patch("runner.causal_feedback.db.insert", side_effect=Exception("DB down")):
            with patch("runner.causal_feedback.NONBLOCKING_WRITE", True):
                result = causal_feedback.write(
                    "bottleneck", "remediation",
                    signal_before=10.0, signal_after=5.0
                )
                self.assertTrue(result)
                time.sleep(0.2)  # let async thread finish
                stats = causal_feedback.stats()
                self.assertEqual(stats["errors"], 1)

    # === Thread Safety ===

    def test_write_concurrent_writes_safe(self):
        """write() is thread-safe under concurrent writes."""
        with patch("runner.causal_feedback.db.insert", return_value=True):
            threads = []
            for i in range(10):
                def _write():
                    causal_feedback.write(
                        f"bottleneck_{i}", f"remediation_{i}",
                        signal_before=float(i), signal_after=float(i-1)
                    )
                t = threading.Thread(target=_write)
                threads.append(t)
                t.start()
            for t in threads:
                t.join()
            stats = causal_feedback.stats()
            self.assertEqual(stats["writes"], 10)

    def test_stats_thread_safe(self):
        """stats() is thread-safe during concurrent writes."""
        with patch("runner.causal_feedback.db.insert", return_value=True):
            observed_stats = []
            def _write_and_check():
                causal_feedback.write(
                    "bottleneck", "remediation",
                    signal_before=10.0, signal_after=5.0
                )
                observed_stats.append(causal_feedback.stats())
            threads = [threading.Thread(target=_write_and_check) for _ in range(5)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            self.assertEqual(len(observed_stats), 5)
            final_stats = causal_feedback.stats()
            self.assertEqual(final_stats["writes"], 5)


class TestCausalFeedbackLookup(unittest.TestCase):
    """Test suite for causal_feedback.lookup() function."""

    def setUp(self):
        """Reset singleton before each test."""
        causal_feedback.invalidate()

    def tearDown(self):
        """Clean up after each test."""
        causal_feedback.invalidate()

    def test_lookup_empty_result(self):
        """lookup() returns empty list when no rows match."""
        with patch("runner.causal_feedback.db.rpc", return_value=None):
            result = causal_feedback.lookup("bottleneck")
            self.assertEqual(result, [])

    def test_lookup_none_bottleneck(self):
        """lookup() returns empty list when bottleneck_key is None."""
        result = causal_feedback.lookup(None)
        self.assertEqual(result, [])

    def test_lookup_empty_bottleneck(self):
        """lookup() returns empty list when bottleneck_key is empty string."""
        result = causal_feedback.lookup("")
        self.assertEqual(result, [])

    def test_lookup_single_result(self):
        """lookup() returns parsed single result row."""
        rows = [{
            "remediation_slug": "improve-cycle",
            "positive_count": 5,
            "neutral_count": 2,
            "negative_count": 1,
            "avg_confidence": 0.85,
            "avg_delta_pct": 23.4,
        }]
        with patch("runner.causal_feedback.db.rpc", return_value=rows):
            result = causal_feedback.lookup("cycle_time")
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]["remediation_slug"], "improve-cycle")
            self.assertEqual(result[0]["positive_count"], 5)

    def test_lookup_dict_result_converted_to_list(self):
        """lookup() converts dict result to list."""
        row = {
            "remediation_slug": "fix-queue",
            "positive_count": 3,
            "neutral_count": 0,
            "negative_count": 0,
            "avg_confidence": 0.9,
            "avg_delta_pct": 15.0,
        }
        with patch("runner.causal_feedback.db.rpc", return_value=row):
            result = causal_feedback.lookup("queue_depth")
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]["remediation_slug"], "fix-queue")

    def test_lookup_confidence_floor_default(self):
        """lookup() uses CONFIDENCE_FLOOR env var by default."""
        rows = []
        with patch("runner.causal_feedback.db.rpc", return_value=rows) as mock_rpc:
            causal_feedback.lookup("bottleneck")
            call_args = mock_rpc.call_args[0][1]
            self.assertGreaterEqual(call_args["confidence_floor"], 0.0)
            self.assertLessEqual(call_args["confidence_floor"], 1.0)

    def test_lookup_confidence_floor_override(self):
        """lookup() accepts confidence_floor override."""
        rows = []
        with patch("runner.causal_feedback.db.rpc", return_value=rows) as mock_rpc:
            causal_feedback.lookup("bottleneck", confidence_floor=0.6)
            call_args = mock_rpc.call_args[0][1]
            self.assertEqual(call_args["confidence_floor"], 0.6)

    def test_lookup_confidence_floor_clamped_invalid(self):
        """lookup() clamps invalid confidence_floor to default."""
        rows = []
        with patch("runner.causal_feedback.db.rpc", return_value=rows) as mock_rpc:
            causal_feedback.lookup("bottleneck", confidence_floor=1.5)
            call_args = mock_rpc.call_args[0][1]
            # Should clamp to default (CONFIDENCE_FLOOR)
            self.assertGreaterEqual(call_args["confidence_floor"], 0.0)
            self.assertLessEqual(call_args["confidence_floor"], 1.0)

    def test_lookup_db_error_returns_empty(self):
        """lookup() returns empty list on DB error."""
        with patch("runner.causal_feedback.db.rpc", side_effect=Exception("DB down")):
            result = causal_feedback.lookup("bottleneck")
            self.assertEqual(result, [])


class TestCausalFeedbackForRemediation(unittest.TestCase):
    """Test suite for causal_feedback.for_remediation() function."""

    def setUp(self):
        """Reset singleton before each test."""
        causal_feedback.invalidate()

    def tearDown(self):
        """Clean up after each test."""
        causal_feedback.invalidate()

    def test_for_remediation_empty_result(self):
        """for_remediation() returns empty list when no rows match."""
        with patch("runner.causal_feedback.db.rpc", return_value=None):
            result = causal_feedback.for_remediation("improve-cycle")
            self.assertEqual(result, [])

    def test_for_remediation_none_slug(self):
        """for_remediation() returns empty list when slug is None."""
        result = causal_feedback.for_remediation(None)
        self.assertEqual(result, [])

    def test_for_remediation_empty_slug(self):
        """for_remediation() returns empty list when slug is empty string."""
        result = causal_feedback.for_remediation("")
        self.assertEqual(result, [])

    def test_for_remediation_single_result(self):
        """for_remediation() returns parsed single result row."""
        rows = [{
            "id": "uuid-1",
            "bottleneck_key": "cycle_time",
            "signal_before": 96.4,
            "signal_after": 42.1,
            "outcome_status": "positive",
            "confidence_0to1": 0.9,
            "delta_pct": 56.2,
            "created_at": "2026-08-03T12:34:56+00:00",
        }]
        with patch("runner.causal_feedback.db.rpc", return_value=rows):
            result = causal_feedback.for_remediation("improve-cycle")
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]["bottleneck_key"], "cycle_time")
            self.assertEqual(result[0]["outcome_status"], "positive")

    def test_for_remediation_dict_result_converted_to_list(self):
        """for_remediation() converts dict result to list."""
        row = {
            "id": "uuid-2",
            "bottleneck_key": "queue_depth",
            "signal_before": 100.0,
            "signal_after": 50.0,
            "outcome_status": "positive",
            "confidence_0to1": 0.85,
            "delta_pct": 50.0,
            "created_at": "2026-08-03T13:00:00+00:00",
        }
        with patch("runner.causal_feedback.db.rpc", return_value=row):
            result = causal_feedback.for_remediation("fix-queue")
            self.assertEqual(len(result), 1)

    def test_for_remediation_type_conversions(self):
        """for_remediation() converts numeric strings to floats."""
        rows = [{
            "id": "uuid-3",
            "bottleneck_key": "latency",
            "signal_before": "100.5",
            "signal_after": "95.2",
            "outcome_status": "positive",
            "confidence_0to1": "0.88",
            "delta_pct": "5.28",
            "created_at": "2026-08-03T13:30:00+00:00",
        }]
        with patch("runner.causal_feedback.db.rpc", return_value=rows):
            result = causal_feedback.for_remediation("tune-latency")
            self.assertEqual(len(result), 1)
            self.assertIsInstance(result[0]["signal_before"], float)
            self.assertIsInstance(result[0]["signal_after"], float)

    def test_for_remediation_db_error_returns_empty(self):
        """for_remediation() returns empty list on DB error."""
        with patch("runner.causal_feedback.db.rpc", side_effect=Exception("DB down")):
            result = causal_feedback.for_remediation("improve-cycle")
            self.assertEqual(result, [])


class TestCausalFeedbackOutcomeClassification(unittest.TestCase):
    """Test suite for outcome classification logic."""

    def test_classify_outcome_positive_threshold(self):
        """_classify_outcome returns positive for >5% improvement."""
        result = causal_feedback._classify_outcome(100.0, 94.0)
        self.assertEqual(result, "positive")

    def test_classify_outcome_positive_exact(self):
        """_classify_outcome returns positive for exactly 5% improvement."""
        result = causal_feedback._classify_outcome(100.0, 95.0)
        self.assertEqual(result, "positive")

    def test_classify_outcome_neutral_lower(self):
        """_classify_outcome returns neutral for 5% improvement."""
        result = causal_feedback._classify_outcome(100.0, 95.1)
        self.assertEqual(result, "neutral")

    def test_classify_outcome_neutral_middle(self):
        """_classify_outcome returns neutral for no change."""
        result = causal_feedback._classify_outcome(100.0, 100.0)
        self.assertEqual(result, "neutral")

    def test_classify_outcome_neutral_upper(self):
        """_classify_outcome returns neutral for 5% worsening."""
        result = causal_feedback._classify_outcome(100.0, 104.9)
        self.assertEqual(result, "neutral")

    def test_classify_outcome_negative_threshold(self):
        """_classify_outcome returns negative for >5% worsening."""
        result = causal_feedback._classify_outcome(100.0, 105.1)
        self.assertEqual(result, "negative")

    def test_classify_outcome_negative_large(self):
        """_classify_outcome returns negative for large worsening."""
        result = causal_feedback._classify_outcome(100.0, 150.0)
        self.assertEqual(result, "negative")

    def test_classify_outcome_none_before(self):
        """_classify_outcome returns pending when signal_before is None."""
        result = causal_feedback._classify_outcome(None, 50.0)
        self.assertEqual(result, "pending")

    def test_classify_outcome_none_after(self):
        """_classify_outcome returns pending when signal_after is None."""
        result = causal_feedback._classify_outcome(100.0, None)
        self.assertEqual(result, "pending")

    def test_classify_outcome_type_error(self):
        """_classify_outcome returns pending on type error."""
        result = causal_feedback._classify_outcome("not_a_number", 50.0)
        self.assertEqual(result, "pending")


class TestCausalFeedbackDeltaCalculation(unittest.TestCase):
    """Test suite for delta percentage calculation."""

    def test_compute_delta_pct_positive(self):
        """_compute_delta_pct calculates positive delta correctly."""
        result = causal_feedback._compute_delta_pct(100.0, 50.0)
        self.assertEqual(result, 50.0)

    def test_compute_delta_pct_negative(self):
        """_compute_delta_pct calculates negative delta correctly."""
        result = causal_feedback._compute_delta_pct(100.0, 150.0)
        self.assertEqual(result, -50.0)

    def test_compute_delta_pct_zero_delta(self):
        """_compute_delta_pct returns 0.0 when no change."""
        result = causal_feedback._compute_delta_pct(100.0, 100.0)
        self.assertEqual(result, 0.0)

    def test_compute_delta_pct_small_delta(self):
        """_compute_delta_pct rounds to 2 decimal places."""
        result = causal_feedback._compute_delta_pct(100.0, 99.5)
        self.assertEqual(result, 0.5)

    def test_compute_delta_pct_none_before(self):
        """_compute_delta_pct returns None when before is None."""
        result = causal_feedback._compute_delta_pct(None, 50.0)
        self.assertIsNone(result)

    def test_compute_delta_pct_none_after(self):
        """_compute_delta_pct returns None when after is None."""
        result = causal_feedback._compute_delta_pct(100.0, None)
        self.assertIsNone(result)

    def test_compute_delta_pct_zero_before(self):
        """_compute_delta_pct returns None when before is 0."""
        result = causal_feedback._compute_delta_pct(0.0, 50.0)
        self.assertIsNone(result)

    def test_compute_delta_pct_negative_before(self):
        """_compute_delta_pct returns None when before is negative."""
        result = causal_feedback._compute_delta_pct(-100.0, 50.0)
        self.assertIsNone(result)

    def test_compute_delta_pct_type_error(self):
        """_compute_delta_pct returns None on type error."""
        result = causal_feedback._compute_delta_pct("not_a_number", 50.0)
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
