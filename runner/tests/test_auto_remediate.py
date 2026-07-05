import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import auto_remediate


class AutoRemediateRecoveryTest(unittest.TestCase):

    def test_pending_cap_card_requeues_matching_blocked_task(self):
        card = {
            "id": "a1",
            "title": "Needs a look: 'fix-login' blocked after 3 auto-fixes",
            "why": "Last error: judge: missing validation.",
            "status": "pending",
            "project": None,
        }
        task = {
            "id": "t1",
            "slug": "fix-login",
            "state": "BLOCKED",
            "prompt": "Fix login validation.",
            "note": "judge: missing validation",
            "model": "claude-haiku-4-5-20251001",
            "material": False,
        }
        updates = []
        db = MagicMock()

        def select(table, params=None):
            if table == "approvals":
                return [card]
            if table == "tasks":
                return [task]
            return []

        db.select.side_effect = select
        db.update.side_effect = lambda table, match, patch: updates.append((table, match, patch))

        with patch.object(auto_remediate, "db", db):
            recovered = auto_remediate.recover_pending_manual_reviews()

        self.assertEqual(recovered, 1)
        task_patch = next(p for table, _, p in updates if table == "tasks")
        self.assertEqual(task_patch["state"], "QUEUED")
        self.assertEqual(task_patch["remediation_count"], 0)
        self.assertIn(auto_remediate.DIRECTIVE_MARKER, task_patch["prompt"])
        approval_patch = next(p for table, _, p in updates if table == "approvals")
        self.assertEqual(approval_patch["status"], "approved")
        self.assertEqual(approval_patch["decided_by"], auto_remediate.RECOVERY_MARK)

    def test_auto_closed_noop_task_is_restored_to_queue(self):
        task = {
            "id": "t2",
            "slug": "restore-me",
            "state": "DONE",
            "prompt": "Implement the missing widget.",
            "note": "auto-closed: no committable work after retry (not a real task)",
            "model": "claude-sonnet-4-6",
            "material": False,
        }
        updates = []
        db = MagicMock()
        db.select.return_value = [task]
        db.update.side_effect = lambda table, match, patch: updates.append((table, match, patch))

        with patch.object(auto_remediate, "db", db):
            restored = auto_remediate.recover_auto_closed_noops()

        self.assertEqual(restored, 1)
        patch_row = updates[0][2]
        self.assertEqual(patch_row["state"], "QUEUED")
        # counter is preserved+incremented across restores so repeat no-ops converge to the hard cap
        self.assertEqual(patch_row["remediation_count"], 1)
        self.assertIn("incorrectly removed from the cue", patch_row["prompt"])

    def test_cap_reached_requeues_without_creating_human_card(self):
        task = {
            "id": "t3",
            "slug": "hard-fix",
            "state": "BLOCKED",
            "prompt": "Fix the hard bug.",
            "note": "quality gate: property test failed",
            "remediation_count": auto_remediate.CAP,
            "model": "claude-sonnet-4-6",
            "material": False,
            "project_id": "p1",
        }
        updates = []
        inserts = []
        db = MagicMock()
        # select order in run(): approvals(cards), tasks(DONE noops), tasks(SHELVED recover), tasks(blocked)
        db.select.side_effect = [[], [], [], [task]]
        db.update.side_effect = lambda table, match, patch: updates.append((table, match, patch))
        db.insert.side_effect = lambda table, row, **kw: inserts.append((table, row))

        with patch.object(auto_remediate, "db", db):
            result = auto_remediate.run()

        self.assertEqual(result["reclaimed"], 1)
        self.assertEqual(inserts, [])
        task_patch = next(p for table, _, p in updates if table == "tasks")
        self.assertEqual(task_patch["state"], "QUEUED")
        self.assertIn("cap reached", task_patch["note"])


if __name__ == "__main__":
    unittest.main()
