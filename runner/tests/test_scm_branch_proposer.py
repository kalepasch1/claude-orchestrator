#!/usr/bin/env python3
"""Tests for scm_branch_proposer.py"""
import datetime
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import scm_branch_proposer


class TestPropose(unittest.TestCase):
    NOW = datetime.datetime(2026, 7, 11, 12, 0, 0)

    def _task(self, slug, state, updated_at=None, pid="p1", tid="t1"):
        return {"slug": slug, "state": state, "project_id": pid, "id": tid,
                "updated_at": updated_at or self.NOW.isoformat()}

    # --- creation ---
    def test_create_for_running_task_without_branch(self):
        tasks = [self._task("foo", "RUNNING")]
        props = scm_branch_proposer.propose(tasks, set(), now=self.NOW)
        self.assertEqual(len(props), 1)
        self.assertEqual(props[0]["action"], "create")
        self.assertEqual(props[0]["branch_name"], "agent/foo")

    def test_no_create_if_branch_exists(self):
        tasks = [self._task("foo", "RUNNING")]
        props = scm_branch_proposer.propose(tasks, {"agent/foo"}, now=self.NOW)
        self.assertEqual(len(props), 0)

    def test_create_for_queued(self):
        tasks = [self._task("bar", "QUEUED")]
        props = scm_branch_proposer.propose(tasks, set(), now=self.NOW)
        self.assertEqual(len(props), 1)
        self.assertEqual(props[0]["action"], "create")

    # --- deletion ---
    def test_delete_stale_done_branch(self):
        old = (self.NOW - datetime.timedelta(days=20)).isoformat()
        tasks = [self._task("old-task", "DONE", updated_at=old)]
        props = scm_branch_proposer.propose(tasks, {"agent/old-task"}, now=self.NOW)
        self.assertEqual(len(props), 1)
        self.assertEqual(props[0]["action"], "delete")

    def test_no_delete_recent_done(self):
        recent = (self.NOW - datetime.timedelta(days=3)).isoformat()
        tasks = [self._task("recent", "DONE", updated_at=recent)]
        props = scm_branch_proposer.propose(tasks, {"agent/recent"}, now=self.NOW)
        self.assertEqual(len(props), 0)

    def test_delete_merged_stale(self):
        old = (self.NOW - datetime.timedelta(days=30)).isoformat()
        tasks = [self._task("merged-old", "MERGED", updated_at=old)]
        props = scm_branch_proposer.propose(tasks, {"agent/merged-old"}, now=self.NOW)
        self.assertEqual(len(props), 1)
        self.assertEqual(props[0]["action"], "delete")

    def test_no_delete_if_no_branch(self):
        old = (self.NOW - datetime.timedelta(days=30)).isoformat()
        tasks = [self._task("gone", "DONE", updated_at=old)]
        props = scm_branch_proposer.propose(tasks, set(), now=self.NOW)
        self.assertEqual(len(props), 0)

    # --- edge cases ---
    def test_empty_tasks(self):
        self.assertEqual(scm_branch_proposer.propose([], set(), now=self.NOW), [])

    def test_none_tasks(self):
        self.assertEqual(scm_branch_proposer.propose(None, set(), now=self.NOW), [])

    def test_missing_slug(self):
        tasks = [{"slug": "", "state": "RUNNING", "project_id": "p", "id": "t"}]
        self.assertEqual(scm_branch_proposer.propose(tasks, set(), now=self.NOW), [])

    def test_none_slug(self):
        tasks = [{"slug": None, "state": "RUNNING", "project_id": "p", "id": "t"}]
        self.assertEqual(scm_branch_proposer.propose(tasks, set(), now=self.NOW), [])

    def test_none_existing_branches_skips_delete(self):
        old = (self.NOW - datetime.timedelta(days=30)).isoformat()
        tasks = [self._task("x", "DONE", updated_at=old)]
        props = scm_branch_proposer.propose(tasks, None, now=self.NOW)
        self.assertEqual(len(props), 0)

    def test_bad_updated_at(self):
        tasks = [self._task("x", "DONE", updated_at="not-a-date")]
        props = scm_branch_proposer.propose(tasks, {"agent/x"}, now=self.NOW)
        self.assertEqual(len(props), 0)

    def test_iso_with_z_suffix(self):
        old = (self.NOW - datetime.timedelta(days=20)).strftime("%Y-%m-%dT%H:%M:%SZ")
        tasks = [self._task("zz", "DONE", updated_at=old)]
        props = scm_branch_proposer.propose(tasks, {"agent/zz"}, now=self.NOW)
        self.assertEqual(len(props), 1)

    def test_datetime_object_as_updated_at(self):
        old = self.NOW - datetime.timedelta(days=20)
        tasks = [self._task("dt", "MERGED", updated_at=old)]
        props = scm_branch_proposer.propose(tasks, {"agent/dt"}, now=self.NOW)
        self.assertEqual(len(props), 1)

    def test_mixed_create_and_delete(self):
        old = (self.NOW - datetime.timedelta(days=20)).isoformat()
        tasks = [
            self._task("new-one", "RUNNING"),
            self._task("old-one", "DONE", updated_at=old),
        ]
        branches = {"agent/old-one"}
        props = scm_branch_proposer.propose(tasks, branches, now=self.NOW)
        actions = {p["action"] for p in props}
        self.assertEqual(actions, {"create", "delete"})

    def test_retention_boundary(self):
        exactly = (self.NOW - datetime.timedelta(days=14)).isoformat()
        tasks = [self._task("edge", "DONE", updated_at=exactly)]
        props = scm_branch_proposer.propose(tasks, {"agent/edge"}, now=self.NOW)
        self.assertEqual(len(props), 0)  # not strictly greater

    def test_multiple_projects(self):
        tasks = [
            self._task("a", "RUNNING", pid="p1"),
            self._task("b", "RUNNING", pid="p2"),
        ]
        props = scm_branch_proposer.propose(tasks, set(), now=self.NOW)
        pids = {p["project_id"] for p in props}
        self.assertEqual(pids, {"p1", "p2"})


class TestAgeDays(unittest.TestCase):
    NOW = datetime.datetime(2026, 7, 11, 12, 0, 0)

    def test_none_returns_none(self):
        self.assertIsNone(scm_branch_proposer._age_days(self.NOW, None))

    def test_int_returns_none(self):
        self.assertIsNone(scm_branch_proposer._age_days(self.NOW, 12345))

    def test_valid_iso(self):
        ts = "2026-07-01T12:00:00"
        age = scm_branch_proposer._age_days(self.NOW, ts)
        self.assertAlmostEqual(age, 10.0, places=1)


if __name__ == "__main__":
    unittest.main()
