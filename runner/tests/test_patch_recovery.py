"""Tests for patch_recovery.py — specifically the _template_adaptation bug fix.

Prior to this fix, _template_adaptation called _replay_stored_patch(repo, slug, branch, base)
after finding a best_match from merged artifacts. That looked up task_artifacts.get_patch(slug)
— the original missing task's patch — not the found similar diff. Since the original patch was
missing (that's why we're in recovery at all), method 3 always failed silently.

The fix routes through _apply_patch_to_branch(repo, patch, branch, base) with the found patch.
"""
import sys
import os
import types
import unittest
from unittest.mock import MagicMock, patch as mock_patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestTemplateAdaptationRouting(unittest.TestCase):
    """Verify _template_adaptation uses the found artifact's diff, not the original slug's patch."""

    def _make_module(self):
        """Import patch_recovery with db and task_artifacts mocked out."""
        import importlib
        import patch_recovery as pr
        return pr

    def _inject_task_artifacts(self, get_artifacts_fn):
        """Inject a mock task_artifacts module into sys.modules for tests."""
        mock_ta = MagicMock()
        mock_ta.get_artifacts.side_effect = get_artifacts_fn
        sys.modules["task_artifacts"] = mock_ta
        return mock_ta

    def test_template_adaptation_calls_apply_not_replay(self):
        """When a best_match is found, _apply_patch_to_branch should be called, not _replay_stored_patch."""
        import patch_recovery as pr

        found_diff = "diff --git a/foo.py b/foo.py\n--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-old\n+new\n"

        self._inject_task_artifacts(lambda slug: {
            "patch_diff": found_diff,
            "touched_files": '["widget/frob.py"]',
        })

        with mock_patch.object(pr, "db") as mock_db, \
             mock_patch.object(pr, "_replay_stored_patch") as mock_replay, \
             mock_patch.object(pr, "_apply_patch_to_branch") as mock_apply:

            # task row exists with a prompt using words that overlap with "widget frob"
            mock_db.select.side_effect = lambda table, q: (
                [{"prompt": "fix the widget frob handler"}] if table == "tasks" and "slug" in q
                else [{"slug": "other-task-merged"}] if table == "tasks"
                else []
            )
            mock_apply.return_value = {"ok": True, "method": "template", "branch": "agent/missing-slug"}

            result = pr._template_adaptation("/fake/repo", "missing-slug", "agent/missing-slug", "main")

            # _apply_patch_to_branch must be called with the found diff, never _replay_stored_patch
            mock_apply.assert_called_once()
            call_args = mock_apply.call_args
            self.assertEqual(call_args[0][1], found_diff,
                             "_apply_patch_to_branch must receive the found artifact diff, not the slug's patch")
            mock_replay.assert_not_called()
            self.assertTrue(result["ok"])

    def test_template_adaptation_no_match_returns_not_ok(self):
        """When no merged diff has keyword overlap >= 2, returns ok=False without calling recovery."""
        import patch_recovery as pr

        self._inject_task_artifacts(lambda slug: {
            "patch_diff": "some diff",
            "touched_files": '["totally_unrelated.py"]',
        })

        with mock_patch.object(pr, "db") as mock_db, \
             mock_patch.object(pr, "_apply_patch_to_branch") as mock_apply:

            mock_db.select.side_effect = lambda table, q: (
                [{"prompt": "completely different domain operation"}] if table == "tasks" and "slug" in q
                else [{"slug": "other"}] if table == "tasks"
                else []
            )

            result = pr._template_adaptation("/fake/repo", "missing-slug", "agent/missing-slug", "main")

            mock_apply.assert_not_called()
            self.assertFalse(result["ok"])
            self.assertIn("no similar", result.get("reason", ""))

    def test_apply_patch_to_branch_guards_missing_repo(self):
        """_apply_patch_to_branch returns ok=False when repo path doesn't exist."""
        import patch_recovery as pr

        result = pr._apply_patch_to_branch("/nonexistent/repo", "diff content", "agent/x", "main")
        self.assertFalse(result["ok"])
        self.assertIn("not accessible", result.get("reason", ""))


if __name__ == "__main__":
    unittest.main()
