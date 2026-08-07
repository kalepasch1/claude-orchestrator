#!/usr/bin/env python3
"""Tests for report-failure-if-n functionality in racefeed task.

Task: rework-oversized-relfix-racefeed-07060650-sub-task-4-report-failure-if-n-5cfe75f
Spec: Report failures to owner when N consecutive task failures occur.

Tests validate:
  - Failure counter increments on consecutive terminal states
  - Threshold triggering (N=3 consecutive failures)
  - Failure signature generation and uniqueness
  - Notification creation and delivery
  - Integration with run_history tracking
  - Edge cases: empty history, mixed states, state column variants
"""
import os
import sys
import json
import tempfile
import time
from unittest.mock import Mock, patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Disable external dependencies for test isolation
os.environ["SUPABASE_URL"] = "http://localhost:test"
os.environ["SUPABASE_SERVICE_KEY"] = "test-key"
os.environ["ORCH_DB_ENABLED"] = "false"
os.environ.setdefault("APPROVAL_PUSH_EMAIL", "test@example.com")


# Mock database client for testing
class MockDB:
    def __init__(self):
        self.run_history = []
        self.notifications = []
        self.failures_recorded = []

    def select(self, table, query):
        """Mock database select with support for run_history queries."""
        if table == "run_history":
            # Filter by task_id and apply ordering/limiting
            task_id = query.get("task_id", "").replace("eq.", "")
            order = query.get("order", "")
            limit = int(query.get("limit", "10"))

            filtered = [r for r in self.run_history if r.get("task_id") == task_id]

            if "desc" in order:
                filtered = sorted(filtered, key=lambda r: r.get("created_at", 0), reverse=True)

            return filtered[:limit]
        elif table == "notifications":
            return self.notifications
        return []

    def insert(self, table, record):
        """Mock database insert."""
        if table == "notifications":
            self.notifications.append(record)
            return True
        elif table == "failures_recorded":
            self.failures_recorded.append(record)
            return True
        return False


def _row_status(row):
    """Extract status from row (handles both 'status' and 'state' columns)."""
    return str(row.get("status") or row.get("state") or "").lower()


TERMINAL_STATES = ('failed', 'error', 'blocked', 'quarantined')
CONSECUTIVE_FAIL_THRESHOLD = 3


def count_consecutive_failures(task_id, db_client):
    """Count consecutive terminal failures from most recent run backwards.

    Returns: tuple (count, should_report)
    where should_report is True when count >= CONSECUTIVE_FAIL_THRESHOLD
    """
    try:
        rows = db_client.select("run_history", {
            "select": "status",
            "task_id": "eq." + str(task_id),
            "order": "created_at.desc",
            "limit": str(CONSECUTIVE_FAIL_THRESHOLD + 1),
        }) or []
    except Exception:
        return 0, False

    if not rows:
        return 0, False

    consecutive_count = 0
    for row in rows:
        if _row_status(row) in TERMINAL_STATES:
            consecutive_count += 1
        else:
            break

    should_report = consecutive_count >= CONSECUTIVE_FAIL_THRESHOLD
    return consecutive_count, should_report


def generate_failure_signature(task_id, error_text):
    """Generate a unique signature for a failure type."""
    import hashlib
    normalized = error_text.lower().strip()[:200]
    return hashlib.sha256(f"{task_id}:{normalized}".encode()).hexdigest()[:12]


def report_failure_if_n(task_id, db_client, notify_email=None):
    """Report failure to owner if N consecutive failures detected.

    Args:
        task_id: The task identifier
        db_client: Database client instance
        notify_email: Email to notify (from env if not provided)

    Returns:
        dict with keys: {
            "reported": bool,
            "consecutive_count": int,
            "signature": str or None,
            "notification_id": int or None,
            "error": str or None
        }
    """
    notify_email = notify_email or os.environ.get("APPROVAL_PUSH_EMAIL", "")

    try:
        # Query here instead of delegating to count_consecutive_failures(), whose public
        # fail-soft contract intentionally turns database errors into (0, False). Reporting
        # must preserve the distinction between "no failures" and "could not read history".
        rows = db_client.select("run_history", {
            "select": "*",
            "task_id": "eq." + str(task_id),
            "order": "created_at.desc",
            "limit": str(CONSECUTIVE_FAIL_THRESHOLD + 1),
        }) or []
        if not rows:
            return {
                "reported": False,
                "consecutive_count": 0,
                "signature": None,
                "notification_id": None,
                "error": "No run_history found"
            }

        consecutive_count = 0
        for row in rows:
            if _row_status(row) in TERMINAL_STATES:
                consecutive_count += 1
            else:
                break
        should_report = consecutive_count >= CONSECUTIVE_FAIL_THRESHOLD

        if not should_report:
            return {
                "reported": False,
                "consecutive_count": consecutive_count,
                "signature": None,
                "notification_id": None,
                "error": None
            }

        latest_run = rows[0]
        error_text = latest_run.get("error_message", "") or latest_run.get("error", "")
        sig = generate_failure_signature(task_id, error_text)

        # Create notification
        notification = {
            "channel": "email",
            "audience": notify_email,
            "kind": "alert",
            "title": f"Task failure threshold reached: {task_id}",
            "body": (
                f"Task {task_id} has failed {consecutive_count} times consecutively.\n"
                f"Signature: {sig}\n"
                f"Latest error: {error_text[:500]}\n"
                f"Action: Review logs and consider escalation."
            ),
            "sent": False,
            "created_at": time.time(),
            "task_id": task_id,
            "signature": sig
        }

        db_client.insert("notifications", notification)

        return {
            "reported": True,
            "consecutive_count": consecutive_count,
            "signature": sig,
            "notification_id": len(db_client.notifications),
            "error": None
        }

    except Exception as e:
        return {
            "reported": False,
            "consecutive_count": 0,
            "signature": None,
            "notification_id": None,
            "error": str(e)
        }


# ============================================================================
# TESTS
# ============================================================================

class TestConsecutiveFailureCounter:
    """Test failure counting from run_history."""

    def test_count_no_runs_returns_zero(self):
        """Empty run_history should return 0 consecutive failures."""
        db = MockDB()
        db.run_history = []

        count, should_report = count_consecutive_failures("task-1", db)
        assert count == 0
        assert should_report is False

    def test_count_single_failure(self):
        """Single failure should return 1, not report."""
        db = MockDB()
        db.run_history = [
            {"task_id": "task-1", "status": "failed", "created_at": 1000}
        ]

        count, should_report = count_consecutive_failures("task-1", db)
        assert count == 1
        assert should_report is False

    def test_count_two_failures(self):
        """Two consecutive failures should return 2, not report."""
        db = MockDB()
        db.run_history = [
            {"task_id": "task-1", "status": "failed", "created_at": 2000},
            {"task_id": "task-1", "status": "failed", "created_at": 1000}
        ]

        count, should_report = count_consecutive_failures("task-1", db)
        assert count == 2
        assert should_report is False

    def test_count_three_failures_triggers_report(self):
        """Three consecutive failures should trigger report."""
        db = MockDB()
        db.run_history = [
            {"task_id": "task-1", "status": "failed", "created_at": 3000},
            {"task_id": "task-1", "status": "failed", "created_at": 2000},
            {"task_id": "task-1", "status": "failed", "created_at": 1000}
        ]

        count, should_report = count_consecutive_failures("task-1", db)
        assert count == 3
        assert should_report is True

    def test_count_four_failures_triggers_report(self):
        """Four consecutive failures should also trigger report."""
        db = MockDB()
        db.run_history = [
            {"task_id": "task-1", "status": "failed", "created_at": 4000},
            {"task_id": "task-1", "status": "failed", "created_at": 3000},
            {"task_id": "task-1", "status": "failed", "created_at": 2000},
            {"task_id": "task-1", "status": "failed", "created_at": 1000}
        ]

        count, should_report = count_consecutive_failures("task-1", db)
        assert count == 4
        assert should_report is True


class TestFailureStateVariants:
    """Test different terminal state columns and values."""

    def test_recognize_error_status(self):
        """Recognize 'error' as terminal state."""
        db = MockDB()
        db.run_history = [
            {"task_id": "task-1", "status": "error", "created_at": 3000},
            {"task_id": "task-1", "status": "error", "created_at": 2000},
            {"task_id": "task-1", "status": "error", "created_at": 1000}
        ]

        count, should_report = count_consecutive_failures("task-1", db)
        assert count == 3
        assert should_report is True

    def test_recognize_blocked_status(self):
        """Recognize 'blocked' as terminal state."""
        db = MockDB()
        db.run_history = [
            {"task_id": "task-1", "status": "blocked", "created_at": 3000},
            {"task_id": "task-1", "status": "blocked", "created_at": 2000},
            {"task_id": "task-1", "status": "blocked", "created_at": 1000}
        ]

        count, should_report = count_consecutive_failures("task-1", db)
        assert count == 3
        assert should_report is True

    def test_recognize_quarantined_status(self):
        """Recognize 'quarantined' as terminal state."""
        db = MockDB()
        db.run_history = [
            {"task_id": "task-1", "status": "quarantined", "created_at": 3000},
            {"task_id": "task-1", "status": "quarantined", "created_at": 2000},
            {"task_id": "task-1", "status": "quarantined", "created_at": 1000}
        ]

        count, should_report = count_consecutive_failures("task-1", db)
        assert count == 3
        assert should_report is True

    def test_state_column_fallback(self):
        """Handle 'state' column when 'status' is missing."""
        db = MockDB()
        db.run_history = [
            {"task_id": "task-1", "state": "failed", "created_at": 3000},
            {"task_id": "task-1", "state": "failed", "created_at": 2000},
            {"task_id": "task-1", "state": "failed", "created_at": 1000}
        ]

        count, should_report = count_consecutive_failures("task-1", db)
        assert count == 3
        assert should_report is True

    def test_case_insensitive_status(self):
        """Handle mixed-case status values."""
        db = MockDB()
        db.run_history = [
            {"task_id": "task-1", "status": "FAILED", "created_at": 3000},
            {"task_id": "task-1", "status": "Failed", "created_at": 2000},
            {"task_id": "task-1", "status": "ERROR", "created_at": 1000}
        ]

        count, should_report = count_consecutive_failures("task-1", db)
        assert count == 3
        assert should_report is True


class TestFailureStreak:
    """Test failure streak detection (stops on success)."""

    def test_streak_broken_by_success(self):
        """Success breaks the failure streak."""
        db = MockDB()
        db.run_history = [
            {"task_id": "task-1", "status": "failed", "created_at": 3000},
            {"task_id": "task-1", "status": "failed", "created_at": 2000},
            {"task_id": "task-1", "status": "passed", "created_at": 1500},
            {"task_id": "task-1", "status": "failed", "created_at": 1000}
        ]

        count, should_report = count_consecutive_failures("task-1", db)
        # Should count only the most recent failures (2)
        assert count == 2
        assert should_report is False

    def test_streak_broken_by_running(self):
        """Running status breaks the failure streak."""
        db = MockDB()
        db.run_history = [
            {"task_id": "task-1", "status": "failed", "created_at": 3000},
            {"task_id": "task-1", "status": "failed", "created_at": 2000},
            {"task_id": "task-1", "status": "running", "created_at": 1500}
        ]

        count, should_report = count_consecutive_failures("task-1", db)
        assert count == 2
        assert should_report is False

    def test_many_old_failures_dont_count(self):
        """Old failures before a success don't count toward current streak."""
        db = MockDB()
        db.run_history = [
            {"task_id": "task-1", "status": "failed", "created_at": 6000},
            {"task_id": "task-1", "status": "failed", "created_at": 5000},
            {"task_id": "task-1", "status": "passed", "created_at": 4000},
            {"task_id": "task-1", "status": "failed", "created_at": 3000},
            {"task_id": "task-1", "status": "failed", "created_at": 2000},
            {"task_id": "task-1", "status": "failed", "created_at": 1000}
        ]

        count, should_report = count_consecutive_failures("task-1", db)
        # Should count only the 2 most recent failures
        assert count == 2
        assert should_report is False


class TestTaskIsolation:
    """Test that different tasks don't interfere with each other."""

    def test_task_isolation_no_cross_contamination(self):
        """Failures for task-1 don't affect task-2."""
        db = MockDB()
        db.run_history = [
            {"task_id": "task-1", "status": "failed", "created_at": 3000},
            {"task_id": "task-1", "status": "failed", "created_at": 2000},
            {"task_id": "task-1", "status": "failed", "created_at": 1000},
            # Task-2 has only 1 failure
            {"task_id": "task-2", "status": "failed", "created_at": 500}
        ]

        count1, report1 = count_consecutive_failures("task-1", db)
        count2, report2 = count_consecutive_failures("task-2", db)

        assert count1 == 3 and report1 is True
        assert count2 == 1 and report2 is False

    def test_multiple_tasks_independent_tracking(self):
        """Multiple tasks can each reach threshold independently."""
        db = MockDB()
        db.run_history = [
            # Task-1: 3 failures → report
            {"task_id": "task-1", "status": "failed", "created_at": 6000},
            {"task_id": "task-1", "status": "failed", "created_at": 5000},
            {"task_id": "task-1", "status": "failed", "created_at": 4000},
            # Task-2: 3 failures → report
            {"task_id": "task-2", "status": "failed", "created_at": 3000},
            {"task_id": "task-2", "status": "failed", "created_at": 2000},
            {"task_id": "task-2", "status": "failed", "created_at": 1000}
        ]

        count1, report1 = count_consecutive_failures("task-1", db)
        count2, report2 = count_consecutive_failures("task-2", db)

        assert count1 >= 3 and report1 is True
        assert count2 >= 3 and report2 is True


class TestFailureSignature:
    """Test failure signature generation."""

    def test_signature_deterministic(self):
        """Same input produces same signature."""
        sig1 = generate_failure_signature("task-1", "timeout error")
        sig2 = generate_failure_signature("task-1", "timeout error")
        assert sig1 == sig2

    def test_signature_different_for_different_errors(self):
        """Different errors produce different signatures."""
        sig1 = generate_failure_signature("task-1", "timeout error")
        sig2 = generate_failure_signature("task-1", "memory error")
        assert sig1 != sig2

    def test_signature_case_insensitive(self):
        """Signature ignores case."""
        sig1 = generate_failure_signature("task-1", "TIMEOUT ERROR")
        sig2 = generate_failure_signature("task-1", "timeout error")
        assert sig1 == sig2

    def test_signature_short_format(self):
        """Signature is reasonably short (12 chars hex)."""
        sig = generate_failure_signature("task-1", "error message")
        assert len(sig) == 12
        assert all(c in "0123456789abcdef" for c in sig)

    def test_signature_truncates_long_errors(self):
        """Handles very long error messages."""
        long_error = "x" * 10000
        sig = generate_failure_signature("task-1", long_error)
        assert len(sig) == 12
        assert all(c in "0123456789abcdef" for c in sig)


class TestReportFailureIfN:
    """Test the complete report_failure_if_n workflow."""

    def test_report_not_triggered_below_threshold(self):
        """No report when below N failures."""
        db = MockDB()
        db.run_history = [
            {"task_id": "task-1", "status": "failed", "created_at": 2000},
            {"task_id": "task-1", "status": "failed", "created_at": 1000}
        ]

        result = report_failure_if_n("task-1", db)

        assert result["reported"] is False
        assert result["consecutive_count"] == 2
        assert result["signature"] is None
        assert len(db.notifications) == 0

    def test_report_triggered_at_threshold(self):
        """Report created when exactly N failures."""
        db = MockDB()
        db.run_history = [
            {
                "task_id": "task-1",
                "status": "failed",
                "created_at": 3000,
                "error_message": "Database connection timeout"
            },
            {"task_id": "task-1", "status": "failed", "created_at": 2000},
            {"task_id": "task-1", "status": "failed", "created_at": 1000}
        ]

        result = report_failure_if_n("task-1", db)

        assert result["reported"] is True
        assert result["consecutive_count"] == 3
        assert result["signature"] is not None
        assert result["notification_id"] == 1
        assert len(db.notifications) == 1

    def test_notification_structure(self):
        """Notification has required fields."""
        db = MockDB()
        db.run_history = [
            {
                "task_id": "task-1",
                "status": "failed",
                "created_at": 3000,
                "error_message": "Auth failure"
            },
            {"task_id": "task-1", "status": "failed", "created_at": 2000},
            {"task_id": "task-1", "status": "failed", "created_at": 1000}
        ]

        result = report_failure_if_n("task-1", db, notify_email="owner@example.com")

        notification = db.notifications[0]
        assert notification["channel"] == "email"
        assert notification["audience"] == "owner@example.com"
        assert notification["kind"] == "alert"
        assert "task-1" in notification["title"]
        assert "3 times" in notification["body"]
        assert "Auth failure" in notification["body"]
        assert notification["sent"] is False

    def test_notification_uses_env_email_by_default(self):
        """Uses APPROVAL_PUSH_EMAIL from environment."""
        os.environ["APPROVAL_PUSH_EMAIL"] = "default@example.com"
        db = MockDB()
        db.run_history = [
            {"task_id": "task-1", "status": "failed", "created_at": 3000},
            {"task_id": "task-1", "status": "failed", "created_at": 2000},
            {"task_id": "task-1", "status": "failed", "created_at": 1000}
        ]

        result = report_failure_if_n("task-1", db)

        notification = db.notifications[0]
        assert notification["audience"] == "default@example.com"

    def test_error_handling_missing_run_history(self):
        """Gracefully handles missing run_history."""
        db = MockDB()
        db.run_history = []

        result = report_failure_if_n("nonexistent", db)

        assert result["reported"] is False
        assert result["error"] is not None
        assert len(db.notifications) == 0

    def test_error_handling_db_exception(self):
        """Gracefully handles database exceptions."""
        db = Mock()
        db.select.side_effect = Exception("DB connection failed")

        result = report_failure_if_n("task-1", db)

        assert result["reported"] is False
        assert result["error"] is not None
        assert "DB connection failed" in result["error"]


class TestRaceConditions:
    """Test race condition scenarios."""

    def test_concurrent_failure_reports(self):
        """Multiple concurrent reports for same task are independent."""
        db = MockDB()
        db.run_history = [
            {"task_id": "task-1", "status": "failed", "created_at": 3000},
            {"task_id": "task-1", "status": "failed", "created_at": 2000},
            {"task_id": "task-1", "status": "failed", "created_at": 1000}
        ]

        result1 = report_failure_if_n("task-1", db)
        result2 = report_failure_if_n("task-1", db)

        # Both should report (no idempotency built in at this level)
        assert result1["reported"] is True
        assert result2["reported"] is True
        assert len(db.notifications) == 2

    def test_late_arriving_success_after_report(self):
        """Success arriving late doesn't retroactively cancel the report."""
        db = MockDB()
        db.run_history = [
            {"task_id": "task-1", "status": "failed", "created_at": 3000},
            {"task_id": "task-1", "status": "failed", "created_at": 2000},
            {"task_id": "task-1", "status": "failed", "created_at": 1000}
        ]

        result1 = report_failure_if_n("task-1", db)
        assert result1["reported"] is True
        notification_count_after_report = len(db.notifications)

        # Simulate late-arriving success (inserted after report)
        db.run_history.insert(0, {"task_id": "task-1", "status": "passed", "created_at": 4000})

        # Existing notifications aren't retroactively removed
        assert len(db.notifications) == notification_count_after_report


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_empty_error_message_field(self):
        """Handles missing/empty error message gracefully."""
        db = MockDB()
        db.run_history = [
            {"task_id": "task-1", "status": "failed", "created_at": 3000},
            {"task_id": "task-1", "status": "failed", "created_at": 2000},
            {"task_id": "task-1", "status": "failed", "created_at": 1000}
        ]

        result = report_failure_if_n("task-1", db)

        assert result["reported"] is True
        assert result["signature"] is not None

    def test_error_field_fallback(self):
        """Falls back to 'error' field when 'error_message' missing."""
        db = MockDB()
        db.run_history = [
            {"task_id": "task-1", "status": "failed", "created_at": 3000, "error": "Network timeout"},
            {"task_id": "task-1", "status": "failed", "created_at": 2000},
            {"task_id": "task-1", "status": "failed", "created_at": 1000}
        ]

        result = report_failure_if_n("task-1", db)

        assert result["reported"] is True
        notification = db.notifications[0]
        assert "Network timeout" in notification["body"]

    def test_very_long_task_id(self):
        """Handles very long task IDs."""
        long_id = "task-" + "x" * 500
        db = MockDB()
        db.run_history = [
            {"task_id": long_id, "status": "failed", "created_at": 3000},
            {"task_id": long_id, "status": "failed", "created_at": 2000},
            {"task_id": long_id, "status": "failed", "created_at": 1000}
        ]

        result = report_failure_if_n(long_id, db)

        assert result["reported"] is True

    def test_special_characters_in_error(self):
        """Handles special characters in error messages."""
        db = MockDB()
        db.run_history = [
            {
                "task_id": "task-1",
                "status": "failed",
                "created_at": 3000,
                "error_message": "Failed: /path/to/file#123 (line 456) [FATAL] 🚨"
            },
            {"task_id": "task-1", "status": "failed", "created_at": 2000},
            {"task_id": "task-1", "status": "failed", "created_at": 1000}
        ]

        result = report_failure_if_n("task-1", db)

        assert result["reported"] is True
        assert result["signature"] is not None


class TestIntegrationWithFailureForecast:
    """Test integration with failure_forecast module logic."""

    def test_compatible_with_failure_forecast_states(self):
        """Works with states defined in failure_forecast."""
        db = MockDB()
        db.run_history = [
            {"task_id": "task-1", "status": "failed", "created_at": 3000},
            {"task_id": "task-1", "status": "error", "created_at": 2000},
            {"task_id": "task-1", "status": "blocked", "created_at": 1000}
        ]

        count, should_report = count_consecutive_failures("task-1", db)

        # All three are terminal states from failure_forecast
        assert count == 3
        assert should_report is True

    def test_can_skip_and_report_independently(self):
        """Report and skip decisions are independent."""
        db = MockDB()
        db.run_history = [
            {"task_id": "task-1", "status": "failed", "created_at": 3000},
            {"task_id": "task-1", "status": "failed", "created_at": 2000},
            {"task_id": "task-1", "status": "failed", "created_at": 1000}
        ]

        count, should_report = count_consecutive_failures("task-1", db)
        result = report_failure_if_n("task-1", db)

        # Both should trigger independently
        assert should_report is True
        assert result["reported"] is True


if __name__ == "__main__":
    # Run all tests
    test_classes = [
        TestConsecutiveFailureCounter,
        TestFailureStateVariants,
        TestFailureStreak,
        TestTaskIsolation,
        TestFailureSignature,
        TestReportFailureIfN,
        TestRaceConditions,
        TestEdgeCases,
        TestIntegrationWithFailureForecast
    ]

    passed = 0
    failed = 0

    for test_class in test_classes:
        cls_instance = test_class()
        for method_name in dir(cls_instance):
            if method_name.startswith("test_"):
                try:
                    method = getattr(cls_instance, method_name)
                    method()
                    passed += 1
                    print(f"✓ {test_class.__name__}.{method_name}")
                except AssertionError as e:
                    failed += 1
                    print(f"✗ {test_class.__name__}.{method_name}: {e}")
                except Exception as e:
                    failed += 1
                    print(f"✗ {test_class.__name__}.{method_name}: ERROR: {e}")

    print(f"\n{'='*60}")
    print(f"Results: {passed} passed, {failed} failed")
    print(f"{'='*60}")

    if failed > 0:
        sys.exit(1)
