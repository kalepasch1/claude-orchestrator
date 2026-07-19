import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import task_dedup


class TaskDedupTest(unittest.TestCase):

    def test_release_protected_clears_dedup_deps_on_recovery_and_canaries(self):
        rows = [
            {"id": "r1", "slug": "recover-missing-branch-a", "state": "QUEUED",
             "deps": ["other"], "note": "dedup: waits on other"},
            {"id": "c1", "slug": "canary-ollama-1", "state": "QUEUED",
             "deps": [], "note": "dedup: waits on canary-gpt-1"},
            {"id": "n1", "slug": "normal-task", "state": "QUEUED",
             "deps": ["other"], "note": "dedup: waits on other"},
        ]
        updates = []
        db = MagicMock()
        db.select.return_value = rows
        db.update.side_effect = lambda table, match, patch: updates.append((table, match, patch))

        old_db = task_dedup.db
        try:
            task_dedup.db = db
            released = task_dedup.release_protected()
        finally:
            task_dedup.db = old_db

        self.assertEqual(released, 2)
        self.assertEqual([u[1]["id"] for u in updates], ["r1", "c1"])
        self.assertTrue(all(u[2]["deps"] == [] for u in updates))
        self.assertEqual(updates[0][2]["note"], "recovery: protected lane released; rebuild/reuse before net-new work")
        self.assertIn("coder-canary", updates[1][2]["note"])
        self.assertNotIn("waits on", updates[1][2]["note"])

    def test_analyze_skips_protected_lanes(self):
        rows = [
            {"id": "r1", "slug": "recover-missing-branch-a", "state": "QUEUED",
             "prompt": "same exact useful prompt", "deps": [], "material": False, "project_id": "p1"},
            {"id": "r2", "slug": "recover-missing-branch-b", "state": "QUEUED",
             "prompt": "same exact useful prompt", "deps": [], "material": False, "project_id": "p1"},
        ]
        db = MagicMock()
        db.select.return_value = rows

        old_db = task_dedup.db
        try:
            task_dedup.db = db
            clusters = task_dedup.analyze()
        finally:
            task_dedup.db = old_db

        self.assertEqual(clusters, [])

    def test_queued_tasks_uses_bounded_pages(self):
        db = MagicMock()
        db.select.side_effect = [
            [{"id": "1"}, {"id": "2"}],
            [{"id": "3"}],
        ]
        old_db, old_page, old_limit = task_dedup.db, task_dedup.DEDUP_PAGE_SIZE, task_dedup.DEDUP_SCAN_LIMIT
        try:
            task_dedup.db = db
            task_dedup.DEDUP_PAGE_SIZE = 2
            task_dedup.DEDUP_SCAN_LIMIT = 10
            rows = task_dedup._queued_tasks("id")
        finally:
            task_dedup.db = old_db
            task_dedup.DEDUP_PAGE_SIZE = old_page
            task_dedup.DEDUP_SCAN_LIMIT = old_limit

        self.assertEqual([row["id"] for row in rows], ["1", "2", "3"])
        self.assertEqual(db.select.call_args_list[0].args[1]["limit"], "2")
        self.assertEqual(db.select.call_args_list[1].args[1]["offset"], "2")


if __name__ == "__main__":
    unittest.main()
