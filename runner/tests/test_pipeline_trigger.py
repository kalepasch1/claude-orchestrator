"""
Acceptance tests for immediate test triggering on queue.

Verifies:
- test_trigger() transitions QUEUED → TESTING atomically
- claim_task() picks up TESTING tasks (no stuck tasks)
- enqueue_task() fires test_trigger() immediately after insert
- No regression on existing QUEUED → RUNNING claim flow
"""
import os
import sys
import time
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db


class TestTestTrigger(unittest.TestCase):
    def setUp(self):
        self.orig_req = db._req

    def tearDown(self):
        db._req = self.orig_req

    def test_trigger_transitions_queued_to_testing(self):
        patched = [{"id": "t1", "state": "TESTING"}]

        def req(method, path, body=None, headers=None, params=None):
            self.assertEqual(method, "PATCH")
            self.assertIn("tasks", path)
            self.assertEqual(body.get("state"), "TESTING")
            self.assertEqual(params.get("state"), "eq.QUEUED")
            self.assertEqual(params.get("id"), "eq.t1")
            return patched

        db._req = req
        result = db.test_trigger("t1")
        self.assertEqual(result["state"], "TESTING")

    def test_trigger_returns_none_when_already_claimed(self):
        """If PATCH matches 0 rows (task was already claimed), return None."""
        def req(method, path, body=None, headers=None, params=None):
            return []  # 0 rows matched — task already moved out of QUEUED

        db._req = req
        result = db.test_trigger("t1")
        self.assertIsNone(result)

    def test_trigger_is_fail_soft_on_error(self):
        def req(method, path, body=None, headers=None, params=None):
            raise RuntimeError("network error")

        db._req = req
        result = db.test_trigger("t1")
        self.assertIsNone(result)

    def test_trigger_returns_none_on_empty_response(self):
        def req(method, path, body=None, headers=None, params=None):
            return None

        db._req = req
        result = db.test_trigger("t1")
        self.assertIsNone(result)


class TestClaimTaskPicksUpTesting(unittest.TestCase):
    def setUp(self):
        self.orig = (db.select, db._req)
        self.claimed = []

    def tearDown(self):
        db.select, db._req = self.orig

    def test_claim_task_picks_up_testing_state(self):
        """A TESTING task (test suite started, not yet claimed) is claimable."""
        tasks = [
            {"id": "t1", "project_id": "p1", "slug": "feature-x",
             "deps": [], "created_at": "2026-01-01", "state": "TESTING"},
        ]

        def select(table, params=None):
            params = params or {}
            if table == "projects":
                return [{"id": "p1", "name": "app", "priority": 5, "concurrency_weight": 1}]
            if table == "controls":
                return []
            if table == "tasks":
                state = params.get("state")
                if state in ("eq.QUEUED", "in.(QUEUED,TESTING)"):
                    return [dict(t) for t in tasks]
                if state in ("in.(RUNNING,RETRY)", "in.(RUNNING,DONE,MERGED)", "in.(DONE,MERGED)"):
                    return []
            return []

        def req(method, path, body=None, headers=None, params=None):
            task_id = params.get("id", "").replace("eq.", "")
            self.claimed.append(task_id)
            return [next(t for t in tasks if t["id"] == task_id)]

        db.select = select
        db._req = req
        task = db.claim_task("runner-1")
        self.assertIsNotNone(task)
        self.assertEqual(task["id"], "t1")
        self.assertEqual(self.claimed, ["t1"])

    def test_claim_prefers_testing_over_queued_when_enqueued_earlier(self):
        """FIFO ordering is preserved across QUEUED and TESTING tasks."""
        tasks = [
            {"id": "t-old", "project_id": "p1", "slug": "old-feature",
             "deps": [], "created_at": "2026-01-01", "state": "TESTING"},
            {"id": "t-new", "project_id": "p1", "slug": "new-feature",
             "deps": [], "created_at": "2026-01-02", "state": "QUEUED"},
        ]

        def select(table, params=None):
            params = params or {}
            if table == "projects":
                return [{"id": "p1", "name": "app", "priority": 5, "concurrency_weight": 1}]
            if table == "controls":
                return []
            if table == "tasks":
                state = params.get("state")
                if state in ("eq.QUEUED", "in.(QUEUED,TESTING)"):
                    return [dict(t) for t in tasks]
                if state in ("in.(RUNNING,RETRY)", "in.(RUNNING,DONE,MERGED)", "in.(DONE,MERGED)"):
                    return []
            return []

        def req(method, path, body=None, headers=None, params=None):
            task_id = params.get("id", "").replace("eq.", "")
            self.claimed.append(task_id)
            return [next(t for t in tasks if t["id"] == task_id)]

        db.select = select
        db._req = req
        task = db.claim_task("runner-1")
        self.assertEqual(task["id"], "t-old")

    def test_queued_task_still_claimable_without_test_trigger(self):
        """Existing QUEUED → RUNNING flow still works (no regression)."""
        tasks = [
            {"id": "t1", "project_id": "p1", "slug": "vanilla",
             "deps": [], "created_at": "2026-01-01", "state": "QUEUED"},
        ]

        def select(table, params=None):
            params = params or {}
            if table == "projects":
                return [{"id": "p1", "name": "app", "priority": 5, "concurrency_weight": 1}]
            if table == "controls":
                return []
            if table == "tasks":
                state = params.get("state")
                if state in ("eq.QUEUED", "in.(QUEUED,TESTING)"):
                    return [dict(t) for t in tasks]
                if state in ("in.(RUNNING,RETRY)", "in.(RUNNING,DONE,MERGED)", "in.(DONE,MERGED)"):
                    return []
            return []

        def req(method, path, body=None, headers=None, params=None):
            task_id = params.get("id", "").replace("eq.", "")
            self.claimed.append(task_id)
            return [next(t for t in tasks if t["id"] == task_id)]

        db.select = select
        db._req = req
        task = db.claim_task("runner-1")
        self.assertIsNotNone(task)
        self.assertEqual(task["id"], "t1")


class TestEnqueueFiresTestTrigger(unittest.TestCase):
    """Verify enqueue_task.main() calls test_trigger within the same call."""

    def test_trigger_called_immediately_after_insert(self):
        import enqueue_task

        insert_calls = []
        trigger_calls = []

        def mock_select(table, params=None):
            if table == "projects":
                return [{"id": "p1", "name": "myapp", "repo_path": "/repo/myapp"}]
            if table == "tasks":
                return []
            return []

        def mock_insert(table, row):
            insert_calls.append(row)
            return [{"id": "new-task-id", "state": "QUEUED"}]

        def mock_test_trigger(task_id):
            trigger_calls.append(task_id)
            return {"id": task_id, "state": "TESTING"}

        spec = {"project": "myapp", "slug": "test-slug", "prompt": "do something"}
        with patch.object(db, "select", side_effect=mock_select), \
             patch.object(db, "insert", side_effect=mock_insert), \
             patch.object(db, "test_trigger", side_effect=mock_test_trigger):
            enqueue_task.main.__wrapped__ = None  # just call the function
            import io, contextlib
            with contextlib.redirect_stdout(io.StringIO()):
                enqueue_task.main.__func__ if hasattr(enqueue_task.main, "__func__") else None
                # call main with a temp file
                import tempfile, json
                with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
                    json.dump(spec, f)
                    fname = f.name
                enqueue_task.main(fname)

        self.assertEqual(len(insert_calls), 1)
        self.assertEqual(trigger_calls, ["new-task-id"],
                         "test_trigger must be called immediately after enqueue with the new task id")

    def test_trigger_fires_within_two_seconds(self):
        """Acceptance: from enqueue to TESTING state in under 2 s (mocked clock)."""
        import enqueue_task

        trigger_times = []
        enqueue_time = time.monotonic()

        def mock_select(table, params=None):
            if table == "projects":
                return [{"id": "p1", "name": "myapp", "repo_path": "/repo/myapp"}]
            if table == "tasks":
                return []
            return []

        def mock_insert(table, row):
            return [{"id": "task-abc", "state": "QUEUED"}]

        def mock_test_trigger(task_id):
            trigger_times.append(time.monotonic())
            return {"id": task_id, "state": "TESTING"}

        spec = {"project": "myapp", "slug": "timing-test", "prompt": "do something"}
        with patch.object(db, "select", side_effect=mock_select), \
             patch.object(db, "insert", side_effect=mock_insert), \
             patch.object(db, "test_trigger", side_effect=mock_test_trigger):
            import tempfile, json, io, contextlib
            with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
                json.dump(spec, f)
                fname = f.name
            with contextlib.redirect_stdout(io.StringIO()):
                enqueue_task.main(fname)

        self.assertTrue(len(trigger_times) >= 1, "test_trigger was never called")
        elapsed = trigger_times[0] - enqueue_time
        self.assertLess(elapsed, 2.0,
                        f"test_trigger fired {elapsed:.3f}s after enqueue — must be < 2s")


if __name__ == "__main__":
    unittest.main(verbosity=2)
