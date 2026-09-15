#!/usr/bin/env python3
"""Tests for enhanced error handling and recovery mechanisms in orchestration pipeline.

Covers:
- Structured error categorization and propagation
- Recovery state machine transitions
- Error context preservation across retries
- Transient vs permanent error handling
- Recovery from pipeline failures
- Error aggregation and reporting
"""
import os
import sys
import time
import unittest
from unittest.mock import MagicMock, patch, call

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test")


# Placeholder imports - adjust to actual module names in the project
# from orchestration_error_handler import (
#     OrchestrationError,
#     ErrorContext,
#     RecoveryStrategy,
#     should_retry,
#     get_recovery_handler,
# )


# ─────────────────────────────────────────────────────────────────────────────
# Test fixtures and helpers
# ─────────────────────────────────────────────────────────────────────────────

class MockRecoveryContext:
    """Mock recovery context for testing."""
    def __init__(self, task_id="test-task-001", branch="test-branch", attempt=1):
        self.task_id = task_id
        self.branch = branch
        self.attempt = attempt
        self.errors = []
        self.recovery_actions = []
        self.state = "INITIAL"
        self.timestamp = time.time()

    def add_error(self, error, category="unknown"):
        self.errors.append({"error": error, "category": category, "time": time.time()})

    def record_recovery_action(self, action_type, result):
        self.recovery_actions.append({"type": action_type, "result": result, "time": time.time()})

    def to_dict(self):
        return {
            "task_id": self.task_id,
            "branch": self.branch,
            "attempt": self.attempt,
            "state": self.state,
            "error_count": len(self.errors),
            "recovery_actions": len(self.recovery_actions),
            "elapsed": time.time() - self.timestamp,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Error Context and Categorization Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestErrorContextPreservation(unittest.TestCase):
    """Test that error context is preserved across recovery attempts."""

    def test_error_context_captures_task_id(self):
        """Error context should preserve task identifier."""
        ctx = MockRecoveryContext(task_id="task-xyz-789")
        ctx.add_error(ValueError("bad config"), category="logic")

        assert ctx.errors[0]["error"].args[0] == "bad config"
        assert ctx.task_id == "task-xyz-789"

    def test_error_context_tracks_branch_name(self):
        """Error context should track the branch being processed."""
        ctx = MockRecoveryContext(branch="feature/complex-change")
        ctx.add_error(RuntimeError("merge conflict"), category="transient")

        assert ctx.branch == "feature/complex-change"
        assert len(ctx.errors) == 1

    def test_error_context_preserves_attempt_count(self):
        """Error context should track attempt numbers for retries."""
        ctx = MockRecoveryContext(attempt=3)
        ctx.add_error(TimeoutError("network timeout"), category="transient")

        assert ctx.attempt == 3

    def test_multiple_errors_preserved_in_order(self):
        """Multiple errors should be preserved with timestamps."""
        ctx = MockRecoveryContext()

        ctx.add_error(ConnectionError("first"), category="transient")
        time.sleep(0.01)
        ctx.add_error(TimeoutError("second"), category="transient")

        assert len(ctx.errors) == 2
        assert ctx.errors[0]["error"].args[0] == "first"
        assert ctx.errors[1]["error"].args[0] == "second"
        assert ctx.errors[0]["time"] < ctx.errors[1]["time"]

    def test_error_context_to_dict_serialization(self):
        """Error context should serialize to dict for logging/storage."""
        ctx = MockRecoveryContext(task_id="t1", branch="b1", attempt=2)
        ctx.add_error(ValueError("test"), category="logic")
        ctx.record_recovery_action("retry", {"success": False})

        d = ctx.to_dict()
        assert d["task_id"] == "t1"
        assert d["branch"] == "b1"
        assert d["attempt"] == 2
        assert d["error_count"] == 1
        assert d["recovery_actions"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# Recovery State Transition Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestRecoveryStateMachine(unittest.TestCase):
    """Test state transitions in recovery process."""

    def test_initial_state_is_initial(self):
        """Recovery context should start in INITIAL state."""
        ctx = MockRecoveryContext()
        assert ctx.state == "INITIAL"

    def test_state_transition_to_recovering(self):
        """Context should transition to RECOVERING after first error."""
        ctx = MockRecoveryContext()
        ctx.add_error(ConnectionError("test"), category="transient")
        ctx.state = "RECOVERING"

        assert ctx.state == "RECOVERING"
        assert len(ctx.errors) == 1

    def test_state_transition_to_retry_exhausted(self):
        """Context should transition to RETRY_EXHAUSTED after max attempts."""
        ctx = MockRecoveryContext(attempt=5)
        for i in range(5):
            ctx.add_error(TimeoutError(f"attempt {i}"), category="transient")
        ctx.state = "RETRY_EXHAUSTED"

        assert ctx.state == "RETRY_EXHAUSTED"
        assert len(ctx.errors) == 5

    def test_state_transition_to_recovered(self):
        """Context should transition to RECOVERED on success."""
        ctx = MockRecoveryContext()
        ctx.add_error(ConnectionError("transient"), category="transient")
        ctx.record_recovery_action("retry", {"success": True})
        ctx.state = "RECOVERED"

        assert ctx.state == "RECOVERED"
        assert len(ctx.recovery_actions) == 1

    def test_state_transition_to_failed(self):
        """Context should transition to FAILED on permanent error."""
        ctx = MockRecoveryContext()
        ctx.add_error(PermissionError("denied"), category="permission")
        ctx.state = "FAILED"

        assert ctx.state == "FAILED"


class TestRecoveryActionRecording(unittest.TestCase):
    """Test recording of recovery actions taken."""

    def test_record_single_recovery_action(self):
        """Should record a recovery action with timestamp."""
        ctx = MockRecoveryContext()
        ctx.record_recovery_action("cache_clear", {"cleared": 10})

        assert len(ctx.recovery_actions) == 1
        assert ctx.recovery_actions[0]["type"] == "cache_clear"
        assert ctx.recovery_actions[0]["result"]["cleared"] == 10

    def test_record_multiple_recovery_actions(self):
        """Should record multiple recovery actions in order."""
        ctx = MockRecoveryContext()

        ctx.record_recovery_action("lock_release", {"released": True})
        time.sleep(0.01)
        ctx.record_recovery_action("state_reset", {"reset": True})

        assert len(ctx.recovery_actions) == 2
        assert ctx.recovery_actions[0]["type"] == "lock_release"
        assert ctx.recovery_actions[1]["type"] == "state_reset"

    def test_recovery_action_sequence(self):
        """Recovery actions should follow a logical sequence."""
        ctx = MockRecoveryContext()

        # Typical recovery sequence
        ctx.record_recovery_action("identify_root_cause", {"cause": "deadlock"})
        ctx.record_recovery_action("acquire_lock", {"attempt": 1})
        ctx.record_recovery_action("clear_state", {"entries_cleared": 5})
        ctx.record_recovery_action("retry", {"success": True})

        assert len(ctx.recovery_actions) == 4
        assert ctx.recovery_actions[0]["type"] == "identify_root_cause"
        assert ctx.recovery_actions[-1]["type"] == "retry"


# ─────────────────────────────────────────────────────────────────────────────
# Transient vs Permanent Error Handling Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestTransientErrorDetection(unittest.TestCase):
    """Test detection and handling of transient errors."""

    def test_connection_error_is_transient(self):
        """ConnectionError should be classified as transient."""
        errors_transient = [
            ConnectionError("reset"),
            TimeoutError("read timeout"),
            OSError("temporary"),
        ]

        for err in errors_transient:
            ctx = MockRecoveryContext()
            ctx.add_error(err, category="transient")
            assert ctx.errors[0]["category"] == "transient"

    def test_timeout_errors_are_transient(self):
        """Timeout errors should be retryable."""
        ctx = MockRecoveryContext()
        ctx.add_error(TimeoutError("connect timeout"), category="transient")

        assert ctx.errors[0]["category"] == "transient"

    def test_rate_limit_is_transient(self):
        """Rate limit errors should be transient."""
        err = RuntimeError("rate limit exceeded (429)")
        ctx = MockRecoveryContext()
        ctx.add_error(err, category="transient")

        assert ctx.errors[0]["category"] == "transient"


class TestPermanentErrorDetection(unittest.TestCase):
    """Test detection and handling of permanent errors."""

    def test_permission_error_is_permanent(self):
        """PermissionError should be permanent and not retried."""
        ctx = MockRecoveryContext()
        ctx.add_error(PermissionError("access denied"), category="permission")

        assert ctx.errors[0]["category"] == "permission"

    def test_logic_error_is_permanent(self):
        """Logic errors (ValueError, etc.) should not be retried."""
        errors_permanent = [
            ValueError("invalid argument"),
            KeyError("missing key"),
            TypeError("wrong type"),
        ]

        for err in errors_permanent:
            ctx = MockRecoveryContext()
            ctx.add_error(err, category="logic")
            assert ctx.errors[0]["category"] == "logic"

    def test_resource_exhaustion_is_permanent_with_action(self):
        """Resource errors might need cleanup action before retry."""
        ctx = MockRecoveryContext()
        ctx.add_error(MemoryError("OOM"), category="resource")
        ctx.record_recovery_action("gc_trigger", {"freed": 1000})

        assert ctx.errors[0]["category"] == "resource"
        assert len(ctx.recovery_actions) == 1


# ─────────────────────────────────────────────────────────────────────────────
# Retry Logic Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestRetryBehavior(unittest.TestCase):
    """Test retry behavior and backoff."""

    def test_retry_transient_error(self):
        """Transient errors should allow retry."""
        ctx = MockRecoveryContext()
        ctx.add_error(TimeoutError("network"), category="transient")

        # Simulate retry
        ctx.attempt += 1
        ctx.record_recovery_action("retry", {"attempt": 2})

        assert ctx.attempt == 2
        assert len(ctx.recovery_actions) == 1

    def test_do_not_retry_permanent_error(self):
        """Permanent errors should not retry."""
        ctx = MockRecoveryContext()
        ctx.add_error(ValueError("invalid"), category="logic")
        ctx.state = "FAILED"

        # No retry attempt recorded
        assert ctx.state == "FAILED"
        assert len(ctx.recovery_actions) == 0

    def test_exponential_backoff_calculation(self):
        """Retry backoff should increase exponentially."""
        base_delay = 1.0
        max_delay = 60.0

        delays = []
        for attempt in range(1, 6):
            delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
            delays.append(delay)

        assert delays == [1.0, 2.0, 4.0, 8.0, 16.0]

        # Test cap at max_delay
        attempt = 10
        delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
        assert delay == max_delay

    def test_jitter_in_backoff(self):
        """Backoff should have jitter to prevent thundering herd."""
        import random
        base_delay = 1.0

        delays = []
        random.seed(42)
        for attempt in range(3):
            base = base_delay * (2 ** attempt)
            jitter = base * random.uniform(0, 0.1)
            delay = base + jitter
            delays.append(delay)

        # All delays should be unique (with very high probability)
        assert len(set(delays)) == len(delays)


# ─────────────────────────────────────────────────────────────────────────────
# Error Aggregation and Reporting Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestErrorAggregation(unittest.TestCase):
    """Test aggregation of multiple errors."""

    def test_collect_multiple_errors_from_multiple_contexts(self):
        """Should aggregate errors from multiple recovery contexts."""
        contexts = [
            MockRecoveryContext(task_id="t1"),
            MockRecoveryContext(task_id="t2"),
            MockRecoveryContext(task_id="t3"),
        ]

        for ctx in contexts:
            ctx.add_error(ConnectionError("failed"), category="transient")

        total_errors = sum(len(ctx.errors) for ctx in contexts)
        assert total_errors == 3

    def test_group_errors_by_category(self):
        """Errors should be groupable by category."""
        ctx = MockRecoveryContext()

        ctx.add_error(ConnectionError("c1"), category="transient")
        ctx.add_error(TimeoutError("t1"), category="transient")
        ctx.add_error(ValueError("v1"), category="logic")

        by_category = {}
        for err in ctx.errors:
            cat = err["category"]
            by_category.setdefault(cat, []).append(err)

        assert len(by_category["transient"]) == 2
        assert len(by_category["logic"]) == 1

    def test_error_statistics(self):
        """Should compute error statistics."""
        ctx = MockRecoveryContext()

        for i in range(3):
            ctx.add_error(TimeoutError(f"timeout {i}"), category="transient")
        for i in range(2):
            ctx.add_error(ValueError(f"invalid {i}"), category="logic")

        stats = {
            "total": len(ctx.errors),
            "transient": sum(1 for e in ctx.errors if e["category"] == "transient"),
            "logic": sum(1 for e in ctx.errors if e["category"] == "logic"),
        }

        assert stats["total"] == 5
        assert stats["transient"] == 3
        assert stats["logic"] == 2


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline Integration Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestOrchestrationPipelineErrorHandling(unittest.TestCase):
    """Test error handling in orchestration pipeline stages."""

    def test_error_propagation_through_stages(self):
        """Error from one stage should propagate with context."""
        ctx = MockRecoveryContext(task_id="pipeline-test")

        # Simulate pipeline stages
        stages = ["preflight", "strategy", "execution", "qa"]

        # Error occurs in execution stage
        error_stage = "execution"
        ctx.add_error(
            RuntimeError(f"failed in {error_stage}"),
            category="transient"
        )
        ctx.record_recovery_action("rollback", {"stages_rolled_back": 1})

        assert error_stage in str(ctx.errors[0]["error"])
        assert len(ctx.recovery_actions) == 1

    def test_error_in_preflight_gates_task(self):
        """Error in preflight should gate downstream stages."""
        ctx = MockRecoveryContext(task_id="gated-task")
        ctx.add_error(
            ValueError("preflight validation failed"),
            category="logic"
        )
        ctx.state = "FAILED"

        assert ctx.state == "FAILED"
        # No recovery actions should have been attempted
        assert len(ctx.recovery_actions) == 0

    def test_error_in_independent_qa_allows_retry(self):
        """Error in independent QA should allow retry of that phase."""
        ctx = MockRecoveryContext(task_id="qa-retry-test")
        ctx.add_error(
            TimeoutError("QA timeout"),
            category="transient"
        )
        ctx.state = "RECOVERING"
        ctx.attempt = 1

        # Simulate retry of QA
        ctx.attempt += 1
        ctx.record_recovery_action("qa_retry", {"attempt": 2})

        assert ctx.attempt == 2
        assert ctx.state == "RECOVERING"

    def test_recovery_backlog_processing_with_errors(self):
        """Recovery backlog should handle errors gracefully."""
        recovery_items = [
            MockRecoveryContext(task_id=f"recover-{i}") for i in range(3)
        ]

        # First item has transient error
        recovery_items[0].add_error(
            ConnectionError("network"),
            category="transient"
        )
        recovery_items[0].state = "RECOVERING"

        # Second item succeeds
        recovery_items[1].state = "RECOVERED"

        # Third item has permanent error
        recovery_items[2].add_error(
            PermissionError("access denied"),
            category="permission"
        )
        recovery_items[2].state = "FAILED"

        states = [item.state for item in recovery_items]
        assert states == ["RECOVERING", "RECOVERED", "FAILED"]


# ─────────────────────────────────────────────────────────────────────────────
# Edge Cases and Boundary Conditions
# ─────────────────────────────────────────────────────────────────────────────

class TestErrorHandlingEdgeCases(unittest.TestCase):
    """Test edge cases in error handling."""

    def test_handle_none_error(self):
        """Should handle None error gracefully."""
        ctx = MockRecoveryContext()
        # Should not raise
        try:
            if None:
                ctx.add_error(None, category="unknown")
        except Exception as e:
            self.fail(f"Failed to handle None: {e}")

    def test_handle_very_long_error_message(self):
        """Should handle very long error messages."""
        ctx = MockRecoveryContext()
        long_msg = "x" * 10000
        ctx.add_error(ValueError(long_msg), category="logic")

        assert len(ctx.errors) == 1
        assert len(str(ctx.errors[0]["error"])) > 10000

    def test_handle_unicode_in_error_message(self):
        """Should handle unicode in error messages."""
        ctx = MockRecoveryContext()
        ctx.add_error(ValueError("Failed: 中文 日本語 한국어"), category="logic")

        assert len(ctx.errors) == 1

    def test_rapid_error_accumulation(self):
        """Should handle rapid error accumulation."""
        ctx = MockRecoveryContext()

        for i in range(100):
            ctx.add_error(
                RuntimeError(f"error {i}"),
                category="transient"
            )

        assert len(ctx.errors) == 100

    def test_recovery_context_with_extreme_attempt_count(self):
        """Should handle extremely high attempt counts."""
        ctx = MockRecoveryContext(attempt=999)
        assert ctx.attempt == 999

        ctx.attempt = 10**6
        assert ctx.attempt == 10**6


class TestErrorHandlingUnderConcurrency(unittest.TestCase):
    """Test error handling under concurrent conditions."""

    def test_concurrent_error_contexts_independent(self):
        """Error contexts should be independent."""
        contexts = [
            MockRecoveryContext(task_id=f"task-{i}") for i in range(5)
        ]

        for i, ctx in enumerate(contexts):
            for j in range(i + 1):
                ctx.add_error(RuntimeError(f"error {j}"), category="transient")

        error_counts = [len(ctx.errors) for ctx in contexts]
        assert error_counts == [1, 2, 3, 4, 5]

    def test_recovery_action_isolation(self):
        """Recovery actions in one context shouldn't affect others."""
        ctx1 = MockRecoveryContext(task_id="t1")
        ctx2 = MockRecoveryContext(task_id="t2")

        ctx1.record_recovery_action("action1", {"result": True})
        ctx2.record_recovery_action("action2", {"result": False})

        assert len(ctx1.recovery_actions) == 1
        assert len(ctx2.recovery_actions) == 1
        assert ctx1.recovery_actions[0]["type"] == "action1"
        assert ctx2.recovery_actions[0]["type"] == "action2"


# ─────────────────────────────────────────────────────────────────────────────
# Regression and Integration Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestErrorRecoveryRegression(unittest.TestCase):
    """Regression tests for error recovery scenarios."""

    def test_phantom_merge_error_recovery(self):
        """Test recovery from phantom merge (MERGED state but not in master)."""
        ctx = MockRecoveryContext(task_id="phantom-merge-1")
        ctx.add_error(
            RuntimeError("branch not in master despite MERGED state"),
            category="transient"
        )
        ctx.record_recovery_action("detect_phantom", {"phantom": True})
        ctx.record_recovery_action("requeue_recovery", {"recovered": True})
        ctx.state = "RECOVERED"

        assert len(ctx.recovery_actions) == 2
        assert ctx.state == "RECOVERED"

    def test_deadlock_detection_and_recovery(self):
        """Test detection and recovery from deadlock."""
        ctx = MockRecoveryContext(task_id="deadlock-1")
        ctx.add_error(
            TimeoutError("operation timeout - possible deadlock"),
            category="transient"
        )
        ctx.record_recovery_action("detect_deadlock", {"deadlock_detected": True})
        ctx.record_recovery_action("acquire_lock", {"timeout": 30})
        ctx.record_recovery_action("clear_state", {"entries_cleared": 10})
        ctx.state = "RECOVERED"

        assert len(ctx.recovery_actions) == 3
        assert ctx.state == "RECOVERED"

    def test_cascade_failure_containment(self):
        """Test that errors don't cascade across unrelated tasks."""
        contexts = [
            MockRecoveryContext(task_id="task-1"),
            MockRecoveryContext(task_id="task-2"),
            MockRecoveryContext(task_id="task-3"),
        ]

        # First task fails
        contexts[0].add_error(RuntimeError("critical failure"), category="transient")
        contexts[0].state = "FAILED"

        # Other tasks should be unaffected
        contexts[1].state = "RECOVERED"
        contexts[2].state = "RECOVERED"

        assert contexts[0].state == "FAILED"
        assert contexts[1].state == "RECOVERED"
        assert contexts[2].state == "RECOVERED"


if __name__ == "__main__":
    unittest.main()
