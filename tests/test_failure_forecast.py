"""Tests for failure_forecast.should_skip — mock the DB."""

import sys
import os
import types

# Ensure runner/ is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "runner"))

# Create a mock db module so failure_forecast can import it at module level
mock_db_module = types.ModuleType("db")
mock_db_module.select = lambda *a, **kw: []
sys.modules["db"] = mock_db_module

import failure_forecast  # noqa: E402


class MockDB:
    """Injectable mock for the db module."""
    def __init__(self, task_row, history_rows):
        self._task_row = task_row
        self._history_rows = history_rows

    def select(self, table, params):
        if params.get("id"):
            return [self._task_row] if self._task_row else []
        return self._history_rows


def test_three_consecutive_failures_returns_true():
    """3 consecutive failures -> True"""
    mock = MockDB(
        task_row={"slug": "my-task", "project_id": "proj-1"},
        history_rows=[
            {"state": "BLOCKED", "updated_at": "2025-01-03"},
            {"state": "FAILED", "updated_at": "2025-01-02"},
            {"state": "ERROR", "updated_at": "2025-01-01"},
        ],
    )
    assert failure_forecast.should_skip("task-1", _db=mock) is True


def test_two_consecutive_failures_returns_false():
    """2 consecutive failures -> False"""
    mock = MockDB(
        task_row={"slug": "my-task", "project_id": "proj-1"},
        history_rows=[
            {"state": "BLOCKED", "updated_at": "2025-01-02"},
            {"state": "ERROR", "updated_at": "2025-01-01"},
        ],
    )
    assert failure_forecast.should_skip("task-1", _db=mock) is False


def test_three_failures_then_success_returns_false():
    """3 failures then 1 success -> False (success resets streak)"""
    mock = MockDB(
        task_row={"slug": "my-task", "project_id": "proj-1"},
        history_rows=[
            {"state": "DONE", "updated_at": "2025-01-04"},
            {"state": "BLOCKED", "updated_at": "2025-01-03"},
            {"state": "FAILED", "updated_at": "2025-01-02"},
            {"state": "ERROR", "updated_at": "2025-01-01"},
        ],
    )
    assert failure_forecast.should_skip("task-1", _db=mock) is False


if __name__ == "__main__":
    test_three_consecutive_failures_returns_true()
    test_two_consecutive_failures_returns_false()
    test_three_failures_then_success_returns_false()
    print("All tests passed.")
