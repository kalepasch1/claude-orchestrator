             patch.object(auto_remediate, "recover_pending_manual_reviews", return_value=0), \
             patch.object(auto_remediate, "recover_auto_closed_noops", return_value=0), \
             patch.object(auto_remediate, "recover_shelved", return_value=(0, 0)), \
             patch.object(auto_remediate, "offload_budget_capacity_backlog", return_value=0), \
             patch.object(auto_remediate, "_already_decomposed", return_value=True):
            auto_remediate.run(limit=1)

        self.assertIn(updates.get("state"), ("SHELVED", "DECOMPOSED"))

    # --- DONE (auto-closed no-op) -> QUEUED ---
    def test_auto_closed_noop_recovered_to_queued(self):
        t = self._make_task(state="DONE", note="auto-closed: no committable work after retry")
        updates = []
        db = MagicMock()
        db.select.return_value = [t]
        db.update.side_effect = lambda table, match, patch: updates.append(patch)

        with patch.dict(os.environ, {"ORCH_RECOVER_AUTO_CLOSED_NOOPS": "true"}), \
             patch.object(auto_remediate, "db", db):
            restored = auto_remediate.recover_auto_closed_noops()

        self.assertEqual(restored, 1)
        self.assertEqual(updates[0]["state"], "QUEUED")


class TaskStateInvariantsTest(unittest.TestCase):
    """Structural invariants that should always hold."""

    def test_remediation_count_never_negative(self):
        """remediation_count must be >= 0 after any transition."""
        t = {
            "id": "t-neg", "slug": "neg-test", "state": "BLOCKED",
            "prompt": "Fix bug.", "note": "timeout error",
            "model": "claude-sonnet-4-6", "remediation_count": 0,
            "material": False, "project_id": "proj-1",
            "base_branch": "main", "log_tail": "",
        }
        updates = {}
        db = MagicMock()
        db.select.return_value = [t]
        db.update.side_effect = lambda table, match, patch: updates.update(patch)

        with patch.object(auto_remediate, "db", db), \
             patch.object(auto_remediate, "recover_pending_manual_reviews", return_value=0), \
             patch.object(auto_remediate, "recover_auto_closed_noops", return_value=0), \
             patch.object(auto_remediate, "recover_shelved", return_value=(0, 0)), \
             patch.object(auto_remediate, "offload_budget_capacity_backlog", return_value=0):
            auto_remediate.run(limit=1)

        self.assertGreaterEqual(updates.get("remediation_count", 0), 0)

    def test_hard_cap_constant_is_greater_than_cap(self):
        """HARD_CAP must always exceed CAP to give the escalation ladder room."""
        self.assertGreater(auto_remediate.HARD_CAP, auto_remediate.CAP)


if __name__ == "__main__":
    unittest.main()
