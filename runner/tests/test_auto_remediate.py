import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import auto_remediate
import agentic_repair


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
        self.assertIn(agentic_repair.MARKER, task_patch["prompt"])
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

        with patch.dict(os.environ, {"ORCH_RECOVER_AUTO_CLOSED_NOOPS": "true"}), \
             patch.object(auto_remediate, "db", db):
            restored = auto_remediate.recover_auto_closed_noops()

        self.assertEqual(restored, 1)
        patch_row = updates[0][2]
        self.assertEqual(patch_row["state"], "QUEUED")
        # counter is preserved+incremented across restores so repeat no-ops converge to the hard cap
        self.assertEqual(patch_row["remediation_count"], 1)
        self.assertIn("incorrectly removed from active work", patch_row["prompt"])

    def test_auto_closed_noop_recovery_is_disabled_by_default(self):
        db = MagicMock()

        with patch.dict(os.environ, {}, clear=True), patch.object(auto_remediate, "db", db):
            restored = auto_remediate.recover_auto_closed_noops()

        self.assertEqual(restored, 0)
        db.select.assert_not_called()
        db.update.assert_not_called()

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
        # select order in run(): approvals(cards), tasks(SHELVED recover), tasks(backlog offload), tasks(blocked)
        db.select.side_effect = [[], [], [], [task]]
        db.update.side_effect = lambda table, match, patch: updates.append((table, match, patch))
        db.insert.side_effect = lambda table, row, **kw: inserts.append((table, row))

        with patch.object(auto_remediate, "db", db):
            result = auto_remediate.run()

        self.assertEqual(result["reclaimed"], 1)
        self.assertEqual(inserts, [])
        task_patch = next(p for table, _, p in updates if table == "tasks")
        self.assertEqual(task_patch["state"], "QUEUED")
        self.assertIn("agentic-repair:rework", task_patch["note"])

    def test_dependency_buildfail_requeued_after_prewarm(self):
        task = {
            "id": "t4",
            "slug": "nuxt-fix",
            "state": "BLOCKED",
            "prompt": "Fix Nuxt build.",
            "note": "integrate BUILDFAIL — production build red; sh: nuxt: command not found",
            "remediation_count": 0,
            "model": "claude-sonnet-4-6",
            "material": False,
            "project_id": "p1",
            "build_fail_count": 2,
            "force_coder": "gemini",
        }
        updates = []
        db = MagicMock()
        db.select.side_effect = [[], [], [], [task]]
        db.update.side_effect = lambda table, match, patch: updates.append((table, match, patch))

        with patch.object(auto_remediate, "db", db):
            result = auto_remediate.run()

        self.assertEqual(result["requeued"], 1)
        task_patch = next(p for table, _, p in updates if table == "tasks")
        self.assertEqual(task_patch["state"], "QUEUED")
        self.assertEqual(task_patch["build_fail_count"], 0)
        self.assertEqual(task_patch["force_coder"], "gemini")
        self.assertIn("Dependency prewarm", task_patch["prompt"])

    def test_budget_guard_blocked_task_forces_non_claude_failover(self):
        task = {
            "id": "t5",
            "slug": "budgeted",
            "state": "BLOCKED",
            "prompt": "Finish the implementation.",
            "note": "budget guard converted to subscription/failover route",
            "remediation_count": 1,
            "model": "claude-sonnet-4-6",
            "material": False,
            "project_id": "p1",
        }
        updates = []
        db = MagicMock()
        db.select.side_effect = [[], [], [], [task]]
        db.update.side_effect = lambda table, match, patch: updates.append((table, match, patch))

        with patch.object(auto_remediate, "db", db), \
             patch.object(auto_remediate.agentic_repair, "choose_coder", return_value="ollama"), \
             patch.object(auto_remediate, "_non_claude_coder", return_value="ollama"):
            result = auto_remediate.run()

        self.assertEqual(result["requeued"], 1)
        task_patch = updates[-1][2]
        self.assertEqual(task_patch["state"], "QUEUED")
        self.assertEqual(task_patch["force_coder"], "ollama")
        self.assertEqual(task_patch["model"], "ollama")
        self.assertIn("non-Claude failover", task_patch["note"])

    def test_backlog_budget_capacity_rows_are_offloaded_from_claude(self):
        task = {
            "id": "t6",
            "slug": "capacity-row",
            "state": "QUEUED",
            "prompt": "Finish the implementation.",
            "note": "capacity circuit -> failover route",
            "model": "claude-haiku-4-5-20251001",
            "material": False,
        }
        updates = []
        db = MagicMock()
        db.select.return_value = [task]
        db.update.side_effect = lambda table, match, patch: updates.append((table, match, patch))

        with patch.object(auto_remediate, "db", db), \
             patch.object(auto_remediate.agentic_repair, "choose_coder", return_value="ollama"), \
             patch.object(auto_remediate, "_non_claude_coder", return_value="ollama"):
            changed = auto_remediate.offload_budget_capacity_backlog()

        self.assertEqual(changed, 1)
        patch_row = updates[0][2]
        self.assertEqual(patch_row["force_coder"], "ollama")
        self.assertEqual(patch_row["model"], "ollama")
        self.assertEqual(patch_row["state"], "QUEUED")

    def test_mock_api_key_mentions_do_not_create_human_hold(self):
        task = {
            "slug": "mock-default-mode",
            "prompt": "- legal gate: owner-only when a secret is needed\nImplement mock mode.",
            "log_tail": "Mock mode runs unless DARWIN_LIVE=1 and DARWIN_API_KEY are both set.",
        }
        self.assertFalse(auto_remediate._requires_human_hold(task, "agent produced no committable changes"))
        self.assertTrue(auto_remediate._requires_human_hold(task, "missing api key required for this task"))

    def test_non_claude_failover_prefers_zero_cost_local(self):
        coders = [
            {"name": "claude", "cost": 1, "cap": 10},
            {"name": "codex", "cost": 1, "cap": 8},
            {"name": "ollama", "cost": 0, "cap": 9},
        ]
        fake_agentic = MagicMock()
        fake_agentic._pool.return_value = coders
        fake_agentic._within_cap.return_value = True
        fake_agentic._allowed_by_terms.return_value = True
        fake_agentic._task_sensitivity.return_value = "standard"

        with patch.dict(sys.modules, {"agentic_coders": fake_agentic}):
            auto_remediate._NON_CLAUDE_CACHE = {"t": 0.0, "coder": None}
            self.assertEqual(auto_remediate._non_claude_coder({"prompt": "x"}), "ollama")

    def test_hard_cap_task_is_decomposed_into_subtasks(self):
        """BLOCKED task at HARD_CAP that isn't already decomposed should spawn sub-tasks."""
        task = {
            "id": "t-hard",
            "slug": "big-feature",
            "state": "BLOCKED",
            "prompt": "Implement a very large feature with many components.",
            "note": "quality gate: too many failures",
            "remediation_count": auto_remediate.HARD_CAP,
            "model": "claude-sonnet-4-6",
            "material": False,
            "project_id": "p1",
            "base_branch": "main",
        }
        updates = []
        db_mock = MagicMock()
        db_mock.select.side_effect = [[], [], [], [task]]
        db_mock.update.side_effect = lambda table, match, patch: updates.append((table, match, patch))

        with patch.object(auto_remediate, "db", db_mock), \
             patch.object(auto_remediate, "_decompose", return_value=[
                 {"title": "part-one", "prompt": "Implement step one."},
                 {"title": "part-two", "prompt": "Implement step two."},
             ]), \
             patch.object(auto_remediate, "_spawn_subtasks", return_value=2):
            result = auto_remediate.run()

        self.assertEqual(result["decomposed"], 1)
        task_patch = next(p for table, _, p in updates if table == "tasks")
        self.assertEqual(task_patch["state"], "DECOMPOSED")
        self.assertIn("auto-split", task_patch["note"])

    def test_already_decomposed_task_at_hard_cap_is_shelved(self):
        """BLOCKED task at HARD_CAP that IS already decomposed must be shelved, not re-decomposed."""
        task = {
            "id": "t-sub",
            "slug": "big-feature-part-one",
            "state": "BLOCKED",
            "prompt": "Implement step one.",
            "note": "auto-decomposed from big-feature; quality gate: still failing",
            "remediation_count": auto_remediate.HARD_CAP,
            "model": "claude-sonnet-4-6",
            "material": False,
            "project_id": "p1",
        }
        updates = []
        db_mock = MagicMock()
        db_mock.select.side_effect = [[], [], [], [task]]
        db_mock.update.side_effect = lambda table, match, patch: updates.append((table, match, patch))

        with patch.object(auto_remediate, "db", db_mock):
            result = auto_remediate.run()

        self.assertEqual(result["shelved"], 1)
        task_patch = next(p for table, _, p in updates if table == "tasks")
        self.assertEqual(task_patch["state"], "SHELVED")

    def test_already_decomposed_recognizes_note_marker(self):
        self.assertTrue(auto_remediate._already_decomposed(
            {"slug": "child-task"}, "auto-decomposed from parent-slug"))
        self.assertFalse(auto_remediate._already_decomposed(
            {"slug": "original-task"}, "some other note"))

    def test_already_decomposed_recognizes_multi_part_slug(self):
        self.assertTrue(auto_remediate._already_decomposed(
            {"slug": "parent-part-one-part-two"}, ""))
        self.assertFalse(auto_remediate._already_decomposed(
            {"slug": "parent-part-one"}, ""))


if __name__ == "__main__":
    unittest.main()
