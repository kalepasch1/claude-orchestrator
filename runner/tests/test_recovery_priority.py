"""Tests for recovery/train-approved/build-fix queue prioritization."""
import unittest


class TestRecoveryPriority(unittest.TestCase):

    def _make_task(self, slug, note="", kind="build", priority=1000, created_at="2026-01-01T00:00:00Z"):
        return {"id": slug, "slug": slug, "note": note, "kind": kind,
                "priority": priority, "project_id": "p1", "created_at": created_at,
                "confidence": 0.5}

    def test_recovery_task_detected(self):
        from runner.db import _is_recovery_task
        self.assertTrue(_is_recovery_task(self._make_task("recover-missing-branch-foo")))
        self.assertFalse(_is_recovery_task(self._make_task("add-feature-bar")))

    def test_release_fix_includes_buildfix(self):
        from runner.db import _is_release_fix_task
        self.assertTrue(_is_release_fix_task(self._make_task("buildfix-tomorrow-abc123")))

    def test_release_fix_includes_qafix(self):
        from runner.db import _is_release_fix_task
        self.assertTrue(_is_release_fix_task(self._make_task("qafix-beethoven-def456")))

    def test_train_approved_note_detected(self):
        approved = self._make_task("some-task", note="train: passed on orchestrator/dev")
        generic = self._make_task("other-task", note="queued by miner")
        self.assertIn("train: passed", approved["note"].lower())
        self.assertNotIn("train: passed", generic["note"].lower())

    def test_recovery_reserved_lanes_default_is_one(self):
        import os
        old = os.environ.pop("ORCH_RECOVERY_RESERVED_LANES", None)
        try:
            lanes = max(0, int(os.environ.get("ORCH_RECOVERY_RESERVED_LANES", "1") or 0))
            self.assertEqual(lanes, 1)
        finally:
            if old is not None:
                os.environ["ORCH_RECOVERY_RESERVED_LANES"] = old


if __name__ == "__main__":
    unittest.main()
