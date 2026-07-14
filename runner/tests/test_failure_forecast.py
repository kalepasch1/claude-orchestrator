"""Tests for failure_forecast.should_skip — mock the DB."""
import sys, os
# Ensure runner/ is on the path so failure_forecast can be imported
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from failure_forecast import should_skip


class MockDB:
    def __init__(self, rows):
        self._rows = rows
    def select(self, table, params):
        return self._rows


def test_three_consecutive_failures_returns_true():
    db = MockDB([
        {"status": "failed"},
        {"status": "error"},
        {"status": "failed"},
    ])
    assert should_skip("task-abc", db) is True


def test_two_consecutive_failures_returns_false():
    db = MockDB([
        {"status": "failed"},
        {"status": "error"},
    ])
    assert should_skip("task-abc", db) is False


def test_three_failures_then_one_success_returns_false():
    db = MockDB([
        {"status": "success"},
        {"status": "failed"},
        {"status": "failed"},
        {"status": "failed"},
    ])
    assert should_skip("task-abc", db) is False
