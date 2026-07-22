"""Tests for deploy_verify._attribute_deploy_to_outcomes.

Verifies that a confirmed Vercel READY state triggers deployed=True writes
back to the outcomes rows that were integrated into that project.
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, call, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import deploy_verify


class AttributeDeployToOutcomesTest(unittest.TestCase):

    def _run(self, project, select_rows, *, raises=False):
        mock_db = MagicMock()
        if raises:
            mock_db.select.side_effect = Exception("column does not exist")
        else:
            mock_db.select.return_value = select_rows
        updates = []
        mock_db.update.side_effect = lambda t, m, p: updates.append((t, m, p))
        with patch.object(deploy_verify, "db", mock_db):
            deploy_verify._attribute_deploy_to_outcomes(project)
        return mock_db, updates

    def test_marks_integrated_outcomes_deployed(self):
        rows = [{"slug": "foo-abc"}, {"slug": "bar-def"}]
        _, updates = self._run("myproject", rows)
        self.assertEqual(len(updates), 2)
        for t, m, p in updates:
            self.assertEqual(t, "outcomes")
            self.assertEqual(m["project"], "myproject")
            self.assertTrue(p["deployed"])
            self.assertEqual(p["deploy_status"], "success")
        slugs = {u[1]["slug"] for u in updates}
        self.assertEqual(slugs, {"foo-abc", "bar-def"})

    def test_select_uses_integrated_filter(self):
        mock_db, _ = self._run("proj", [])
        call_params = mock_db.select.call_args[0][1]
        self.assertEqual(call_params["integrated"], "eq.true")
        self.assertEqual(call_params["deployed"], "is.false")
        self.assertEqual(call_params["project"], "eq.proj")

    def test_skips_rows_without_slug(self):
        rows = [{"slug": None}, {"slug": ""}, {"slug": "good-slug"}]
        _, updates = self._run("proj", rows)
        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0][1]["slug"], "good-slug")

    def test_fail_soft_on_missing_columns(self):
        # If the schema migration hasn't run yet, select raises — must not propagate.
        _, updates = self._run("proj", [], raises=True)
        self.assertEqual(updates, [])

    def test_empty_project_does_nothing(self):
        _, updates = self._run("proj", [])
        self.assertEqual(updates, [])

    def test_individual_update_failure_does_not_abort_loop(self):
        mock_db = MagicMock()
        mock_db.select.return_value = [{"slug": "a"}, {"slug": "b"}, {"slug": "c"}]
        call_count = [0]

        def flaky_update(t, m, p):
            call_count[0] += 1
            if m["slug"] == "b":
                raise Exception("transient error")

        mock_db.update.side_effect = flaky_update
        with patch.object(deploy_verify, "db", mock_db):
            deploy_verify._attribute_deploy_to_outcomes("proj")
        # All three slugs attempted despite the middle one failing
        self.assertEqual(call_count[0], 3)


if __name__ == "__main__":
    unittest.main()
