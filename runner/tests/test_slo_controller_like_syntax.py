import os
import sys
import unittest
from unittest.mock import MagicMock, patch, call

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import slo_controller


class SloControllerLikeSyntaxTest(unittest.TestCase):
    """Verify PostgREST like filters use % wildcards, not * wildcards."""

    def _make_db(self, results=None):
        db = MagicMock()
        db.select.return_value = results or []
        db.insert.return_value = None
        return db

    def test_check_missing_branches_uses_percent_wildcard(self):
        db = self._make_db()
        with patch.object(slo_controller, "db", db):
            slo_controller._check_missing_branches()

        calls = db.select.call_args_list
        note_filters = [
            c.args[1].get("note", "") for c in calls if c.args[0] == "tasks"
        ]
        slug_filters = [
            c.args[1].get("slug", "") for c in calls if c.args[0] == "tasks"
        ]
        for f in note_filters:
            self.assertNotIn("*", f, f"note filter should use % not *: {f!r}")
        for f in slug_filters:
            if f:
                self.assertNotIn("*", f, f"slug filter should use % not *: {f!r}")
                if "recover-missing-branch" in f:
                    self.assertIn("%", f)

    def test_check_recovery_backlog_uses_percent_wildcard(self):
        db = self._make_db()
        with patch.object(slo_controller, "db", db):
            slo_controller._check_recovery_backlog()

        for c in db.select.call_args_list:
            slug = c.args[1].get("slug", "")
            if slug:
                self.assertNotIn("*", slug, f"slug filter should use % not *: {slug!r}")
                self.assertTrue(slug.endswith("%"), f"like slug filter should end with %: {slug!r}")

    def test_check_release_fix_age_uses_percent_wildcard(self):
        db = self._make_db()
        with patch.object(slo_controller, "db", db):
            slo_controller._check_release_fix_age()

        for c in db.select.call_args_list:
            slug = c.args[1].get("slug", "")
            if slug:
                self.assertNotIn("*", slug, f"slug filter should use % not *: {slug!r}")
                self.assertIn("%", slug)

    def test_apply_action_patch_recovery_uses_percent_wildcard(self):
        db = self._make_db()
        with patch.object(slo_controller, "db", db):
            slo_controller._apply_action({"action": "trigger_patch_recovery"})

        for c in db.select.call_args_list:
            note = c.args[1].get("note", "")
            if note:
                self.assertNotIn("*", note, f"note filter should use % not *: {note!r}")
                self.assertIn("%", note)


if __name__ == "__main__":
    unittest.main()
