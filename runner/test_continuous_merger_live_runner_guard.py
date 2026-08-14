#!/usr/bin/env python3
"""Contract test: continuous_merger must never merge a branch a live runner owns.

THE BUG THIS PINS: _process_task merged agent/<slug> the moment any task row
for the slug reached DONE. When another runner for the same slug was still
RUNNING (orphan-repair resume, duplicate claim), it was still committing to
that branch from its worktree — the merger merged a mid-write snapshot and
deleted the ref, orphaning the live runner's commits and manufacturing the
exact merge conflicts the queue exists to prevent. The guard defers instead:
the task stays DONE and merge_backlog()/merge_train retries after the runner
finishes or the janitor demotes it.
"""
import datetime
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import continuous_merger  # noqa: E402


def _iso(age_seconds):
    ts = (datetime.datetime.now(datetime.timezone.utc)
          - datetime.timedelta(seconds=age_seconds))
    return ts.isoformat()


class _FakeDB:
    """Stands in for the db module; records queried tables."""

    def __init__(self, task_rows):
        self.task_rows = task_rows
        self.tables_queried = []

    def select(self, table, params=None):
        self.tables_queried.append(table)
        if table == "tasks":
            return self.task_rows
        return []


class _RaisingDB:
    def select(self, table, params=None):
        raise RuntimeError("supabase down")


class LiveRunnerGuardTest(unittest.TestCase):
    def setUp(self):
        self._real_db = continuous_merger.db
        self._real_guard = continuous_merger.LIVE_RUNNER_GUARD
        continuous_merger.LIVE_RUNNER_GUARD = True

    def tearDown(self):
        continuous_merger.db = self._real_db
        continuous_merger.LIVE_RUNNER_GUARD = self._real_guard

    def test_fresh_running_sibling_blocks(self):
        continuous_merger.db = _FakeDB(
            [{"id": "t2", "state": "RUNNING", "updated_at": _iso(30)}])
        self.assertTrue(
            continuous_merger._live_runner_blocking("p1", "some-slug", "t1"))

    def test_no_running_sibling_allows(self):
        continuous_merger.db = _FakeDB([])
        self.assertEqual(
            continuous_merger._live_runner_blocking("p1", "some-slug", "t1"), "")

    def test_own_task_row_does_not_block_itself(self):
        # The completing task can race its own DONE write and still read back
        # as RUNNING; its own row must never defer its own merge.
        continuous_merger.db = _FakeDB(
            [{"id": "t1", "state": "RUNNING", "updated_at": _iso(5)}])
        self.assertEqual(
            continuous_merger._live_runner_blocking("p1", "some-slug", "t1"), "")

    def test_stale_running_row_does_not_block(self):
        # An orphaned RUNNING row (janitor territory) may only delay a merge,
        # never block it forever.
        stale = continuous_merger.LIVE_RUNNER_STALE_SECONDS + 60
        continuous_merger.db = _FakeDB(
            [{"id": "t2", "state": "RUNNING", "updated_at": _iso(stale)}])
        self.assertEqual(
            continuous_merger._live_runner_blocking("p1", "some-slug", "t1"), "")

    def test_unparseable_timestamp_blocks(self):
        continuous_merger.db = _FakeDB(
            [{"id": "t2", "state": "RUNNING", "updated_at": "not-a-time"}])
        self.assertTrue(
            continuous_merger._live_runner_blocking("p1", "some-slug", "t1"))

    def test_db_error_fails_safe_to_deferral(self):
        continuous_merger.db = _RaisingDB()
        self.assertTrue(
            continuous_merger._live_runner_blocking("p1", "some-slug", "t1"))

    def test_guard_disabled_allows(self):
        continuous_merger.LIVE_RUNNER_GUARD = False
        continuous_merger.db = _RaisingDB()
        self.assertEqual(
            continuous_merger._live_runner_blocking("p1", "some-slug", "t1"), "")

    def test_no_db_allows(self):
        continuous_merger.db = None
        self.assertEqual(
            continuous_merger._live_runner_blocking("p1", "some-slug", "t1"), "")

    def test_process_task_defers_before_touching_the_repo(self):
        fake = _FakeDB([{"id": "t2", "state": "RUNNING", "updated_at": _iso(10)}])
        continuous_merger.db = fake
        with continuous_merger._stats_lock:
            before = continuous_merger._stats["deferred_live_runner"]
        continuous_merger._process_task(
            {"id": "t1", "project_id": "p1", "slug": "some-slug"})
        with continuous_merger._stats_lock:
            after = continuous_merger._stats["deferred_live_runner"]
        self.assertEqual(after, before + 1)
        # Deferral happens before any project lookup (and thus any git ops).
        self.assertNotIn("projects", fake.tables_queried)


if __name__ == "__main__":
    unittest.main()
