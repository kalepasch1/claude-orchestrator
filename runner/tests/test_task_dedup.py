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


if __name__ == "__main__":
    unittest.main()
