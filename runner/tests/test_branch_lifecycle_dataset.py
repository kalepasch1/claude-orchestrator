#!/usr/bin/env python3
"""Tests for branch_lifecycle_dataset.py"""
import datetime
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import branch_lifecycle_dataset as bld


class TestBuildDataset(unittest.TestCase):
    NOW = datetime.datetime(2026, 7, 11, 12, 0, 0)

    def _task(self, state, days_ago=1, pid="p1", tid="t1"):
        ts = (self.NOW - datetime.timedelta(days=days_ago)).isoformat()
        return {"id": tid, "project_id": pid, "state": state,
                "created_at": ts, "updated_at": ts}

    def test_running_labeled_needed(self):
        rows = bld.build_dataset([self._task("RUNNING")], now=self.NOW)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["label"], 1)
        self.assertEqual(rows[0]["task_state_running"], 1)

    def test_queued_labeled_needed(self):
        rows = bld.build_dataset([self._task("QUEUED")], now=self.NOW)
        self.assertEqual(rows[0]["label"], 1)
        self.assertEqual(rows[0]["task_state_queued"], 1)

    def test_merged_labeled_stale(self):
        rows = bld.build_dataset([self._task("MERGED")], now=self.NOW)
        self.assertEqual(rows[0]["label"], 0)

    def test_done_recent_labeled_needed(self):
        rows = bld.build_dataset([self._task("DONE", days_ago=2)], now=self.NOW)
        self.assertEqual(rows[0]["label"], 1)

    def test_done_old_labeled_stale(self):
        rows = bld.build_dataset([self._task("DONE", days_ago=10)], now=self.NOW)
        self.assertEqual(rows[0]["label"], 0)

    def test_quarantined_labeled_stale(self):
        rows = bld.build_dataset([self._task("QUARANTINED")], now=self.NOW)
        self.assertEqual(rows[0]["label"], 0)

    def test_blocked_recent_skipped(self):
        rows = bld.build_dataset([self._task("BLOCKED", days_ago=2)], now=self.NOW)
        self.assertEqual(len(rows), 0)  # ambiguous → None → skipped

    def test_blocked_old_labeled_stale(self):
        rows = bld.build_dataset([self._task("BLOCKED", days_ago=10)], now=self.NOW)
        self.assertEqual(rows[0]["label"], 0)

    def test_empty_tasks(self):
        self.assertEqual(bld.build_dataset([], now=self.NOW), [])

    def test_none_tasks(self):
        self.assertEqual(bld.build_dataset(None, now=self.NOW), [])

    def test_queue_depth_norm(self):
        rows = bld.build_dataset(
            [self._task("RUNNING", pid="p1")],
            queue_depths={"p1": 10},
            now=self.NOW,
        )
        self.assertAlmostEqual(rows[0]["project_queue_depth_norm"], 0.5)

    def test_queue_depth_capped(self):
        rows = bld.build_dataset(
            [self._task("RUNNING", pid="p1")],
            queue_depths={"p1": 100},
            now=self.NOW,
        )
        self.assertAlmostEqual(rows[0]["project_queue_depth_norm"], 1.0)

    def test_limit(self):
        tasks = [self._task("RUNNING", tid=f"t{i}") for i in range(10)]
        rows = bld.build_dataset(tasks, limit=3, now=self.NOW)
        self.assertEqual(len(rows), 3)


class TestLabel(unittest.TestCase):
    def test_active_states(self):
        for s in ("QUEUED", "RUNNING", "RETRY"):
            self.assertEqual(bld._label(s, 0), 1)

    def test_merged_always_stale(self):
        self.assertEqual(bld._label("MERGED", 0), 0)

    def test_unknown_state_skipped(self):
        self.assertIsNone(bld._label("UNKNOWN", 5))


if __name__ == "__main__":
    unittest.main()
