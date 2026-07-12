#!/usr/bin/env python3
"""Tests for monitoring_feedback.py"""
import datetime
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import monitoring_feedback as mf


class FakeDB:
    """Minimal mock for db module."""
    def __init__(self, select_result=None, fail_insert=False):
        self.inserted = []
        self._select_result = select_result or []
        self._fail_insert = fail_insert

    def insert(self, table, data):
        if self._fail_insert:
            raise RuntimeError("insert failed")
        self.inserted.append((table, data))

    def select(self, table, params):
        return self._select_result


class TestRecordStateChange(unittest.TestCase):
    def test_basic_insert(self):
        db = FakeDB()
        ok = mf.record_state_change(db, "t1", "QUEUED", "RUNNING", account="exec-1")
        self.assertTrue(ok)
        self.assertEqual(len(db.inserted), 1)
        self.assertEqual(db.inserted[0][0], "monitoring_feed")
        self.assertEqual(db.inserted[0][1]["task_id"], "t1")
        self.assertEqual(db.inserted[0][1]["new_state"], "RUNNING")

    def test_detail_truncated(self):
        db = FakeDB()
        mf.record_state_change(db, "t1", "A", "B", detail="x" * 2000)
        self.assertLessEqual(len(db.inserted[0][1]["detail"]), 1000)

    def test_fail_soft(self):
        db = FakeDB(fail_insert=True)
        ok = mf.record_state_change(db, "t1", "A", "B")
        self.assertFalse(ok)

    def test_none_values(self):
        db = FakeDB()
        ok = mf.record_state_change(db, "t1", None, None)
        self.assertTrue(ok)
        self.assertEqual(db.inserted[0][1]["old_state"], "")


class TestGetRecentFeed(unittest.TestCase):
    def test_returns_rows(self):
        rows = [{"task_id": "t1", "new_state": "DONE"}]
        db = FakeDB(select_result=rows)
        result = mf.get_recent_feed(db, limit=10)
        self.assertEqual(len(result), 1)

    def test_empty_on_error(self):
        class BadDB:
            def select(self, *a, **kw):
                raise RuntimeError("fail")
        result = mf.get_recent_feed(BadDB())
        self.assertEqual(result, [])


class TestBuildSummary(unittest.TestCase):
    def test_counts_transitions(self):
        entries = [
            {"old_state": "QUEUED", "new_state": "RUNNING"},
            {"old_state": "QUEUED", "new_state": "RUNNING"},
            {"old_state": "RUNNING", "new_state": "DONE"},
        ]
        s = mf.build_summary(entries)
        self.assertEqual(s["QUEUED -> RUNNING"], 2)
        self.assertEqual(s["RUNNING -> DONE"], 1)

    def test_empty(self):
        self.assertEqual(mf.build_summary([]), {})

    def test_none(self):
        self.assertEqual(mf.build_summary(None), {})


if __name__ == "__main__":
    unittest.main()
