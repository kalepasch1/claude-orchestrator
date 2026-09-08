"""Tests for queue_state_monitor — queue state snapshots for sync monitoring."""
import os
import sys
import time
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import queue_state_monitor as qsm


class MockDB:
    """Fake db module for testing without a real database."""
    def __init__(self, responses=None):
        self.responses = responses or {}
        self.calls = []

    def execute_sql(self, query):
        self.calls.append(query)
        for key, val in self.responses.items():
            if key in query:
                return val
        return []


class TestSnapshotShape(unittest.TestCase):
    def test_returns_required_keys(self):
        snap = qsm.snapshot(db_module=MockDB())
        for key in ("by_state", "by_project", "zombie_candidates", "total", "ts"):
            self.assertIn(key, snap)

    def test_timestamp_is_recent(self):
        snap = qsm.snapshot(db_module=MockDB())
        self.assertAlmostEqual(snap["ts"], time.time(), delta=5)


class TestSnapshotWithData(unittest.TestCase):
    def test_state_distribution(self):
        db = MockDB(responses={
            "GROUP BY state": [
                {"state": "QUEUED", "cnt": 10},
                {"state": "RUNNING", "cnt": 3},
                {"state": "DONE", "cnt": 50},
            ],
        })
        snap = qsm.snapshot(db_module=db)
        self.assertEqual(snap["by_state"]["QUEUED"], 10)
        self.assertEqual(snap["by_state"]["RUNNING"], 3)
        self.assertEqual(snap["total"], 63)

    def test_zombie_count(self):
        db = MockDB(responses={
            "GROUP BY state": [],
            "RUNNING": [{"cnt": 2}],
        })
        snap = qsm.snapshot(db_module=db)
        self.assertEqual(snap["zombie_candidates"], 2)

    def test_project_breakdown(self):
        db = MockDB(responses={
            "GROUP BY state": [],
            "RUNNING": [{"cnt": 0}],
            "GROUP BY p.name": [
                {"name": "beethoven", "state": "QUEUED", "cnt": 5},
                {"name": "beethoven", "state": "DONE", "cnt": 10},
                {"name": "pareto-2080", "state": "QUEUED", "cnt": 3},
            ],
        })
        snap = qsm.snapshot(db_module=db)
        self.assertEqual(snap["by_project"]["beethoven"]["QUEUED"], 5)
        self.assertEqual(snap["by_project"]["pareto-2080"]["QUEUED"], 3)


class TestSnapshotFailSoft(unittest.TestCase):
    def test_no_db_module(self):
        snap = qsm.snapshot(db_module=None)
        self.assertEqual(snap["total"], 0)
        self.assertIsInstance(snap["by_state"], dict)

    def test_db_raises_exception(self):
        db = MagicMock()
        db.execute_sql.side_effect = RuntimeError("connection lost")
        snap = qsm.snapshot(db_module=db)
        self.assertEqual(snap["total"], 0)

    def test_partial_failure(self):
        """State query works, zombie query fails."""
        call_count = [0]
        def fake_sql(query):
            call_count[0] += 1
            if call_count[0] == 1:
                return [{"state": "QUEUED", "cnt": 5}]
            raise RuntimeError("timeout")
        db = MagicMock()
        db.execute_sql = fake_sql
        snap = qsm.snapshot(db_module=db)
        self.assertEqual(snap["by_state"]["QUEUED"], 5)
        self.assertEqual(snap["total"], 5)


if __name__ == "__main__":
    unittest.main()
