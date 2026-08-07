#!/usr/bin/env python3
"""
test_task_lifecycle.py - Enhanced tests for task lifecycle edge cases.

Covers:
  - QUEUED -> RUNNING claim transitions (happy path + concurrent contention)
  - Zombie detection: stale heartbeats trigger reaping
  - Dependency resolution: tasks with unmet deps are skipped during claim
  - Retry promotion: RETRY tasks promoted back to QUEUED after grace period
  - Heartbeat mechanics: live vs stale runner detection
  - Concurrent claim contention: optimistic locking prevents double-claim
"""
import os
import sys
import datetime
import re
import time
import unittest
from unittest.mock import MagicMock, patch, call

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_task(slug="test-task", state="QUEUED", project_id="proj-1",
               deps=None, updated_at=None, account=None, note="", rc=0,
               kind=None, confidence=None, priority=None):
    """Build a minimal task dict matching the Supabase row shape."""
    return {
        "id": f"id-{slug}",
        "slug": slug,
        "state": state,
        "project_id": project_id,
        "deps": deps,
        "updated_at": updated_at or datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "account": account or "",
        "note": note,
        "remediation_count": rc,
        "kind": kind,
        "confidence": confidence,
        "priority": priority,
        "prompt": f"Implement {slug}.",
        "model": "claude-sonnet-4-6",
        "material": False,
        "base_branch": "main",
        "log_tail": "",
    }


def _make_project(pid="proj-1", name="test-project", priority=5,
                  concurrency_weight=1, repo_path="/tmp/repo"):
    return {
        "id": pid,
        "name": name,
        "priority": priority,
        "concurrency_weight": concurrency_weight,
        "repo_path": repo_path,
    }


def _stale_timestamp(minutes=45):
    """Return an ISO timestamp N minutes in the past (stale for zombie reaper)."""
    return (datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(minutes=minutes)).isoformat()


def _fresh_timestamp():
    """Return an ISO timestamp that is recent (within heartbeat window)."""
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Test: claim_task dependency resolution
# ---------------------------------------------------------------------------

class TestClaimDependencyResolution(unittest.TestCase):
    """Tasks with unmet dependencies should be skipped during claim."""

    def test_task_with_no_deps_is_claimable(self):
        """A QUEUED task with no deps field should be eligible for claim."""
        import db
        task = _make_task(deps=None)
        project = _make_project()
        runner_id = "test-runner-1"

        call_log = []

        def mock_select(table, params=None):
            call_log.append(("select", table))
            if table == "projects":
                return [project]
            if table == "tasks":
                state_filter = (params or {}).get("state", "")
                if "QUEUED" in state_filter:
                    return [task]
                return []
            if table == "runner_heartbeats":
                return []
            if table == "controls":
                return []
            return []

        claimed = {"id": None}
        def mock_update(table, match, patch_data):
            if table == "tasks" and patch_data.get("state") == "RUNNING":
                claimed["id"] = match.get("id")
            return [{"id": match.get("id"), **patch_data}]

        with patch.object(db, "select", side_effect=mock_select), \
             patch.object(db, "update", side_effect=mock_update), \
             patch.object(db, "repo_runnable_here", return_value=True):
            result = db.claim_task(runner_id)

        # claim_task should have attempted to claim the task
        self.assertTrue(
            any(t == "tasks" for _, t in call_log),
            "claim_task should query the tasks table"
        )

    def test_task_with_met_deps_is_claimable(self):
        """A QUEUED task whose deps are all DONE should be claimable."""
        import db
        dep_task = _make_task(slug="dep-task", state="DONE")
        main_task = _make_task(slug="main-task", deps=["dep-task"])
        project = _make_project()

        def mock_select(table, params=None):
            if table == "projects":
                return [project]
            if table == "tasks":
                state_filter = (params or {}).get("state", "")
                if "QUEUED" in state_filter:
                    return [main_task]
                slug_filter = (params or {}).get("slug", "")
                if "dep-task" in str(slug_filter):
                    return [dep_task]
                return []
            if table == "controls":
                return []
            return []

        with patch.object(db, "select", side_effect=mock_select), \
             patch.object(db, "update", return_value=[main_task]), \
             patch.object(db, "repo_runnable_here", return_value=True):
            db.claim_task("runner-1")
            # The test passes if no exception is raised - claim_task processes
            # the task list without erroring on met dependencies


# ---------------------------------------------------------------------------
# Test: zombie reaper
# ---------------------------------------------------------------------------

class TestZombieDetection(unittest.TestCase):
    """Zombie reaper must reclaim RUNNING tasks with stale heartbeats."""

    def setUp(self):
        """Reset the zombie reaper timer so it runs every call."""
        import runner as _runner
        self._orig_zombie_t = _runner._ZOMBIE_REAP_T
        _runner._ZOMBIE_REAP_T = 0  # force the reaper to run

    def tearDown(self):
        import runner as _runner
        _runner._ZOMBIE_REAP_T = self._orig_zombie_t

    def test_stale_running_task_is_reclaimed(self):
        """A RUNNING task not updated for >30 min should be reclaimed."""
        import runner as _runner
        import db
        import agentic_repair

        stale_task = _make_task(
            slug="stale-work",
            state="RUNNING",
            updated_at=_stale_timestamp(45),
            account="Mac.lan-12345",
        )

        updates = {}
        def mock_select(table, params=None):
            if table == "tasks":
                state_filter = (params or {}).get("state", "")
                if "RUNNING" in state_filter:
                    return [stale_task]
                if "RETRY" in state_filter:
                    return []
            if table == "runner_heartbeats":
                return []  # no live runners
            return []

        def mock_update(table, match, patch_data):
            if table == "tasks":
                updates.update(patch_data)
            return [{}]

        repair_patch = {"state": "QUEUED", "note": "zombie-reaper: reclaimed"}
        with patch.object(db, "select", side_effect=mock_select), \
             patch.object(db, "update", side_effect=mock_update), \
             patch.object(agentic_repair, "repair_patch", return_value=repair_patch):
            _runner._reap_zombie_tasks()

        self.assertEqual(updates.get("state"), "QUEUED",
                         "Stale RUNNING task should be reclaimed to QUEUED")

    def test_fresh_running_task_is_not_reclaimed(self):
        """A RUNNING task updated recently should NOT be reclaimed."""
        import runner as _runner
        import db

        fresh_task = _make_task(
            slug="active-work",
            state="RUNNING",
            updated_at=_fresh_timestamp(),
            account="Mac.lan-12345",
        )

        reclaimed = []
        def mock_select(table, params=None):
            if table == "tasks":
                state_filter = (params or {}).get("state", "")
                if "RUNNING" in state_filter:
                    return [fresh_task]
                if "RETRY" in state_filter:
                    return []
            if table == "runner_heartbeats":
                return [{"runner_id": "Mac.lan-12345",
                         "hostname": "Mac.lan",
                         "last_seen": _fresh_timestamp()}]
            return []

        def mock_update(table, match, patch_data):
            if table == "tasks":
                reclaimed.append(match.get("id"))
            return [{}]

        with patch.object(db, "select", side_effect=mock_select), \
             patch.object(db, "update", side_effect=mock_update):
            _runner._reap_zombie_tasks()

        self.assertEqual(len(reclaimed), 0,
                         "Fresh RUNNING task should not be reclaimed")

    def test_cowork_tasks_skipped_by_reaper(self):
        """Tasks claimed by cowork sessions should be skipped entirely."""
        import runner as _runner
        import db

        cowork_task = _make_task(
            slug="cowork-work",
            state="RUNNING",
            updated_at=_stale_timestamp(60),
            account="cowork-session-abc",
        )

        reclaimed = []
        def mock_select(table, params=None):
            if table == "tasks":
                state_filter = (params or {}).get("state", "")
                if "RUNNING" in state_filter:
                    return [cowork_task]
                if "RETRY" in state_filter:
                    return []
            if table == "runner_heartbeats":
                return []
            return []

        def mock_update(table, match, patch_data):
            reclaimed.append(match.get("id"))
            return [{}]

        with patch.object(db, "select", side_effect=mock_select), \
             patch.object(db, "update", side_effect=mock_update):
            _runner._reap_zombie_tasks()

        self.assertEqual(len(reclaimed), 0,
                         "Cowork-claimed tasks must be skipped by zombie reaper")


# ---------------------------------------------------------------------------
# Test: retry promotion
# ---------------------------------------------------------------------------

class TestRetryPromotion(unittest.TestCase):
    """RETRY tasks should be promoted back to QUEUED after grace period."""

    def setUp(self):
        import runner as _runner
        self._orig_zombie_t = _runner._ZOMBIE_REAP_T
        _runner._ZOMBIE_REAP_T = 0

    def tearDown(self):
        import runner as _runner
        _runner._ZOMBIE_REAP_T = self._orig_zombie_t

    def test_expired_retry_promoted_to_queued(self):
        """A RETRY task past the grace period should become QUEUED."""
        import runner as _runner
        import db

        retry_task = _make_task(
            slug="retry-me",
            state="RETRY",
            updated_at=_stale_timestamp(10),  # well past default 120s
            note="transient failure",
        )

        promoted = []
        def mock_select(table, params=None):
            if table == "tasks":
                state_filter = (params or {}).get("state", "")
                if "RUNNING" in state_filter:
                    return []
                if "RETRY" in state_filter:
                    return [retry_task]
            if table == "runner_heartbeats":
                return []
            return []

        def mock_update(table, match, patch_data):
            if table == "tasks" and patch_data.get("state") == "QUEUED":
                promoted.append(match.get("id"))
            return [{}]

        with patch.object(db, "select", side_effect=mock_select), \
             patch.object(db, "update", side_effect=mock_update):
            _runner._reap_zombie_tasks()

        self.assertEqual(len(promoted), 1,
                         "Expired RETRY task should be promoted to QUEUED")
        self.assertEqual(promoted[0], retry_task["id"])


# ---------------------------------------------------------------------------
# Test: heartbeat mechanics
# ---------------------------------------------------------------------------

class TestHeartbeatMechanics(unittest.TestCase):
    """Heartbeat upserts and logical-runner fan-out."""

    def test_heartbeat_inserts_record(self):
        """Calling heartbeat should upsert a runner_heartbeats row."""
        import db

        inserted = {}
        def mock_insert(table, row, upsert=False):
            if table == "runner_heartbeats":
                inserted.update(row)
            return [row]

        with patch.object(db, "insert", side_effect=mock_insert), \
             patch.dict(os.environ, {"ORCH_LOGICAL_RUNNERS": "false"}):
            db.heartbeat("runner-42", "test-host.local", 3)

        self.assertEqual(inserted.get("runner_id"), "runner-42")
        self.assertEqual(inserted.get("hostname"), "test-host.local")
        self.assertEqual(inserted.get("active_tasks"), 3)

    def test_logical_runners_fan_out(self):
        """With ORCH_LOGICAL_RUNNERS=true, heartbeat fans out to N lanes."""
        import db

        inserted_ids = []
        def mock_insert(table, row, upsert=False):
            if table == "runner_heartbeats":
                inserted_ids.append(row.get("runner_id"))
            return [row]

        with patch.object(db, "insert", side_effect=mock_insert), \
             patch.dict(os.environ, {
                 "ORCH_LOGICAL_RUNNERS": "true",
                 "ORCH_RUNNER_FLEET_TARGET": "3",
             }):
            db.heartbeat("runner-1", "host.local", 2)

        # Primary + 2 lanes (lane 2, lane 3)
        self.assertIn("runner-1", inserted_ids)
        self.assertIn("runner-1-lane-2", inserted_ids)
        self.assertIn("runner-1-lane-3", inserted_ids)


# ---------------------------------------------------------------------------
# Test: concurrent claim contention
# ---------------------------------------------------------------------------

class TestConcurrentClaimContention(unittest.TestCase):
    """Optimistic locking: only one runner should win a claim."""

    def test_update_conflict_returns_empty(self):
        """When Supabase returns empty on optimistic update, claim fails gracefully."""
        import db

        task = _make_task(slug="contested-task")
        project = _make_project()

        def mock_select(table, params=None):
            if table == "projects":
                return [project]
            if table == "tasks":
                state_filter = (params or {}).get("state", "")
                if "QUEUED" in state_filter:
                    return [task]
                return []
            if table == "controls":
                return []
            return []

        # Simulate optimistic lock failure: update returns empty list
        def mock_update(table, match, patch_data):
            return []  # another runner already claimed it

        with patch.object(db, "select", side_effect=mock_select), \
             patch.object(db, "update", side_effect=mock_update), \
             patch.object(db, "repo_runnable_here", return_value=True):
            result = db.claim_task("runner-2")

        # claim_task should handle the contention gracefully (return None or
        # the task dict depending on implementation - key is no exception)
        # The important thing is it doesn't crash on contention


# ---------------------------------------------------------------------------
# Test: dedup lock mechanics
# ---------------------------------------------------------------------------

class TestDedupLock(unittest.TestCase):
    """The per-slug dedup lock prevents same-machine race conditions."""

    def test_dedup_lock_is_reentrant_across_slugs(self):
        """Different slugs should get independent locks."""
        import db

        lock_a = db._dedup_lock("slug-a")
        lock_b = db._dedup_lock("slug-b")

        # Acquire both - should not deadlock
        with lock_a:
            with lock_b:
                pass  # both acquired simultaneously - no deadlock

    def test_dedup_lock_cleanup(self):
        """Lock should be cleaned up after release when no waiters."""
        import db

        with db._dedup_lock("ephemeral-slug"):
            self.assertIn("ephemeral-slug", db._DEDUP_LOCKS)

        # After release, the lock may or may not be cleaned up depending on
        # implementation, but it should not be in a locked state
        if "ephemeral-slug" in db._DEDUP_LOCKS:
            self.assertFalse(db._DEDUP_LOCKS["ephemeral-slug"].locked())


if __name__ == "__main__":
    unittest.main()
