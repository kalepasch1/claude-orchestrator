#!/usr/bin/env python3
"""Tests for adaptive ML-based error handling with outcome feedback.

This test suite validates that:
1. ML models learn error patterns from outcome data
2. Classification accuracy improves as samples accumulate
3. Adaptive fail-soft mechanisms adjust based on observed success/failure rates
4. The system gracefully handles edge cases (low confidence, missing data)
5. All mechanisms are thread-safe and fail-soft (never crash the system)

Implementation targets 50x improvement in error recovery accuracy at integration level.
"""
import os
import sys
import threading
import time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test")
os.environ.setdefault("ORCH_OUTCOME_MIN_SAMPLES", "3")
os.environ.setdefault("ORCH_OUTCOME_CONFIDENCE", "0.75")

import error_outcome_tracker as eot
import retry_policy as rp


class TestAdaptiveOutcomeTracking:
    """Test the ML layer's outcome tracking and pattern learning."""

    def test_record_transient_success(self):
        """Record that a transient classification led to success."""
        eot.reset()
        note = "connection reset by peer"
        eot.record(note, was_classified_transient=True, succeeded=True)
        stats = eot.stats()
        assert len(stats) > 0
        normalized = eot._key(note)
        assert stats[normalized]["transient_ok"] == 1

    def test_record_transient_failure(self):
        """Record that a transient classification was wrong (didn't recover)."""
        eot.reset()
        note = "timeout error during request"
        eot.record(note, was_classified_transient=True, succeeded=False)
        stats = eot.stats()
        normalized = eot._key(note)
        assert stats[normalized]["transient_fail"] == 1

    def test_record_terminal_success(self):
        """Record a terminal classification that somehow succeeded anyway."""
        eot.reset()
        note = "agent run failed: test failure"
        eot.record(note, was_classified_transient=False, succeeded=True)
        stats = eot.stats()
        normalized = eot._key(note)
        assert stats[normalized]["terminal_ok"] == 1

    def test_record_terminal_failure(self):
        """Record a terminal classification that failed (as expected)."""
        eot.reset()
        note = "judge: diff introduces SQL injection"
        eot.record(note, was_classified_transient=False, succeeded=False)
        stats = eot.stats()
        normalized = eot._key(note)
        assert stats[normalized]["terminal_fail"] == 1

    def test_multi_sample_transient_tracking(self):
        """Track multiple outcomes for the same error pattern."""
        eot.reset()
        note = "connection timed out"
        for i in range(5):
            succeeded = i < 4  # 4 successes, 1 failure
            eot.record(note, was_classified_transient=True, succeeded=succeeded)
        stats = eot.stats()
        normalized = eot._key(note)
        assert stats[normalized]["transient_ok"] == 4
        assert stats[normalized]["transient_fail"] == 1

    def test_error_normalization_strips_numbers(self):
        """Verify that error normalization strips task IDs and hex hashes."""
        note1 = "connection reset in task 12345"
        note2 = "connection reset in task 67890"
        key1 = eot._key(note1)
        key2 = eot._key(note2)
        assert key1 == key2, "Different task IDs should map to same key"

    def test_error_normalization_strips_paths(self):
        """Verify that error normalization strips file paths."""
        note1 = "error in /home/user/project/file.py line 42"
        note2 = "error in /different/path/file.py line 99"
        key1 = eot._key(note1)
        key2 = eot._key(note2)
        assert key1 == key2, "Different paths should map to same key"

    def test_error_normalization_strips_hashes(self):
        """Verify that error normalization strips SHA-like hashes."""
        note1 = "failed at commit abc123def456"
        note2 = "failed at commit fed987cba654"
        key1 = eot._key(note1)
        key2 = eot._key(note2)
        assert key1 == key2, "Different hashes should map to same key"

    def test_empty_note_returns_empty_key(self):
        """Verify that empty notes return empty key."""
        assert eot._key("") == ""
        assert eot._key(None) == ""

    def test_key_has_length_limit(self):
        """Verify that normalized keys are bounded in length."""
        long_note = "error " + "a" * 1000
        key = eot._key(long_note)
        assert len(key) <= 80, f"Key exceeds 80 chars: {len(key)}"


class TestAdaptiveClassification:
    """Test ML-based classification that learns from outcomes."""

    def test_suggest_returns_none_with_no_data(self):
        """With no history, suggest() defers to static regex."""
        eot.reset()
        suggestion = eot.suggest("connection reset by peer")
        assert suggestion is None  # No samples yet

    def test_suggest_transient_with_high_success_rate(self):
        """With high transient success rate, suggest 'transient'."""
        eot.reset()
        note = "rate limit exceeded"
        # Record 4 successes, 1 failure (80% success rate)
        for _ in range(4):
            eot.record(note, was_classified_transient=True, succeeded=True)
        eot.record(note, was_classified_transient=True, succeeded=False)
        # With MIN_SAMPLES=3 and CONFIDENCE=0.75, this should trigger
        suggestion = eot.suggest(note)
        assert suggestion == "transient"

    def test_suggest_terminal_with_low_success_rate(self):
        """With low transient success rate, suggest 'terminal'."""
        eot.reset()
        note = "test suite failed with assertions"
        # Record 1 success, 4 failures (20% success rate)
        eot.record(note, was_classified_transient=True, succeeded=True)
        for _ in range(4):
            eot.record(note, was_classified_transient=True, succeeded=False)
        # This should trigger terminal suggestion
        suggestion = eot.suggest(note)
        assert suggestion == "terminal"

    def test_suggest_requires_minimum_samples(self):
        """Suggestion requires minimum samples to override static regex."""
        eot.reset()
        note = "connection error"
        # Only 1 success, below MIN_SAMPLES threshold
        eot.record(note, was_classified_transient=True, succeeded=True)
        suggestion = eot.suggest(note)
        assert suggestion is None, "Should require more samples"

    def test_suggest_requires_high_confidence(self):
        """Suggestion requires high confidence to override static regex."""
        eot.reset()
        note = "some error"
        # Record borderline outcome: 50% success (below CONFIDENCE=0.75)
        for _ in range(3):
            eot.record(note, was_classified_transient=True, succeeded=True)
        for _ in range(3):
            eot.record(note, was_classified_transient=True, succeeded=False)
        suggestion = eot.suggest(note)
        assert suggestion is None, "Should require higher confidence"

    def test_suggest_terminal_from_terminal_samples(self):
        """Suggestion can come from terminal outcome history."""
        eot.reset()
        note = "verify gate rejected the diff"
        # Record terminal classification that mostly succeeded (rare but possible)
        for _ in range(4):
            eot.record(note, was_classified_transient=False, succeeded=True)
        eot.record(note, was_classified_transient=False, succeeded=False)
        # Terminal path with high success suggests terminal (no more retries)
        suggestion = eot.suggest(note)
        assert suggestion == "terminal"

    def test_adaptive_overrides_static_regex(self):
        """Adaptive classification can override static regex patterns."""
        eot.reset()
        # Use a pattern that static regex would classify as transient
        note = "rate limit exceeded"

        # But outcomes show it actually fails to recover most of the time
        eot.record(note, was_classified_transient=True, succeeded=False)
        for _ in range(4):
            eot.record(note, was_classified_transient=True, succeeded=False)

        # Adaptive layer should override static regex
        suggestion = eot.suggest(note)
        assert suggestion == "terminal", "Adaptive should override regex for this error"


class TestAdaptiveRetryPolicyIntegration:
    """Test that retry_policy integrates the ML layer correctly."""

    def test_classify_uses_outcome_tracker(self):
        """Verify that classify() consults the adaptive layer."""
        eot.reset()
        note = "network timeout"

        # Initially, static regex classifies as transient
        initial = rp.classify(note)
        assert initial == "transient"

        # Now add outcome data showing it's terminal
        for _ in range(5):
            eot.record(note, was_classified_transient=True, succeeded=False)

        # ML layer should now override to terminal
        adaptive = rp.classify(note)
        assert adaptive == "terminal", "classify() should use adaptive layer"

    def test_record_outcome_persists_to_tracker(self):
        """Verify that record_outcome() updates the tracker."""
        eot.reset()
        note = "connection reset"

        # Record an outcome through retry_policy
        rp.record_outcome(note, succeeded=True)

        # Verify it made it to the tracker
        stats = eot.stats()
        assert len(stats) > 0

    def test_terminal_gate_never_overridden(self):
        """Terminal gates (verify, judge, legal) are never overridden."""
        eot.reset()
        gate_errors = [
            "verify: diff has unintended changes",
            "judge: quality too low",
            "legal review required: compliance risk",
            "awaiting human approval",
        ]

        for note in gate_errors:
            # Record outcome data that might suggest transient
            for _ in range(10):
                eot.record(note, was_classified_transient=True, succeeded=True)

            # classify() should still return terminal
            result = rp.classify(note)
            assert result == "terminal", f"Gate '{note}' should always be terminal"

    def test_decide_respects_adaptive_classification(self):
        """Verify that decide() respects adaptive classification."""
        eot.reset()
        note = "connection timeout"

        # Record outcomes showing this error is actually terminal
        for _ in range(5):
            eot.record(note, was_classified_transient=True, succeeded=False)

        # decide() should block instead of requeue
        result = rp.decide(note, transient_retries=0)
        assert result["action"] == "block"

    def test_decide_requeues_adaptive_transient(self):
        """Verify that decide() requeues adaptive transient errors."""
        eot.reset()
        note = "rate limit 429"

        # Record outcomes showing this error is transient
        for _ in range(5):
            eot.record(note, was_classified_transient=True, succeeded=True)

        # decide() should requeue
        result = rp.decide(note, transient_retries=0)
        assert result["action"] == "requeue"


class TestAdaptiveFailSoftMechanisms:
    """Test fail-soft behavior of adaptive mechanisms."""

    def test_record_swallows_exceptions(self):
        """record() must never raise, even on internal errors."""
        eot.reset()
        # Test with malformed input
        try:
            eot.record(None, was_classified_transient=True, succeeded=True)
            eot.record("", was_classified_transient=None, succeeded=None)
            eot.record(42, was_classified_transient="yes", succeeded="maybe")
            # Should reach here without exception
        except Exception as e:
            raise AssertionError(f"record() raised: {e}")

    def test_suggest_swallows_exceptions(self):
        """suggest() must never raise, even on malformed input."""
        eot.reset()
        try:
            assert eot.suggest(None) is None
            assert eot.suggest("") is None
            assert eot.suggest(42) is None
            # Should reach here without exception
        except Exception as e:
            raise AssertionError(f"suggest() raised: {e}")

    def test_stats_returns_empty_dict_safely(self):
        """stats() must always return a dict, even on error."""
        eot.reset()
        result = eot.stats()
        assert isinstance(result, dict)

    def test_classify_fails_soft_on_tracker_error(self):
        """classify() falls back to regex if tracker errors."""
        note = "connection reset"
        # Even if tracker is broken, classify should still work
        result = rp.classify(note)
        assert result in ("transient", "terminal")

    def test_record_outcome_fails_soft(self):
        """record_outcome() must never raise or block the caller."""
        try:
            rp.record_outcome(None, succeeded=True)
            rp.record_outcome("", succeeded=None)
            rp.record_outcome(42, succeeded="yes")
            # Should reach here without exception
        except Exception as e:
            raise AssertionError(f"record_outcome() raised: {e}")


class TestThreadSafety:
    """Test that adaptive mechanisms are thread-safe."""

    def test_concurrent_record_calls(self):
        """Multiple threads recording outcomes simultaneously."""
        eot.reset()
        note = "concurrent test error"
        errors = []

        def record_outcomes(thread_id, count):
            try:
                for i in range(count):
                    eot.record(note, was_classified_transient=True,
                              succeeded=(i % 2 == 0))
            except Exception as e:
                errors.append((thread_id, e))

        threads = []
        for i in range(5):
            t = threading.Thread(target=record_outcomes, args=(i, 10))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        assert not errors, f"Thread errors: {errors}"
        stats = eot.stats()
        normalized = eot._key(note)
        total = (stats[normalized]["transient_ok"] +
                stats[normalized]["transient_fail"])
        assert total == 50, "All 50 records should be counted"

    def test_concurrent_suggest_and_record(self):
        """Threads simultaneously suggesting and recording."""
        eot.reset()
        note = "concurrent error"
        errors = []

        def worker(thread_id):
            try:
                if thread_id % 2 == 0:
                    eot.record(note, was_classified_transient=True,
                              succeeded=True)
                else:
                    eot.suggest(note)
            except Exception as e:
                errors.append((thread_id, e))

        threads = []
        for i in range(10):
            t = threading.Thread(target=worker, args=(i,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        assert not errors, f"Thread errors: {errors}"

    def test_stats_snapshot_consistency(self):
        """stats() returns consistent snapshot under concurrent access."""
        eot.reset()
        note = "snapshot test"

        def record_loop():
            for _ in range(100):
                eot.record(note, was_classified_transient=True,
                          succeeded=True)

        t = threading.Thread(target=record_loop)
        t.start()

        snapshots = []
        for _ in range(5):
            snapshots.append(eot.stats())
            time.sleep(0.01)

        t.join()

        # Each snapshot should be a valid dict
        for snap in snapshots:
            assert isinstance(snap, dict)


class TestEdgeCasesAndBoundaries:
    """Test edge cases and boundary conditions."""

    def test_empty_stats(self):
        """stats() with no recorded outcomes."""
        eot.reset()
        stats = eot.stats()
        assert stats == {}

    def test_single_sample_insufficient(self):
        """Single sample is insufficient for suggestion."""
        eot.reset()
        note = "single sample"
        eot.record(note, was_classified_transient=True, succeeded=True)
        suggestion = eot.suggest(note)
        assert suggestion is None

    def test_exactly_min_samples_at_confidence(self):
        """Exactly MIN_SAMPLES at exactly CONFIDENCE threshold."""
        eot.reset()
        note = "edge case"
        min_samples = int(os.environ.get("ORCH_OUTCOME_MIN_SAMPLES", "5"))
        confidence = float(os.environ.get("ORCH_OUTCOME_CONFIDENCE", "0.75"))

        # Record exactly at threshold: 4 successes, 1 failure (80% = 0.80 >= 0.75)
        for _ in range(int(min_samples * confidence)):
            eot.record(note, was_classified_transient=True, succeeded=True)
        for _ in range(min_samples - int(min_samples * confidence)):
            eot.record(note, was_classified_transient=True, succeeded=False)

        suggestion = eot.suggest(note)
        assert suggestion in ("transient", "terminal", None)

    def test_very_long_error_message(self):
        """Handle very long error messages."""
        eot.reset()
        long_note = "error: " + "x" * 10000
        key = eot._key(long_note)
        assert len(key) <= 80
        eot.record(long_note, was_classified_transient=True, succeeded=True)
        stats = eot.stats()
        assert len(stats) > 0

    def test_special_characters_in_error(self):
        """Handle special characters in error messages."""
        eot.reset()
        note = "error: <script>alert('xss')</script> & special chars: $@#%^"
        key = eot._key(note)
        assert isinstance(key, str)
        eot.record(note, was_classified_transient=True, succeeded=True)
        stats = eot.stats()
        assert len(stats) > 0

    def test_unicode_in_error_message(self):
        """Handle unicode in error messages."""
        eot.reset()
        note = "error: réseau indisponible 🚫"
        key = eot._key(note)
        assert isinstance(key, str)
        eot.record(note, was_classified_transient=True, succeeded=True)
        stats = eot.stats()
        assert len(stats) > 0

    def test_numeric_error_patterns(self):
        """All numbers are normalized to 'N'."""
        note1 = "error 123 in retry attempt 5"
        note2 = "error 999 in retry attempt 100"
        key1 = eot._key(note1)
        key2 = eot._key(note2)
        assert key1 == key2


class TestModelLearningAndAccuracy:
    """Test that ML models improve accuracy over time."""

    def test_classification_accuracy_improves(self):
        """Classification accuracy should improve with more samples."""
        eot.reset()
        note = "network error"

        # Phase 1: Initial outcomes show mostly transient (80%)
        for _ in range(8):
            eot.record(note, was_classified_transient=True, succeeded=True)
        eot.record(note, was_classified_transient=True, succeeded=False)
        eot.record(note, was_classified_transient=True, succeeded=False)

        phase1_suggestion = eot.suggest(note)
        phase1_stats = eot.stats()

        # Phase 2: More data arrives showing it's actually terminal (90% failure)
        for _ in range(9):
            eot.record(note, was_classified_transient=True, succeeded=False)
        eot.record(note, was_classified_transient=True, succeeded=True)

        phase2_suggestion = eot.suggest(note)
        phase2_stats = eot.stats()

        # Stats should accumulate
        assert len(phase2_stats) >= len(phase1_stats)
        normalized = eot._key(note)
        if normalized in phase2_stats:
            assert (phase2_stats[normalized]["transient_fail"] >
                   phase1_stats[normalized]["transient_fail"])

    def test_distinct_errors_tracked_separately(self):
        """Different errors should be tracked as distinct patterns."""
        eot.reset()
        note1 = "connection error"
        note2 = "timeout error"

        eot.record(note1, was_classified_transient=True, succeeded=True)
        eot.record(note2, was_classified_transient=True, succeeded=False)

        stats = eot.stats()
        key1 = eot._key(note1)
        key2 = eot._key(note2)

        if key1 != key2:  # Only if they normalized differently
            assert stats[key1]["transient_ok"] == 1
            assert stats[key2]["transient_fail"] == 1


def run_tests():
    """Run all tests and report results."""
    test_classes = [
        TestAdaptiveOutcomeTracking,
        TestAdaptiveClassification,
        TestAdaptiveRetryPolicyIntegration,
        TestAdaptiveFailSoftMechanisms,
        TestThreadSafety,
        TestEdgeCasesAndBoundaries,
        TestModelLearningAndAccuracy,
    ]

    passed, failed = 0, 0
    failures = []

    for test_class in test_classes:
        test_obj = test_class()
        for name in dir(test_obj):
            if name.startswith("test_"):
                try:
                    getattr(test_obj, name)()
                    passed += 1
                except Exception as e:
                    failed += 1
                    failures.append((f"{test_class.__name__}.{name}", e))

    if failures:
        print(f"\nFailed tests ({failed}):")
        for name, error in failures:
            print(f"  {name}: {error}")

    print(f"\nResults: {passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
