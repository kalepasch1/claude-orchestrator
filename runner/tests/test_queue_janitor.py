"""Tests for queue_janitor automated task state transitions.

Reproduces the core failure modes the janitor was built to handle:
  - orphaned-running: task stuck RUNNING past the agentic-coder timeout
  - stuck-running: main loop wedged for >STUCK_RUNNING_H hours
  - empty-run: BLOCKED tasks with no committable changes
  - stranded-approval: BLOCKED awaiting-approval tasks
"""
import datetime
import os
import sys
import time
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import agentic_repair
import queue_janitor


def _ts(seconds_ago):
    """Return an ISO-8601 UTC timestamp from N seconds ago."""
    t = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=seconds_ago)
    return t.isoformat()


def _running_task(task_id="t1", slug="fix-me", seconds_ago=0, retries=0):
    return {
        "id": task_id,
        "slug": slug,
        "state": "RUNNING",
        "prompt": f"Complete the task '{slug}'.",
        "note": "",
        "transient_retries": retries,
        "updated_at": _ts(seconds_ago),
    }


class ReleaseOrphanedRunningTest(unittest.TestCase):
    """release_orphaned_running() transitions stale RUNNING tasks to QUEUED."""

    def _run(self, tasks):
        updates = []
        db = MagicMock()
        db.select.return_value = tasks
        db.update.side_effect = lambda table, match, patch_row: updates.append((table, match, patch_row))

        with patch.object(queue_janitor, "db", db), \
             patch.object(agentic_repair, "choose_coder", return_value="ollama"):
            count = queue_janitor.release_orphaned_running()
        return count, updates

    def test_orphaned_task_is_requeued_as_agentic_repair(self):
        # Task last updated 25 minutes ago — past the 20m orphan threshold.
        task = _running_task(seconds_ago=25 * 60)
        count, updates = self._run([task])

        self.assertEqual(count, 1)
        self.assertEqual(len(updates), 1)
        _, _, patch_row = updates[0]
        self.assertEqual(patch_row["state"], "QUEUED")
        self.assertIsNone(patch_row["account"])
        self.assertIn(agentic_repair.MARKER, patch_row["prompt"])
        self.assertIn("orphaned-running", patch_row["note"])

    def test_recent_running_task_is_not_touched(self):
        # Task last updated 5 minutes ago — still within the allowed window.
        task = _running_task(seconds_ago=5 * 60)
        count, updates = self._run([task])

        self.assertEqual(count, 0)
        self.assertEqual(updates, [])

    def test_transient_retries_incremented_below_cap(self):
        task = _running_task(seconds_ago=25 * 60, retries=1)
        _, updates = self._run([task])

        _, _, patch_row = updates[0]
        self.assertEqual(patch_row["transient_retries"], 2)

    def test_at_cap_does_not_increment_transient_retries_further(self):
        # At cap: repair_patch is still called but transient_retries key comes from the task.
        task = _running_task(seconds_ago=25 * 60, retries=queue_janitor.REQUEUE_CAP)
        _, updates = self._run([task])

        self.assertEqual(len(updates), 1)
        _, _, patch_row = updates[0]
        # Patch is applied; prompt still has the repair marker.
        self.assertIn(agentic_repair.MARKER, patch_row["prompt"])

    def test_multiple_orphans_are_all_released(self):
        tasks = [
            _running_task("t1", "slug-a", seconds_ago=30 * 60),
            _running_task("t2", "slug-b", seconds_ago=60 * 60),
        ]
        count, updates = self._run(tasks)

        self.assertEqual(count, 2)
        self.assertEqual(len(updates), 2)
        for _, _, patch_row in updates:
            self.assertEqual(patch_row["state"], "QUEUED")

    def test_env_override_changes_orphan_threshold(self):
        # Raise threshold to 60m; a 30m-old task should NOT be released.
        task = _running_task(seconds_ago=30 * 60)
        with patch.dict(os.environ, {"JANITOR_ORPHAN_RUNNING_MIN": "60"}):
            # Reload the constant from env.
            original = queue_janitor.ORPHAN_RUNNING_MIN
            queue_janitor.ORPHAN_RUNNING_MIN = float(os.environ["JANITOR_ORPHAN_RUNNING_MIN"])
            try:
                count, _ = self._run([task])
            finally:
                queue_janitor.ORPHAN_RUNNING_MIN = original
        self.assertEqual(count, 0)

    def test_malformed_timestamp_is_skipped_gracefully(self):
        task = _running_task()
        task["updated_at"] = "not-a-date"
        count, updates = self._run([task])

        self.assertEqual(count, 0)
        self.assertEqual(updates, [])


class RequeueStuckRunningTest(unittest.TestCase):
    """requeue_stuck_running() handles the main-loop wedge case (>STUCK_RUNNING_H hours)."""

    def _run(self, tasks):
        updates = []
        notifications = []
        db = MagicMock()
        db.select.return_value = tasks
        db.update.side_effect = lambda table, match, patch_row: updates.append(patch_row)
        db.insert.side_effect = lambda table, row, **kw: notifications.append(row)

        with patch.object(queue_janitor, "db", db), \
             patch.object(agentic_repair, "choose_coder", return_value="ollama"):
            count = queue_janitor.requeue_stuck_running()
        return count, updates, notifications

    def test_wedged_task_transitions_to_queued(self):
        task = _running_task(seconds_ago=3 * 3600)  # 3h > 2h default
        count, updates, notifications = self._run([task])

        self.assertEqual(count, 1)
        self.assertEqual(updates[0]["state"], "QUEUED")
        self.assertEqual(len(notifications), 1)
        self.assertEqual(notifications[0]["kind"], "janitor")

    def test_recently_updated_running_task_is_not_wedged(self):
        task = _running_task(seconds_ago=30 * 60)  # 30 min, below 2h
        count, updates, _ = self._run([task])

        self.assertEqual(count, 0)
        self.assertEqual(updates, [])


class RequeueEmptyRunsTest(unittest.TestCase):
    """requeue_empty_runs() auto-repairs BLOCKED tasks with empty-diff markers."""

    def _run(self, tasks):
        updates = []
        db = MagicMock()
        db.select.return_value = tasks
        db.update.side_effect = lambda table, match, patch_row: updates.append(patch_row)

        with patch.object(queue_janitor, "db", db), \
             patch.object(agentic_repair, "choose_coder", return_value="ollama"):
            count = queue_janitor.requeue_empty_runs()
        return count, updates

    def test_empty_diff_blocked_task_is_requeued(self):
        task = {
            "id": "t1",
            "slug": "empty-slug",
            "state": "BLOCKED",
            "prompt": "Fix the widget.",
            "note": "no committable changes",
            "transient_retries": 0,
        }
        count, updates = self._run([task])

        self.assertEqual(count, 1)
        self.assertEqual(updates[0]["state"], "QUEUED")

    def test_unrelated_blocked_task_is_not_touched(self):
        task = {
            "id": "t2",
            "slug": "normal",
            "state": "BLOCKED",
            "prompt": "Do some work.",
            "note": "waiting on review",
            "transient_retries": 0,
        }
        count, updates = self._run([task])

        self.assertEqual(count, 0)
        self.assertEqual(updates, [])

    def test_all_empty_markers_trigger_repair(self):
        for marker in queue_janitor.EMPTY_RUN_MARKERS:
            task = {
                "id": "t3",
                "slug": "empty-slug",
                "state": "BLOCKED",
                "prompt": "Do work.",
                "note": f"runner ended: {marker}",
                "transient_retries": 0,
            }
            count, _ = self._run([task])
            self.assertEqual(count, 1, f"marker '{marker}' did not trigger requeue")


class RefileStrandedApprovalsTest(unittest.TestCase):
    """refile_stranded_approvals() releases BLOCKED awaiting-approval tasks."""

    def _run(self, tasks):
        updates = []
        db = MagicMock()
        db.select.return_value = tasks
        db.update.side_effect = lambda table, match, patch_row: updates.append(patch_row)

        with patch.object(queue_janitor, "db", db), \
             patch.object(agentic_repair, "choose_coder", return_value="ollama"):
            count = queue_janitor.refile_stranded_approvals()
        return count, updates

    def test_awaiting_approval_task_is_refiled(self):
        task = {
            "id": "t1",
            "slug": "pending-approval",
            "state": "BLOCKED",
            "prompt": "Merge the changes.",
            "note": "awaiting your approval before merge",
        }
        count, updates = self._run([task])

        self.assertEqual(count, 1)
        self.assertEqual(updates[0]["state"], "QUEUED")
        self.assertIn(agentic_repair.MARKER, updates[0]["prompt"])

    def test_non_approval_blocked_task_is_skipped(self):
        task = {
            "id": "t2",
            "slug": "other-blocked",
            "state": "BLOCKED",
            "prompt": "Do work.",
            "note": "dependency missing",
        }
        count, updates = self._run([task])

        self.assertEqual(count, 0)


if __name__ == "__main__":
    unittest.main()
