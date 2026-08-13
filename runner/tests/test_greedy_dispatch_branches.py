#!/usr/bin/env python3
"""Missing-branch auto-creator: greedy_dispatch pre-creates agent/<slug>
branches for freshly decomposed children (fail-soft, advisory)."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import greedy_dispatch as gd


PARENT = {"id": "p1", "project_id": "proj1", "slug": "parent-task"}


def _db_select(projects_row, task_slugs):
    """Fake db.select covering the two tables the helper reads."""
    def select(table, params):
        if table == "projects":
            return [projects_row] if projects_row else []
        if table == "tasks":
            slug = task_slugs.get(params.get("id"))
            return [{"id": params["id"], "slug": slug}] if slug is not None else []
        return []
    return select


class TestEnsureChildBranches(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.repo = self.tmpdir.name
        self.gab = mock.Mock()
        self.gab.ensure_branch = mock.Mock(side_effect=lambda repo, slug, base: f"agent/{slug}")

    def tearDown(self):
        self.tmpdir.cleanup()

    def _run(self, projects_row, task_slugs, child_ids):
        with mock.patch.dict(sys.modules, {"git_auto_branch": self.gab}):
            with mock.patch.object(gd.db, "select", side_effect=_db_select(projects_row, task_slugs)):
                return gd._ensure_child_branches(PARENT, child_ids)

    def test_creates_branch_per_child(self):
        proj = {"repo_path": self.repo, "default_base": "develop"}
        created = self._run(proj, {"c1": "slice-1", "c2": "slice-2"}, ["c1", "c2"])
        self.assertEqual(created, 2)
        self.gab.ensure_branch.assert_has_calls([
            mock.call(self.repo, "slice-1", "develop"),
            mock.call(self.repo, "slice-2", "develop"),
        ])

    def test_no_repo_path_skips(self):
        created = self._run({"default_base": "master"}, {"c1": "slice-1"}, ["c1"])
        self.assertEqual(created, 0)
        self.gab.ensure_branch.assert_not_called()

    def test_nonexistent_repo_dir_skips(self):
        proj = {"repo_path": os.path.join(self.repo, "does-not-exist")}
        created = self._run(proj, {"c1": "slice-1"}, ["c1"])
        self.assertEqual(created, 0)
        self.gab.ensure_branch.assert_not_called()

    def test_base_falls_back_to_parent_then_master(self):
        parent = dict(PARENT, base_branch="release")
        with mock.patch.dict(sys.modules, {"git_auto_branch": self.gab}):
            with mock.patch.object(gd.db, "select",
                                   side_effect=_db_select({"repo_path": self.repo}, {"c1": "s1"})):
                gd._ensure_child_branches(parent, ["c1"])
        self.gab.ensure_branch.assert_called_once_with(self.repo, "s1", "release")

        self.gab.ensure_branch.reset_mock()
        self._run({"repo_path": self.repo}, {"c1": "s1"}, ["c1"])
        self.gab.ensure_branch.assert_called_once_with(self.repo, "s1", "master")

    def test_child_without_slug_skipped(self):
        proj = {"repo_path": self.repo}
        created = self._run(proj, {"c1": "slice-1"}, ["c1", "c2-no-row"])
        self.assertEqual(created, 1)
        self.assertEqual(self.gab.ensure_branch.call_count, 1)

    def test_failed_creation_not_counted(self):
        self.gab.ensure_branch.side_effect = lambda repo, slug, base: None
        created = self._run({"repo_path": self.repo}, {"c1": "slice-1"}, ["c1"])
        self.assertEqual(created, 0)

    def test_db_error_is_fail_soft(self):
        with mock.patch.dict(sys.modules, {"git_auto_branch": self.gab}):
            with mock.patch.object(gd.db, "select", side_effect=RuntimeError("db down")):
                created = gd._ensure_child_branches(PARENT, ["c1"])  # must not raise
        self.assertEqual(created, 0)

    def test_broken_git_auto_branch_import_is_fail_soft(self):
        # sys.modules[name] = None makes `import git_auto_branch` raise ImportError
        with mock.patch.dict(sys.modules, {"git_auto_branch": None}):
            with mock.patch.object(gd.db, "select",
                                   side_effect=_db_select({"repo_path": self.repo}, {"c1": "s1"})):
                created = gd._ensure_child_branches(PARENT, ["c1"])  # must not raise
        self.assertEqual(created, 0)


class TestDecompositionHookWiring(unittest.TestCase):

    def test_on_decomposition_complete_invokes_branch_creation(self):
        with mock.patch.object(gd, "dispatch_immediate", return_value=2) as dispatch, \
             mock.patch.object(gd, "_ensure_child_branches") as ensure, \
             mock.patch.object(gd, "_use_greedy_routing", return_value=False), \
             mock.patch.object(gd.db, "insert"):
            result = gd.on_decomposition_complete(PARENT, ["c1", "c2"])
        self.assertEqual(result, 2)
        dispatch.assert_called_once_with(["c1", "c2"], "proj1")
        ensure.assert_called_once_with(PARENT, ["c1", "c2"])


if __name__ == "__main__":
    unittest.main()
