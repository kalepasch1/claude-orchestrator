#!/usr/bin/env python3
"""Integration test: decomposition event -> automatic child branch creation.

missing-branch-auto-creator slice 3: when _spawn_subtasks finishes creating the
children of a decomposed task, each child's agent/<slug> branch must exist in
the project repo (created via git_auto_branch.ensure_branch_safe), named from
the decomposition result. Uses a real temporary git repo; db calls are stubbed.
"""
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _git(repo, *args):
    return subprocess.run(["git", "-C", repo] + list(args),
                          capture_output=True, text=True, check=False)


def _make_repo(tmp):
    repo = os.path.join(tmp, "proj")
    os.makedirs(repo)
    _git(repo, "init", "-b", "master")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t",
         "commit", "--allow-empty", "-m", "seed")
    return repo


PROMPT = ("Implement the widget parser module with validation and add unit tests "
          "covering malformed input, empty input, and the happy path end to end.")

TASK = {"id": "parent-1", "slug": "big-task", "project_id": "p-1",
        "base_branch": "master", "material": False, "prompt": PROMPT}

SUBS = [{"title": "parser-module", "prompt": PROMPT},
        {"title": "parser-tests", "prompt": PROMPT}]


class DecompositionCreatesBranches(unittest.TestCase):
    def _run_spawn(self, repo):
        import auto_remediate

        def fake_select(table, params=None):
            if table == "projects":
                return [{"repo_path": repo, "default_base": "master"}]
            return []  # no duplicate child slugs

        def fake_insert(table, row):
            return [{"id": f"id-{row['slug']}"}]

        with mock.patch.object(auto_remediate.db, "select", side_effect=fake_select), \
             mock.patch.object(auto_remediate.db, "insert", side_effect=fake_insert):
            return auto_remediate._spawn_subtasks(TASK, SUBS, return_ids=True)

    def test_decomposition_event_triggers_branch_creation(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = _make_repo(tmp)
            made, child_ids = self._run_spawn(repo)
            self.assertEqual(made, 2)
            self.assertEqual(len(child_ids), 2)
            out = _git(repo, "branch", "--list", "agent/*").stdout
            self.assertIn("agent/big-task-parser-module", out)
            self.assertIn("agent/big-task-parser-tests", out)

    def test_branch_names_derive_from_decomposition_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = _make_repo(tmp)
            self._run_spawn(repo)
            for s in SUBS:
                branch = f"agent/{TASK['slug']}-{s['title']}"
                rc = _git(repo, "rev-parse", "--verify", branch).returncode
                self.assertEqual(rc, 0, f"{branch} missing")

    def test_missing_repo_is_fail_soft(self):
        import auto_remediate
        with mock.patch.object(auto_remediate.db, "select",
                               side_effect=lambda t, p=None:
                               [{"repo_path": "/nonexistent/nope", "default_base": "master"}]
                               if t == "projects" else []), \
             mock.patch.object(auto_remediate.db, "insert",
                               side_effect=lambda t, r: [{"id": "x"}]):
            made, ids = auto_remediate._spawn_subtasks(TASK, SUBS, return_ids=True)
        self.assertEqual(made, 2)  # task creation unaffected by branch failure


if __name__ == "__main__":
    unittest.main()
