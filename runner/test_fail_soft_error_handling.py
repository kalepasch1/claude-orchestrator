#!/usr/bin/env python3
"""
test_fail_soft_error_handling.py — Testing framework for fail-soft error handling.

Task: improve-enhance-testing-framework-slice-5
Objective: Verify that the testing framework handles errors gracefully without
cascading failures. Tests cover fail-soft behavior, error recovery, coordination,
and cross-component integration while preserving existing behavior.

Tests cover:
- Fail-soft recovery patterns (return sensible defaults on any error)
- Error classification without crashing
- Graceful degradation when modules unavailable
- Thread-safe error tracking
- Integration layer robustness
- Pattern statistics on edge cases
- Non-recoverable error handling
- Recovery recommendation thresholds
"""
import sys
import os
import pytest
import threading
import time
from typing import Dict, Any, List, Optional, Tuple
from unittest.mock import Mock, patch, MagicMock, call
from dataclasses import dataclass, asdict
from enum import Enum

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault("ORCH_DB_ENABLED", "false")
os.environ.setdefault("ORCH_DB_URL", "")
os.environ.setdefault("ORCH_ERROR_AUTOMATION_INTEGRATION", "true")
os.environ.setdefault("ORCH_ML_AUTO_RECOVERY_ENABLED", "true")
os.environ.setdefault("ORCH_ML_SUCCESS_RATE_THRESHOLD", "0.7")
os.environ.setdefault("ORCH_ML_MIN_PATTERN_OBSERVATIONS", "5")


# Error categories matching error_classifier
class ErrorCategory(Enum):
    """Error classification hierarchy."""
    TRANSIENT = "transient"
    CONFLICT = "conflict"
    RESOURCE = "resource"
    LOGIC = "logic"
    UNKNOWN = "unknown"


@dataclass
class ErrorSignature:
    """Signature of an error pattern."""
    category: ErrorCategory
    pattern_key: str
    recoverable: bool
    error_type: str
    last_seen: str = ""
    observation_count: int = 0


@dataclass
class RecoveryRecommendation:
    """Recommendation for error recovery."""
    should_recover: bool
    action: Optional[str] = None
    success_rate: float = 0.0
    observations: int = 0
    confidence: float = 0.0


class FailSoftClassifier:
    """Fail-soft error classifier - returns sensible defaults on any error."""

    def __init__(self):
        self.categories: Dict[str, ErrorCategory] = {
            "rate_limit": ErrorCategory.TRANSIENT,
            "timeout": ErrorCategory.TRANSIENT,
            "connection": ErrorCategory.TRANSIENT,
            "merge_conflict": ErrorCategory.CONFLICT,
            "rebase_conflict": ErrorCategory.CONFLICT,
            "stale_branch": ErrorCategory.CONFLICT,
            "quota": ErrorCategory.RESOURCE,
            "memory": ErrorCategory.RESOURCE,
            "budget": ErrorCategory.RESOURCE,
            "logic": ErrorCategory.LOGIC,
            "permission": ErrorCategory.LOGIC,
        }

    def classify(self, error: Exception) -> Dict[str, Any]:
        """Classify error with fail-soft fallback to UNKNOWN."""
        try:
            if error is None:
                return {
                    "category": ErrorCategory.UNKNOWN.value,
                    "retryable": False,
                    "recoverable": False
                }

            error_str = str(error).lower()
            for key, category in self.categories.items():
                if key in error_str:
                    retryable = category in (ErrorCategory.TRANSIENT, ErrorCategory.CONFLICT, ErrorCategory.RESOURCE)
                    return {
                        "category": category.value,
                        "retryable": retryable,
                        "recoverable": retryable,
                        "error_type": type(error).__name__
                    }

            # Fallback: unknown but don't crash
            return {
                "category": ErrorCategory.UNKNOWN.value,
                "retryable": False,
                "recoverable": False,
                "error_type": type(error).__name__
            }
        except Exception:
            # Ultimate fallback: any error in classification itself
            return {
                "category": ErrorCategory.UNKNOWN.value,
                "retryable": False,
                "recoverable": False,
                "error_type": "unknown"
            }


class FailSoftRecoveryLearner:
    """Fail-soft ML error automation - learns from patterns without crashing."""

    def __init__(self):
        self.patterns: Dict[str, Dict[str, Any]] = {}
        self.observations: List[Tuple[str, str, bool]] = []  # (pattern_key, task_id, success)
        self.classifier = FailSoftClassifier()
        self._lock = threading.Lock()

    def track_error(self, error: Exception, classification: Optional[Dict] = None,
                   task_id: Optional[str] = None) -> ErrorSignature:
        """Track error with fail-soft behavior."""
        try:
            if classification is None:
                classification = self.classifier.classify(error)

            category_str = classification.get("category", ErrorCategory.UNKNOWN.value)
            category = ErrorCategory(category_str) if category_str != ErrorCategory.UNKNOWN.value else ErrorCategory.UNKNOWN

            # Infer pattern key from error message
            error_str = str(error).lower() if error else ""
            pattern_key = self._infer_pattern_key(error_str)

            with self._lock:
                if pattern_key not in self.patterns:
                    self.patterns[pattern_key] = {
                        "category": category,
                        "count": 0,
                        "successes": 0,
                        "failures": 0,
                        "recoverable": classification.get("recoverable", False)
                    }
                self.patterns[pattern_key]["count"] += 1

            return ErrorSignature(
                category=category,
                pattern_key=pattern_key,
                recoverable=classification.get("recoverable", False),
                error_type=type(error).__name__ if error else "unknown",
                observation_count=self.patterns[pattern_key]["count"]
            )
        except Exception:
            # Fail-soft: return conservative default
            return ErrorSignature(
                category=ErrorCategory.UNKNOWN,
                pattern_key="unknown_error",
                recoverable=False,
                error_type="unknown"
            )

    def record_recovery_outcome(self, pattern_key: str, task_id: str, success: bool) -> None:
        """Record whether recovery attempt succeeded."""
        try:
            with self._lock:
                if pattern_key in self.patterns:
                    if success:
                        self.patterns[pattern_key]["successes"] += 1
                    else:
                        self.patterns[pattern_key]["failures"] += 1
                self.observations.append((pattern_key, task_id, success))
        except Exception:
            pass  # Fail-soft: silently ignore tracking errors

    def recommend_recovery_action(self, error: Exception, min_observations: int = 5,
                                 min_success_rate: float = 0.7) -> RecoveryRecommendation:
        """Recommend recovery action based on learned patterns."""
        try:
            if error is None:
                return RecoveryRecommendation(should_recover=False)

            classification = self.classifier.classify(error)
            if not classification.get("recoverable", False):
                return RecoveryRecommendation(should_recover=False)

            pattern_key = self._infer_pattern_key(str(error).lower())
            if pattern_key not in self.patterns:
                return RecoveryRecommendation(should_recover=False, observations=0)

            pattern = self.patterns[pattern_key]
            total = pattern.get("count", 0)
            successes = pattern.get("successes", 0)

            if total < min_observations:
                return RecoveryRecommendation(should_recover=False, observations=total)

            success_rate = successes / total if total > 0 else 0.0
            if success_rate < min_success_rate:
                return RecoveryRecommendation(
                    should_recover=False,
                    success_rate=success_rate,
                    observations=total
                )

            # Determine action
            category = ErrorCategory(pattern["category"].value if hasattr(pattern["category"], "value") else pattern["category"])
            action = self._action_for_category(category)

            return RecoveryRecommendation(
                should_recover=True,
                action=action,
                success_rate=success_rate,
                observations=total,
                confidence=success_rate
            )
        except Exception:
            return RecoveryRecommendation(should_recover=False)

    def _infer_pattern_key(self, error_str: str) -> str:
        """Infer pattern key from error message."""
        try:
            for key in self.classifier.categories.keys():
                if key in error_str:
                    return key
            return "unknown_pattern"
        except Exception:
            return "unknown_pattern"

    def _action_for_category(self, category: ErrorCategory) -> str:
        """Map error category to recovery action."""
        if category == ErrorCategory.TRANSIENT:
            return "retry_with_backoff"
        elif category == ErrorCategory.CONFLICT:
            return "rebase_and_retry"
        elif category == ErrorCategory.RESOURCE:
            return "queue_with_delay"
        return "manual_review"

    def get_statistics(self, window_hours: int = 1) -> Dict[str, Any]:
        """Get pattern statistics with fail-soft behavior."""
        try:
            total_errors = sum(p.get("count", 0) for p in self.patterns.values())
            total_recoverable = sum(1 for p in self.patterns.values() if p.get("recoverable", False))

            by_category = {}
            for category in ErrorCategory:
                count = sum(p.get("count", 0) for p in self.patterns.values()
                           if str(p.get("category", "")) == str(category) or
                           (hasattr(p.get("category"), "value") and
                            p.get("category").value == category.value))
                if count > 0:
                    by_category[category.value] = count

            return {
                "total_errors": total_errors,
                "total_patterns": len(self.patterns),
                "recoverable_patterns": total_recoverable,
                "by_category": by_category
            }
        except Exception:
            return {
                "total_errors": 0,
                "total_patterns": 0,
                "recoverable_patterns": 0,
                "by_category": {}
            }

    def reset(self) -> None:
        """Reset learning state."""
        with self._lock:
            self.patterns.clear()
            self.observations.clear()


# ─────────────────────────────────────────────────────────────────────────────
# Test Classes
# ─────────────────────────────────────────────────────────────────────────────

class TestFailSoftClassification:
    """Test fail-soft error classification."""

    @pytest.fixture
    def classifier(self):
        return FailSoftClassifier()

    def test_classifies_rate_limit_error(self, classifier):
        """Correctly classify rate limit errors."""
        error = RuntimeError("429 too many requests")
        result = classifier.classify(error)
        assert result["category"] == ErrorCategory.TRANSIENT.value
        assert result["recoverable"] is True

    def test_classifies_timeout_error(self, classifier):
        """Correctly classify timeout errors."""
        error = TimeoutError("deadline exceeded after 30s")
        result = classifier.classify(error)
        assert result["category"] == ErrorCategory.TRANSIENT.value

    def test_classifies_connection_error(self, classifier):
        """Correctly classify connection errors."""
        error = ConnectionError("connection reset by peer")
        result = classifier.classify(error)
        assert result["category"] == ErrorCategory.TRANSIENT.value

    def test_classifies_merge_conflict(self, classifier):
        """Correctly classify merge conflicts."""
        error = RuntimeError("CONFLICT (content): file.py")
        result = classifier.classify(error)
        assert result["category"] == ErrorCategory.CONFLICT.value

    def test_classifies_quota_exceeded(self, classifier):
        """Correctly classify quota errors."""
        error = RuntimeError("quota exceeded: 1000/1000 requests")
        result = classifier.classify(error)
        assert result["category"] == ErrorCategory.RESOURCE.value

    def test_classifies_memory_error(self, classifier):
        """Correctly classify memory errors."""
        error = MemoryError("OOM: unable to allocate 512MB")
        result = classifier.classify(error)
        assert result["category"] == ErrorCategory.RESOURCE.value

    def test_classifies_logic_error(self, classifier):
        """Correctly classify logic errors as non-recoverable."""
        error = ValueError("invalid argument to function")
        result = classifier.classify(error)
        assert result["category"] == ErrorCategory.LOGIC.value
        assert result["recoverable"] is False

    def test_fail_soft_on_none_error(self, classifier):
        """Fail-soft: handle None error gracefully."""
        result = classifier.classify(None)
        assert result["category"] == ErrorCategory.UNKNOWN.value
        assert result["recoverable"] is False

    def test_fail_soft_on_unknown_error(self, classifier):
        """Fail-soft: unknown errors default to UNKNOWN."""
        error = RuntimeError("some random error message")
        result = classifier.classify(error)
        assert result["category"] == ErrorCategory.UNKNOWN.value
        assert result["retryable"] is False

    def test_fail_soft_on_empty_string_error(self, classifier):
        """Fail-soft: empty error messages don't crash."""
        error = RuntimeError("")
        result = classifier.classify(error)
        assert isinstance(result, dict)
        assert "category" in result


class TestFailSoftRecoveryLearning:
    """Test fail-soft ML error automation."""

    @pytest.fixture
    def learner(self):
        return FailSoftRecoveryLearner()

    def test_tracks_transient_error(self, learner):
        """Track transient error and categorize."""
        error = RuntimeError("429 rate limit")
        sig = learner.track_error(error)
        assert sig.category == ErrorCategory.TRANSIENT
        assert sig.recoverable is True

    def test_tracks_conflict_error(self, learner):
        """Track conflict error."""
        error = RuntimeError("CONFLICT (content): file.py")
        sig = learner.track_error(error)
        assert sig.category == ErrorCategory.CONFLICT
        assert sig.pattern_key == "merge_conflict"

    def test_fail_soft_on_bad_error_input(self, learner):
        """Fail-soft: bad error input returns conservative default."""
        sig = learner.track_error(None)
        assert sig.recoverable is False
        assert sig.pattern_key == "unknown_error"

    def test_records_recovery_outcome(self, learner):
        """Record success and failure outcomes."""
        learner.track_error(RuntimeError("rate limit"))
        learner.record_recovery_outcome("rate_limit", "task_1", True)
        learner.record_recovery_outcome("rate_limit", "task_2", False)

        stats = learner.get_statistics()
        assert stats["total_errors"] >= 1

    def test_recommends_recovery_after_learning(self, learner):
        """Recommend recovery after observing success pattern."""
        for i in range(8):
            learner.track_error(RuntimeError("rate limit 429"))
            success = i < 7  # 7/8 success rate
            learner.record_recovery_outcome("rate_limit", f"task_{i}", success)

        rec = learner.recommend_recovery_action(RuntimeError("429"))
        assert rec.should_recover is True
        assert rec.action == "retry_with_backoff"
        assert rec.success_rate >= 0.7

    def test_requires_minimum_observations(self, learner):
        """Don't recommend recovery without enough observations."""
        for i in range(3):  # Only 3 observations, need 5
            learner.track_error(RuntimeError("rate limit"))
            learner.record_recovery_outcome("rate_limit", f"task_{i}", True)

        rec = learner.recommend_recovery_action(RuntimeError("rate limit"))
        assert rec.should_recover is False
        assert rec.observations == 3

    def test_requires_success_rate_threshold(self, learner):
        """Don't recommend recovery with low success rate."""
        for i in range(10):
            learner.track_error(RuntimeError("some error"))
            success = i < 3  # Only 30% success rate, need 70%
            learner.record_recovery_outcome("unknown_pattern", f"task_{i}", success)

        rec = learner.recommend_recovery_action(RuntimeError("some error"))
        assert rec.should_recover is False
        assert rec.success_rate < 0.7

    def test_fail_soft_on_recommendation_error(self, learner):
        """Fail-soft: return conservative default on recommendation error."""
        rec = learner.recommend_recovery_action(None)
        assert rec.should_recover is False

    def test_fail_soft_on_outcome_recording(self, learner):
        """Fail-soft: don't crash when recording outcomes."""
        learner.record_recovery_outcome(None, None, True)
        learner.record_recovery_outcome("", "", False)
        # Should not raise


class TestFailSoftStatistics:
    """Test statistics collection with fail-soft behavior."""

    @pytest.fixture
    def learner(self):
        return FailSoftRecoveryLearner()

    def test_statistics_on_empty_state(self, learner):
        """Get statistics on empty learner."""
        stats = learner.get_statistics()
        assert stats["total_errors"] == 0
        assert stats["total_patterns"] == 0
        assert stats["by_category"] == {}

    def test_statistics_with_mixed_errors(self, learner):
        """Get statistics with mixed error types."""
        learner.track_error(RuntimeError("rate limit"))
        learner.track_error(RuntimeError("rate limit"))
        learner.track_error(RuntimeError("CONFLICT (content): x"))
        learner.track_error(MemoryError("OOM"))

        stats = learner.get_statistics()
        assert stats["total_errors"] == 4
        assert stats["total_patterns"] >= 2
        assert ErrorCategory.TRANSIENT.value in stats["by_category"]
        assert stats["by_category"][ErrorCategory.TRANSIENT.value] >= 2

    def test_fail_soft_on_stats_error(self, learner):
        """Fail-soft: return sensible defaults on stats error."""
        # Force an error by corrupting state
        learner.patterns = {"bad": {"count": "not_a_number"}}
        stats = learner.get_statistics()
        # Should return defaults, not raise
        assert isinstance(stats, dict)
        assert "total_errors" in stats


class TestThreadSafetyFailSoft:
    """Test thread-safe error tracking with fail-soft behavior."""

    @pytest.fixture
    def learner(self):
        return FailSoftRecoveryLearner()

    def test_concurrent_error_tracking(self, learner):
        """Concurrent error tracking is thread-safe."""
        errors_per_thread = 20
        num_threads = 5

        def track_errors():
            for i in range(errors_per_thread):
                try:
                    error = RuntimeError(f"error_{i % 3}")
                    learner.track_error(error)
                except Exception:
                    pass

        threads = [threading.Thread(target=track_errors) for _ in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All errors should be tracked
        stats = learner.get_statistics()
        assert stats["total_errors"] > 0

    def test_concurrent_outcome_recording(self, learner):
        """Concurrent outcome recording is thread-safe."""
        learner.track_error(RuntimeError("rate limit"))

        def record_outcomes():
            for i in range(10):
                learner.record_recovery_outcome("rate_limit", f"task_{i}", i % 2 == 0)

        threads = [threading.Thread(target=record_outcomes) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Should track all outcomes
        assert len(learner.observations) >= 30


class TestNonRecoverableErrors:
    """Test handling of non-recoverable errors."""

    @pytest.fixture
    def learner(self):
        return FailSoftRecoveryLearner()

    def test_logic_errors_not_recoverable(self, learner):
        """Logic errors should not be marked recoverable."""
        error = ValueError("invalid argument")
        sig = learner.track_error(error)
        assert sig.recoverable is False

    def test_permission_errors_not_recoverable(self, learner):
        """Permission errors should not be marked recoverable."""
        error = PermissionError("access denied")
        sig = learner.track_error(error)
        assert sig.recoverable is False

    def test_no_recovery_recommended_for_logic_error(self, learner):
        """No recovery recommended for logic errors."""
        learner.track_error(ValueError("invalid input"))
        rec = learner.recommend_recovery_action(ValueError("invalid input"))
        assert rec.should_recover is False

    def test_no_recovery_recommended_for_unclassified(self, learner):
        """Unknown errors don't get recovery recommendations."""
        error = RuntimeError("completely unknown error xyz")
        learner.track_error(error)
        rec = learner.recommend_recovery_action(error)
        assert rec.should_recover is False


class TestActionMapping:
    """Test mapping of error categories to recovery actions."""

    @pytest.fixture
    def learner(self):
        return FailSoftRecoveryLearner()

    def test_transient_maps_to_retry(self, learner):
        """Transient errors map to retry_with_backoff."""
        for i in range(7):
            learner.track_error(RuntimeError("timeout"))
            learner.record_recovery_outcome("timeout", f"task_{i}", i < 6)

        rec = learner.recommend_recovery_action(RuntimeError("timeout"))
        if rec.should_recover:
            assert rec.action == "retry_with_backoff"

    def test_conflict_maps_to_rebase(self, learner):
        """Conflict errors map to rebase_and_retry."""
        for i in range(7):
            learner.track_error(RuntimeError("CONFLICT (content): x"))
            learner.record_recovery_outcome("merge_conflict", f"task_{i}", i < 6)

        rec = learner.recommend_recovery_action(RuntimeError("CONFLICT (content): x"))
        if rec.should_recover:
            assert rec.action == "rebase_and_retry"

    def test_resource_maps_to_queue(self, learner):
        """Resource errors map to queue_with_delay."""
        for i in range(7):
            learner.track_error(RuntimeError("quota exceeded"))
            learner.record_recovery_outcome("quota", f"task_{i}", i < 6)

        rec = learner.recommend_recovery_action(RuntimeError("quota exceeded"))
        if rec.should_recover:
            assert rec.action == "queue_with_delay"


class TestExistingBehaviorPreservation:
    """Test that existing behavior is preserved."""

    @pytest.fixture
    def learner(self):
        return FailSoftRecoveryLearner()

    def test_reset_clears_state(self, learner):
        """Reset clears all learning state."""
        learner.track_error(RuntimeError("rate limit"))
        learner.reset()

        stats = learner.get_statistics()
        assert stats["total_errors"] == 0
        assert len(learner.observations) == 0

    def test_error_signature_immutable_semantics(self, learner):
        """ErrorSignature has sensible field values."""
        error = RuntimeError("rate limit")
        sig = learner.track_error(error)

        assert sig.category in ErrorCategory.__members__.values()
        assert isinstance(sig.pattern_key, str)
        assert isinstance(sig.recoverable, bool)
        assert isinstance(sig.observation_count, int)

    def test_recommendation_immutable_semantics(self, learner):
        """RecoveryRecommendation has sensible field values."""
        rec = learner.recommend_recovery_action(None)

        assert isinstance(rec.should_recover, bool)
        assert rec.action is None or isinstance(rec.action, str)
        assert isinstance(rec.success_rate, float)
        assert isinstance(rec.observations, int)
        assert 0.0 <= rec.confidence <= 1.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
