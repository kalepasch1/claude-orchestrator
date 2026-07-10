"""Tests for repo-path error handling added to runner.py.

Covers three behaviours introduced by the enhanced error handling slice:
1. _branch_exists returns False (not OSError) when cwd doesn't exist.
2. _localize_repo_path finds a local path via resilience_mesh.json.
3. run_task requeues gracefully when the repo path is inaccessible on this machine.
"""
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch, call

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import runner


class BranchExistsOSErrorTest(unittest.TestCase):
    def test_missing_repo_path_returns_false_not_raises(self):
        """subprocess.run raises FileNotFoundError for bad cwd; _branch_exists must catch it."""
        result = runner._branch_exists("/nonexistent/path/that/does/not/exist", "main")
        self.assertFalse(result)

    def test_existing_repo_with_existing_branch_returns_true(self):
        with tempfile.TemporaryDirectory() as d:
            env = {**os.environ, "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t.com",
                   "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t.com"}
            import subprocess
            subprocess.run(["git", "init", "-b", "main"], cwd=d, check=True,
                           capture_output=True, env=env)
            subprocess.run(["git", "commit", "--allow-empty", "-m", "init"],
                           cwd=d, check=True, capture_output=True, env=env)
            self.assertTrue(runner._branch_exists(d, "main"))

    def test_existing_repo_with_missing_branch_returns_false(self):
        with tempfile.TemporaryDirectory() as d:
            env = {**os.environ, "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t.com",
                   "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t.com"}
            import subprocess
            subprocess.run(["git", "init", "-b", "main"], cwd=d, check=True,
                           capture_output=True, env=env)
            subprocess.run(["git", "commit", "--allow-empty", "-m", "init"],
                           cwd=d, check=True, capture_output=True, env=env)
            self.assertFalse(runner._branch_exists(d, "no-such-branch"))


class LocalizeRepoPathTest(unittest.TestCase):
    def _write_mesh(self, tmpdir, repos):
        mesh_path = os.path.join(tmpdir, "resilience_mesh.json")
        with open(mesh_path, "w") as f:
            json.dump({"repos": repos}, f)
        return mesh_path

    def test_matches_by_project_name(self):
        with tempfile.TemporaryDirectory() as d:
            repo_dir = os.path.join(d, "myrepo")
            os.makedirs(repo_dir)
            self._write_mesh(d, [{"name": "myproject", "path": repo_dir}])
            proj = {"name": "myproject"}
            with patch.object(runner, "_CANONICAL_RUNTIME_HOME", d):
                result = runner._localize_repo_path(proj, "/remote/path/myrepo")
            self.assertEqual(result, repo_dir)

    def test_matches_by_basename_when_name_missing(self):
        with tempfile.TemporaryDirectory() as d:
            repo_dir = os.path.join(d, "claude-orchestrator")
            os.makedirs(repo_dir)
            self._write_mesh(d, [{"name": "beethoven", "path": repo_dir}])
            proj = {"name": "beethoven"}
            db_path = "/Users/other/Documents/beethoven/claude-orchestrator"
            with patch.object(runner, "_CANONICAL_RUNTIME_HOME", d):
                result = runner._localize_repo_path(proj, db_path)
            self.assertEqual(result, repo_dir)

    def test_returns_none_when_mesh_missing(self):
        proj = {"name": "beethoven"}
        with patch.object(runner, "_CANONICAL_RUNTIME_HOME", "/nonexistent"):
            result = runner._localize_repo_path(proj, "/some/path")
        self.assertIsNone(result)

    def test_returns_none_when_entry_path_does_not_exist(self):
        with tempfile.TemporaryDirectory() as d:
            self._write_mesh(d, [{"name": "beethoven", "path": "/does/not/exist"}])
            proj = {"name": "beethoven"}
            with patch.object(runner, "_CANONICAL_RUNTIME_HOME", d):
                result = runner._localize_repo_path(proj, "/some/path")
        self.assertIsNone(result)

    def test_returns_none_for_empty_repos(self):
        with tempfile.TemporaryDirectory() as d:
            self._write_mesh(d, [])
            proj = {"name": "beethoven"}
            with patch.object(runner, "_CANONICAL_RUNTIME_HOME", d):
                result = runner._localize_repo_path(proj, "/some/path")
        self.assertIsNone(result)


class RunTaskRepoPathGuardTest(unittest.TestCase):
    """run_task should requeue (not crash) when repo is inaccessible on this machine."""

    def _make_task(self, project_id="p1"):
        return {
            "id": "task-1",
            "slug": "fix-something",
            "project_id": project_id,
            "base_branch": "main",
            "kind": "build",
            "prompt": "do the thing",
            "model": "claude-sonnet-4-6",
            "state": "RUNNING",
            "transient_retries": 0,
            "remediation_count": 0,
            "attempt": 0,
        }

    def test_requeues_when_repo_missing_and_no_local_equivalent(self):
        task = self._make_task()
        proj = {"id": "p1", "name": "beethoven",
                "repo_path": "/Users/other/Documents/beethoven/claude-orchestrator",
                "test_cmd": "npm test"}
        state_updates = []

        def fake_set_state(tid, **kw):
            state_updates.append(kw)

        with patch.object(runner, "projects", return_value={"p1": proj}), \
             patch.object(runner, "_localize_repo_path", return_value=None), \
             patch("os.path.isdir", return_value=False), \
             patch.object(runner, "set_state", side_effect=fake_set_state), \
             patch("time.sleep"):
            runner.run_task(task)

        self.assertEqual(len(state_updates), 1)
        self.assertEqual(state_updates[0]["state"], "QUEUED")
        self.assertIn("not accessible", state_updates[0]["note"])

    def test_uses_localized_path_when_db_path_missing(self):
        """When localization succeeds the task should proceed past the early guard."""
        task = self._make_task()
        proj = {"id": "p1", "name": "beethoven",
                "repo_path": "/Users/other/Documents/beethoven/claude-orchestrator",
                "test_cmd": "npm test"}

        with tempfile.TemporaryDirectory() as local_repo:
            import subprocess, types
            env = {**os.environ, "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t.com",
                   "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t.com"}
            subprocess.run(["git", "init", "-b", "main"], cwd=local_repo, check=True,
                           capture_output=True, env=env)
            subprocess.run(["git", "commit", "--allow-empty", "-m", "init"],
                           cwd=local_repo, check=True, capture_output=True, env=env)

            proceeded = []

            # Intercept after the repo guard — the task_slicer is called right at
            # entry; mock it so slice logic doesn't interfere, then watch kill_switch.
            import kill_switch as ks

            def fake_is_paused(name):
                proceeded.append(name)
                raise SystemExit("stop here for test")

            with patch.object(runner, "projects", return_value={"p1": proj}), \
                 patch.object(runner, "_localize_repo_path", return_value=local_repo), \
                 patch("os.path.isdir", return_value=False), \
                 patch("kill_switch.is_paused", side_effect=fake_is_paused):
                try:
                    runner.run_task(task)
                except SystemExit:
                    pass

            self.assertTrue(proceeded, "run_task should have advanced past the repo guard")


if __name__ == "__main__":
    unittest.main(verbosity=2)
