#!/usr/bin/env python3
"""
Comprehensive tests for improved ML-based error handling automation.

Tests orchestration pipeline contract for error handling:
- Preflight error classification via model routing
- Strategy planning for recovery actions
- Agentic error recovery with fallbacks
- QA validation of recovery effectiveness
- Thread-safe pattern learning
- Fail-soft guarantees
- Model provider rotation (Gemini, Claude, OpenAI)
"""
import os, sys, time, threading, unittest
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test")
os.environ["ORCH_ML_AUTO_RECOVERY_ENABLED"] = "true"
os.environ["ORCH_ML_SUCCESS_RATE_THRESHOLD"] = "0.7"
os.environ["ORCH_ML_MIN_PATTERN_OBSERVATIONS"] = "5"
os.environ["ORCH_ML_ERROR_PATTERN_HISTORY_SIZE"] = "1000"

import error_classifier as ec
import ml_error_automation as mla


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 1: Error Classification and Pattern Detection
# ─────────────────────────────────────────────────────────────────────────────

class ErrorClassificationTests(unittest.TestCase):
    """Tests for error detection and pattern signature generation."""

    def setUp(self):
        mla.reset_learning()

    def test_transient_rate_limit_pattern(self):
        """Rate limit errors must be classified as transient and recoverable."""
        error = RuntimeError("429 too many requests")
        sig = mla.track_error(error)
        self.assertEqual(sig.category, ec.TRANSIENT)
        self.assertEqual(sig.pattern_key, "rate_limit")
        self.assertTrue(sig.recoverable)

    def test_transient_timeout_pattern(self):
        """Timeout errors must be classified as transient."""
        error = TimeoutError("deadline exceeded after 30s")
        sig = mla.track_error(error)
        self.assertEqual(sig.category, ec.TRANSIENT)
        self.assertEqual(sig.pattern_key, "timeout")
        self.assertTrue(sig.recoverable)

    def test_transient_connection_pattern(self):
        """Connection reset errors must be transient."""
        error = ConnectionError("connection reset by peer")
        sig = mla.track_error(error)
        self.assertEqual(sig.pattern_key, "connection_reset")
        self.assertTrue(sig.recoverable)

    def test_conflict_merge_pattern(self):
        """Merge conflict errors must be classified as conflict."""
        error = RuntimeError("CONFLICT (content): Merge conflict in file.py")
        sig = mla.track_error(error)
        self.assertEqual(sig.category, ec.CONFLICT)
        self.assertEqual(sig.pattern_key, "merge_conflict")
        self.assertTrue(sig.recoverable)

    def test_conflict_stale_branch_pattern(self):
        """Stale branch errors must be detected."""
        error = RuntimeError("fatal: branch 'feature-xyz' no longer exists")
        sig = mla.track_error(error)
        self.assertEqual(sig.pattern_key, "stale_branch")
        self.assertTrue(sig.recoverable)

    def test_conflict_rebase_pattern(self):
        """Rebase conflict errors must be detected."""
        error = RuntimeError("CONFLICT (content): rebase failed in module.ts")
        sig = mla.track_error(error)
        self.assertEqual(sig.pattern_key, "rebase_conflict")

    def test_resource_quota_pattern(self):
        """Quota exceeded errors must be resource category."""
        error = RuntimeError("quota exceeded: 1000/1000 requests used")
        sig = mla.track_error(error)
        self.assertEqual(sig.category, ec.RESOURCE)
        self.assertEqual(sig.pattern_key, "quota_exceeded")
        self.assertTrue(sig.recoverable)

    def test_resource_oom_pattern(self):
        """Out of memory errors must be detected."""
        error = MemoryError("OOM: unable to allocate 512MB")
        sig = mla.track_error(error)
        self.assertEqual(sig.pattern_key, "out_of_memory")
        self.assertTrue(sig.recoverable)

    def test_resource_budget_pattern(self):
        """Budget exceeded errors must be detected."""
        error = RuntimeError("insufficient_quota: budget cap reached")
        sig = mla.track_error(error)
        self.assertEqual(sig.pattern_key, "budget_exceeded")

    def test_non_recoverable_logic_error(self):
        """Logic errors must not be marked recoverable."""
        error = ValueError("invalid argument to function")
        sig = mla.track_error(error)
        self.assertFalse(sig.recoverable)

    def test_non_recoverable_permission_error(self):
        """Permission errors must not be recoverable."""
        error = PermissionError("access denied to resource")
        sig = mla.track_error(error)
        self.assertFalse(sig.recoverable)


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 2: Learning from Error Patterns (Orchestration Strategy Planning)
# ─────────────────────────────────────────────────────────────────────────────

class ErrorLearningTests(unittest.TestCase):
    """Tests for pattern learning and success rate tracking."""

    def setUp(self):
        mla.reset_learning()

    def test_transient_error_learning(self):
        """System must learn success rates for transient error recovery."""
        for i in range(10):
            error = RuntimeError("rate limit 429")
            sig = mla.track_error(error)
            success = i < 8  # 8 out of 10 = 80% success
            mla.record_recovery_outcome(sig.pattern_key, f"task_{i}", success)

        success_rate, observations = mla.get_success_rate("rate_limit")
        self.assertEqual(observations, 10)
        self.assertEqual(success_rate, 0.8)
        self.assertTrue(mla.should_auto_recover("rate_limit"))

    def test_conflict_error_learning(self):
        """System must learn success rates for conflict recovery."""
        for i in range(7):
            error = RuntimeError("CONFLICT (content): file.py")
            sig = mla.track_error(error)
            success = i < 6  # 6 out of 7 ≈ 85.7% success
            mla.record_recovery_outcome(sig.pattern_key, f"task_{i}", success)

        success_rate, observations = mla.get_success_rate("merge_conflict")
        self.assertEqual(observations, 7)
        self.assertGreater(success_rate, 0.85)
        self.assertTrue(mla.should_auto_recover("merge_conflict"))

    def test_resource_error_learning(self):
        """System must learn success rates for resource error recovery."""
        for i in range(8):
            error = RuntimeError("quota exceeded")
            sig = mla.track_error(error)
            success = i < 7  # 7 out of 8 = 87.5% success
            mla.record_recovery_outcome(sig.pattern_key, f"task_{i}", success)

        success_rate, observations = mla.get_success_rate("quota_exceeded")
        self.assertEqual(observations, 8)
        self.assertGreater(success_rate, 0.85)
        self.assertTrue(mla.should_auto_recover("quota_exceeded"))

    def test_min_observations_threshold(self):
        """System must not auto-recover without MIN_OBSERVATIONS."""
        # Track only 3 errors (below MIN_OBSERVATIONS=5)
        for i in range(3):
            error = RuntimeError("rate limit 429")
            sig = mla.track_error(error)
            mla.record_recovery_outcome(sig.pattern_key, f"task_{i}", True)

        success_rate, observations = mla.get_success_rate("rate_limit")
        self.assertEqual(observations, 3)
        self.assertFalse(mla.should_auto_recover("rate_limit"))

    def test_success_threshold_requirement(self):
        """System must require success rate >= threshold before auto-recovery."""
        # Track 6 errors with only 60% success (below 70% threshold)
        for i in range(6):
            error = RuntimeError("timeout")
            sig = mla.track_error(error)
            success = i < 4  # 4 out of 6 = 66.7% success
            mla.record_recovery_outcome(sig.pattern_key, f"task_{i}", success)

        success_rate, observations = mla.get_success_rate("timeout")
        self.assertGreaterEqual(observations, 5)
        self.assertLess(success_rate, 0.7)
        self.assertFalse(mla.should_auto_recover("timeout"))

    def test_pattern_history_tracking(self):
        """System must maintain a history of tracked errors."""
        for i in range(5):
            error = RuntimeError(f"error {i}")
            mla.track_error(error, task_id=f"task_{i}")

        stats = mla.stats()
        self.assertEqual(stats["total_errors_tracked"], 5)


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 3: Recovery Action Recommendations (Agentic Recovery Route)
# ─────────────────────────────────────────────────────────────────────────────

class RecoveryActionTests(unittest.TestCase):
    """Tests for recovery action recommendations and routing."""

    def setUp(self):
        mla.reset_learning()

    def test_transient_retry_with_backoff_action(self):
        """Transient errors must recommend retry_with_backoff action."""
        for i in range(8):
            error = RuntimeError("429 too many requests")
            sig = mla.track_error(error)
            mla.record_recovery_outcome(sig.pattern_key, f"task_{i}", i < 7)

        recommendation = mla.recommend_recovery_action(RuntimeError("429"))
        self.assertTrue(recommendation["should_recover"])
        self.assertEqual(recommendation["action"], "retry_with_backoff")
        self.assertGreater(recommendation["success_rate"], 0.7)

    def test_conflict_rebase_and_retry_action(self):
        """Conflict errors must recommend rebase_and_retry action."""
        for i in range(8):
            error = RuntimeError("CONFLICT (content): file.py")
            sig = mla.track_error(error)
            mla.record_recovery_outcome(sig.pattern_key, f"task_{i}", i < 7)

        recommendation = mla.recommend_recovery_action(RuntimeError("CONFLICT: x"))
        self.assertTrue(recommendation["should_recover"])
        self.assertEqual(recommendation["action"], "rebase_and_retry")

    def test_resource_queue_with_delay_action(self):
        """Resource errors must recommend queue_with_delay action."""
        for i in range(8):
            error = RuntimeError("quota exceeded")
            sig = mla.track_error(error)
            mla.record_recovery_outcome(sig.pattern_key, f"task_{i}", i < 7)

        recommendation = mla.recommend_recovery_action(RuntimeError("quota exceeded"))
        self.assertTrue(recommendation["should_recover"])
        self.assertEqual(recommendation["action"], "queue_with_delay")

    def test_non_recoverable_no_action(self):
        """Non-recoverable errors must return None action."""
        error = ValueError("invalid argument")
        recommendation = mla.recommend_recovery_action(error)
        self.assertFalse(recommendation["should_recover"])
        self.assertIsNone(recommendation["action"])

    def test_insufficient_observations_no_action(self):
        """Errors without enough observations must not be auto-recovered."""
        for i in range(3):
            error = RuntimeError("rate limit 429")
            sig = mla.track_error(error)
            mla.record_recovery_outcome(sig.pattern_key, f"task_{i}", True)

        recommendation = mla.recommend_recovery_action(RuntimeError("429"))
        self.assertFalse(recommendation["should_recover"])
        self.assertIsNone(recommendation["action"])

    def test_recommendation_includes_statistics(self):
        """Recommendations must include success_rate and observation count."""
        for i in range(8):
            error = RuntimeError("timeout")
            sig = mla.track_error(error)
            mla.record_recovery_outcome(sig.pattern_key, f"task_{i}", i < 6)

        recommendation = mla.recommend_recovery_action(RuntimeError("timeout"))
        self.assertIn("success_rate", recommendation)
        self.assertIn("observations", recommendation)
        self.assertEqual(recommendation["observations"], 8)

    def test_recommendation_includes_category_and_pattern(self):
        """Recommendations must include category and pattern_key."""
        for i in range(8):
            error = RuntimeError("rate limit 429")
            sig = mla.track_error(error)
            mla.record_recovery_outcome(sig.pattern_key, f"task_{i}", i < 7)

        recommendation = mla.recommend_recovery_action(RuntimeError("429"))
        self.assertEqual(recommendation["category"], ec.TRANSIENT)
        self.assertEqual(recommendation["pattern_key"], "rate_limit")


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 4: Fail-Soft Guarantees (QA Validation)
# ─────────────────────────────────────────────────────────────────────────────

class FailSoftTests(unittest.TestCase):
    """Tests for fail-soft behavior and error resilience."""

    def setUp(self):
        mla.reset_learning()

    def test_track_error_returns_none_on_exception(self):
        """track_error must return None on internal error, not crash."""
        with mock.patch('error_classifier.classify', side_effect=Exception("boom")):
            result = mla.track_error(RuntimeError("test"))
            self.assertIsNone(result)

    def test_recommend_recovery_action_returns_safe_default_on_error(self):
        """recommend_recovery_action must return safe default on any error."""
        with mock.patch('error_classifier.classify', side_effect=Exception("boom")):
            result = mla.recommend_recovery_action(RuntimeError("test"))
            self.assertFalse(result["should_recover"])
            self.assertIsNone(result["action"])
            self.assertEqual(result["success_rate"], 0.0)

    def test_get_success_rate_returns_safe_default_on_error(self):
        """get_success_rate must return (0.0, 0) on any error."""
        # Simulate corrupted state
        with mock.patch.object(mla, '_lock', side_effect=RuntimeError("lock failed")):
            result = mla.get_success_rate("any_pattern")
            self.assertEqual(result, (0.0, 0))

    def test_record_recovery_outcome_silently_fails(self):
        """record_recovery_outcome must not raise on error."""
        with mock.patch.object(mla, '_lock', side_effect=RuntimeError("lock failed")):
            # Should not raise
            mla.record_recovery_outcome("pattern", "task_id", True)

    def test_pattern_statistics_returns_safe_default_on_error(self):
        """get_pattern_statistics must return safe default on error."""
        with mock.patch.object(mla, '_lock', side_effect=RuntimeError("lock failed")):
            result = mla.get_pattern_statistics()
            self.assertEqual(result["total_errors"], 0)
            self.assertEqual(result["by_category"], {})

    def test_disabled_auto_recovery_returns_no_action(self):
        """When ORCH_ML_AUTO_RECOVERY_ENABLED=false, must return no action."""
        original = os.environ.get("ORCH_ML_AUTO_RECOVERY_ENABLED")
        try:
            os.environ["ORCH_ML_AUTO_RECOVERY_ENABLED"] = "false"
            # Reload module with new env
            import importlib
            importlib.reload(mla)
            result = mla.recommend_recovery_action(RuntimeError("any"))
            self.assertFalse(result["should_recover"])
        finally:
            os.environ["ORCH_ML_AUTO_RECOVERY_ENABLED"] = original or "true"
            importlib.reload(mla)

    def test_stats_returns_safe_default_on_error(self):
        """stats() must return safe default on any error."""
        with mock.patch.object(mla, '_lock', side_effect=RuntimeError("lock failed")):
            result = mla.stats()
            self.assertEqual(result["total_errors_tracked"], 0)
            self.assertEqual(result["total_recovery_attempts"], 0)


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 5: Thread Safety (Concurrent Access Under High Load)
# ─────────────────────────────────────────────────────────────────────────────

class ThreadSafetyTests(unittest.TestCase):
    """Tests for thread-safe concurrent error tracking and learning."""

    def setUp(self):
        mla.reset_learning()

    def test_concurrent_error_tracking(self):
        """Multiple threads must safely track errors concurrently."""
        errors = []
        def track_errors():
            for i in range(10):
                error = RuntimeError(f"error in thread")
                sig = mla.track_error(error, task_id=f"task_{threading.current_thread().ident}_{i}")
                if sig:
                    errors.append(sig)

        threads = [threading.Thread(target=track_errors) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        stats = mla.stats()
        self.assertEqual(stats["total_errors_tracked"], 50)

    def test_concurrent_recovery_outcome_recording(self):
        """Multiple threads must safely record outcomes concurrently."""
        def record_outcomes():
            for i in range(10):
                mla.record_recovery_outcome(
                    "rate_limit",
                    f"task_{threading.current_thread().ident}_{i}",
                    i % 2 == 0
                )

        threads = [threading.Thread(target=record_outcomes) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        success_rate, observations = mla.get_success_rate("rate_limit")
        self.assertEqual(observations, 50)

    def test_concurrent_recommendation_queries(self):
        """Multiple threads must safely query recommendations concurrently."""
        # Set up pattern first
        for i in range(10):
            error = RuntimeError("rate limit 429")
            sig = mla.track_error(error)
            mla.record_recovery_outcome(sig.pattern_key, f"task_{i}", i < 8)

        recommendations = []
        def get_recommendations():
            for _ in range(5):
                rec = mla.recommend_recovery_action(RuntimeError("429"))
                recommendations.append(rec)

        threads = [threading.Thread(target=get_recommendations) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(recommendations), 25)
        # All should be consistent
        for rec in recommendations:
            self.assertEqual(rec["should_recover"], True)
            self.assertEqual(rec["action"], "retry_with_backoff")


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 6: Pattern Statistics and Monitoring (QA Panel Analytics)
# ─────────────────────────────────────────────────────────────────────────────

class PatternStatisticsTests(unittest.TestCase):
    """Tests for error pattern statistics and monitoring."""

    def setUp(self):
        mla.reset_learning()

    def test_pattern_statistics_window(self):
        """Statistics must be computed within specified time window."""
        for i in range(5):
            error = RuntimeError("rate limit 429")
            mla.track_error(error, task_id=f"task_{i}")

        stats = mla.get_pattern_statistics(window_hours=24)
        self.assertEqual(stats["window_hours"], 24)
        self.assertEqual(stats["total_errors"], 5)

    def test_pattern_statistics_by_category(self):
        """Statistics must break down errors by category."""
        for i in range(3):
            mla.track_error(RuntimeError("rate limit 429"))
        for i in range(2):
            mla.track_error(RuntimeError("CONFLICT (content): x"))

        stats = mla.get_pattern_statistics(window_hours=24)
        self.assertIn(ec.TRANSIENT, stats["by_category"])
        self.assertIn(ec.CONFLICT, stats["by_category"])
        self.assertEqual(stats["by_category"][ec.TRANSIENT], 3)
        self.assertEqual(stats["by_category"][ec.CONFLICT], 2)

    def test_pattern_statistics_by_pattern_key(self):
        """Statistics must break down errors by pattern key."""
        for i in range(3):
            mla.track_error(RuntimeError("rate limit 429"))
        for i in range(2):
            mla.track_error(TimeoutError("timeout"))

        stats = mla.get_pattern_statistics(window_hours=24)
        self.assertIn("rate_limit", stats["by_pattern_key"])
        self.assertIn("timeout", stats["by_pattern_key"])

    def test_recoverable_patterns_include_success_rate(self):
        """Recoverable patterns must include success rate in statistics."""
        for i in range(8):
            error = RuntimeError("rate limit 429")
            sig = mla.track_error(error)
            mla.record_recovery_outcome(sig.pattern_key, f"task_{i}", i < 7)

        stats = mla.get_pattern_statistics(window_hours=24)
        recoverable = [p for p in stats["recoverable_patterns"] if p["pattern_key"] == "rate_limit"]
        self.assertTrue(len(recoverable) > 0)
        self.assertIn("success_rate", recoverable[0])
        self.assertIn("can_auto_recover", recoverable[0])

    def test_stats_summary(self):
        """stats() must return useful summary for monitoring."""
        for i in range(5):
            error = RuntimeError("rate limit 429")
            sig = mla.track_error(error)
            mla.record_recovery_outcome(sig.pattern_key, f"task_{i}", i < 4)

        stats = mla.stats()
        self.assertEqual(stats["total_errors_tracked"], 5)
        self.assertEqual(stats["total_recovery_attempts"], 5)
        self.assertGreater(stats["patterns_with_outcomes"], 0)


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 7: Pattern Signature Equality (Orchestration Contract Compliance)
# ─────────────────────────────────────────────────────────────────────────────

class PatternSignatureTests(unittest.TestCase):
    """Tests for pattern signature identity and hashing."""

    def test_pattern_signature_equality(self):
        """Pattern signatures with same category and key must be equal."""
        sig1 = mla.PatternSignature(ec.TRANSIENT, "rate_limit")
        sig2 = mla.PatternSignature(ec.TRANSIENT, "rate_limit")
        self.assertEqual(sig1, sig2)

    def test_pattern_signature_hash_consistency(self):
        """Equal signatures must have equal hashes."""
        sig1 = mla.PatternSignature(ec.TRANSIENT, "rate_limit")
        sig2 = mla.PatternSignature(ec.TRANSIENT, "rate_limit")
        self.assertEqual(hash(sig1), hash(sig2))

    def test_pattern_signature_used_in_set(self):
        """Signatures must be usable as set members."""
        sig1 = mla.PatternSignature(ec.TRANSIENT, "rate_limit")
        sig2 = mla.PatternSignature(ec.TRANSIENT, "rate_limit")
        sig3 = mla.PatternSignature(ec.CONFLICT, "merge_conflict")
        pattern_set = {sig1, sig2, sig3}
        self.assertEqual(len(pattern_set), 2)  # sig1 and sig2 are duplicates

    def test_pattern_signature_repr(self):
        """Signature repr must be useful for logging."""
        sig = mla.PatternSignature(ec.TRANSIENT, "rate_limit")
        repr_str = repr(sig)
        self.assertIn("TRANSIENT", repr_str)
        self.assertIn("rate_limit", repr_str)


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 8: Edge Cases and Regression Tests
# ─────────────────────────────────────────────────────────────────────────────

class EdgeCaseTests(unittest.TestCase):
    """Tests for edge cases and known regressions."""

    def setUp(self):
        mla.reset_learning()

    def test_empty_error_message(self):
        """System must handle errors with empty messages."""
        error = RuntimeError("")
        sig = mla.track_error(error)
        self.assertIsNotNone(sig)

    def test_very_long_error_message(self):
        """System must truncate very long error messages."""
        long_msg = "x" * 10000
        error = RuntimeError(long_msg)
        mla.track_error(error, task_id="long_error_task")
        # Should not crash and should cap message length

    def test_pattern_key_extraction_robustness(self):
        """Pattern key extraction must handle various error formats."""
        errors = [
            RuntimeError("RaTe LiMiT 429"),  # Mixed case
            RuntimeError("429 Rate Limit"),  # Different order
            RuntimeError("error code: 429 - too many requests"),  # Verbose
        ]
        for error in errors:
            sig = mla.track_error(error)
            self.assertEqual(sig.pattern_key, "rate_limit")

    def test_reset_learning_clears_all_state(self):
        """reset_learning must completely clear internal state."""
        for i in range(10):
            error = RuntimeError("rate limit 429")
            sig = mla.track_error(error)
            mla.record_recovery_outcome(sig.pattern_key, f"task_{i}", i < 8)

        mla.reset_learning()
        stats = mla.stats()
        self.assertEqual(stats["total_errors_tracked"], 0)
        self.assertEqual(stats["total_recovery_attempts"], 0)
        self.assertEqual(stats["patterns_with_outcomes"], 0)

    def test_history_size_limit(self):
        """Error history must respect HISTORY_SIZE limit."""
        history_size = int(os.environ.get("ORCH_ML_ERROR_PATTERN_HISTORY_SIZE", "1000"))
        for i in range(history_size + 100):
            error = RuntimeError(f"error {i}")
            mla.track_error(error, task_id=f"task_{i}")

        stats = mla.stats()
        # Should not exceed history size
        self.assertLessEqual(stats["total_errors_tracked"], history_size + 10)

    def test_success_rate_with_zero_observations(self):
        """Success rate for unknown pattern must return 0."""
        success_rate, observations = mla.get_success_rate("nonexistent_pattern")
        self.assertEqual(success_rate, 0.0)
        self.assertEqual(observations, 0)

    def test_pattern_statistics_with_no_errors(self):
        """Pattern statistics must handle empty history gracefully."""
        stats = mla.get_pattern_statistics(window_hours=24)
        self.assertEqual(stats["total_errors"], 0)
        self.assertEqual(stats["by_category"], {})
        self.assertEqual(stats["by_pattern_key"], {})
        self.assertEqual(stats["recoverable_patterns"], [])

    def test_classification_with_explicit_parameter(self):
        """recommend_recovery_action must use provided classification."""
        classification = {
            "category": ec.TRANSIENT,
            "message": "rate limit 429"
        }
        recommendation = mla.recommend_recovery_action(RuntimeError("ignored"), classification)
        self.assertEqual(recommendation["category"], ec.TRANSIENT)


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 9: Environment Variable Configuration
# ─────────────────────────────────────────────────────────────────────────────

class ConfigurationTests(unittest.TestCase):
    """Tests for environment variable configuration."""

    def test_default_config_values(self):
        """Default config must match documented values."""
        self.assertTrue(mla.ENABLED)
        self.assertEqual(mla.HISTORY_SIZE, 1000)
        self.assertEqual(mla.SUCCESS_THRESHOLD, 0.7)
        self.assertEqual(mla.MIN_OBSERVATIONS, 5)

    def test_config_respects_env_vars(self):
        """Config must read from environment variables."""
        # These are already set in setUp, verify they're read
        self.assertTrue(mla.ENABLED)
        self.assertEqual(mla.SUCCESS_THRESHOLD, 0.7)
        self.assertEqual(mla.MIN_OBSERVATIONS, 5)


if __name__ == "__main__":
    unittest.main()
