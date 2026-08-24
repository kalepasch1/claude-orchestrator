"""Tests for repo-path error handling in runner.py.

Covers three behaviours of the repo-path resilience slice:
1. _branch_exists returns False (not OSError) when cwd doesn't exist.
2. _localize_repo_path finds a local path via resilience_mesh.json.
3. run_task requeues gracefully when the repo path is inaccessible on this machine.

IMPORT FIX 2026-08-24. This file used to do a bare `import runner` and then reach for
runner._branch_exists / _localize_repo_path / _CANONICAL_RUNTIME_HOME / projects. All ten
tests failed with AttributeError, because `import runner` resolves to the runner/ PACKAGE
(runner/__init__.py), not to runner.py — the package exports none of those names. The
functions under test are real and unchanged; only the way they were reached was wrong.
runner.py is loaded from its file under a private module name, the same way
test_lean_mode.py and test_model_routing.py already do it, so nothing here depends on the
package name and no second runner instance is started (the singleton lock and the
maintenance-lock check live under `if __name__ == "__main__"`).
"""
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

_RUNNER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _RUNNER_DIR)

_RUNNER_SPEC = importlib.util.spec_from_file_location(
    "runner_entrypoint_repo_path", os.path.join(_RUNNER_DIR, "runner.py"))
runner = importlib.util.module_from_spec(_RUNNER_SPEC)
_RUNNER_SPEC.loader.exec_module(runner)


def _git_repo(path):
    """Init a repo with one empty commit on `main`, independent of the host git config."""
    import subprocess
    env = {**os.environ, "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t.com",
           "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t.com"}
    subprocess.run(["git", "init", "-b", "main"], cwd=path, check=True,
                   capture_output=True, env=env, timeout=30)
    subprocess.run(["git", "commit", "--allow-empty", "-m", "init"],
                   cwd=path, check=True, capture_output=True, env=env, timeout=30)


class BranchExistsOSErrorTest(unittest.TestCase):
    def test_missing_repo_path_returns_false_not_raises(self):
        """subprocess.run raises FileNotFoundError for a bad cwd; _branch_exists catches it.

        This is the whole point of the try/except OSError in _branch_exists: the caller
        (_normalize_task_base) runs it against a repo path that may belong to another
        machine, and an exception there aborts the poll instead of requeuing the task.
        """
        result = runner._branch_exists("/nonexistent/path/that/does/not/exist", "main")
        self.assertFalse(result)

    def test_empty_branch_name_is_false_without_shelling_out(self):
        # Added with the import fix: _branch_exists short-circuits on a falsy branch
        # before touching git, which is what keeps `git rev-parse --verify ''` (an error
        # exit that also writes to stderr) out of the hot path.
        import subprocess
        with patch.object(subprocess, "run", side_effect=AssertionError("must not shell out")):
            self.assertFalse(runner._branch_exists("/tmp", ""))
            self.assertFalse(runner._branch_exists("/tmp", None))

    def test_existing_repo_with_existing_branch_returns_true(self):
        with tempfile.TemporaryDirectory() as d:
            _git_repo(d)
            self.assertTrue(runner._branch_exists(d, "main"))

    def test_existing_repo_with_missing_branch_returns_false(self):
        with tempfile.TemporaryDirectory() as d:
            _git_repo(d)
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

    def test_name_match_is_case_insensitive(self):
        # Added with the import fix: both sides are lower()ed before comparison, which is
        # what lets a mesh written by a machine that registered "Beethoven" serve a
        # project row that says "beethoven".
        with tempfile.TemporaryDirectory() as d:
            repo_dir = os.path.join(d, "clone")
            os.makedirs(repo_dir)
            self._write_mesh(d, [{"name": "Beethoven", "path": repo_dir}])
            with patch.object(runner, "_CANONICAL_RUNTIME_HOME", d):
                self.assertEqual(
                    runner._localize_repo_path({"name": "beethoven"}, "/remote/elsewhere"),
                    repo_dir)

    def test_matches_by_basename_when_name_missing(self):
        with tempfile.TemporaryDirectory() as d:
            repo_dir = os.path.join(d, "claude-orchestrator")
            os.makedirs(repo_dir)
            # The mesh entry's name does NOT match the project name, so the only way
            # through is the basename fallback: .../claude-orchestrator on both sides.
            self._write_mesh(d, [{"name": "some-other-name", "path": repo_dir}])
            proj = {"name": "beethoven"}
            db_path = "/Users/other/Documents/beethoven/claude-orchestrator"
            with patch.object(runner, "_CANONICAL_RUNTIME_HOME", d):
                result = runner._localize_repo_path(proj, db_path)
            self.assertEqual(result, repo_dir)

    def test_unrelated_entry_is_not_borrowed(self):
        # Added with the import fix. The two positive cases above are both satisfied by a
        # function that returns the first existing directory in the mesh; this pins that
        # a repo matching on neither name nor basename is rejected, which is what stops a
        # task being run against somebody else's checkout.
        with tempfile.TemporaryDirectory() as d:
            repo_dir = os.path.join(d, "unrelated")
            os.makedirs(repo_dir)
            self._write_mesh(d, [{"name": "unrelated", "path": repo_dir}])
            with patch.object(runner, "_CANONICAL_RUNTIME_HOME", d):
                self.assertIsNone(
                    runner._localize_repo_path({"name": "beethoven"}, "/remote/beethoven/orch"))

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

    def test_corrupt_mesh_returns_none_rather_than_raising(self):
        # Added with the import fix: the blanket `except Exception: pass` is documented
        # fail-soft behaviour, and a half-written mesh file is the realistic way to hit
        # it (resilience_mesh.py rewrites the file in place on every tick).
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "resilience_mesh.json"), "w") as f:
                f.write('{"repos": [{"name": "beeth')
            with patch.object(runner, "_CANONICAL_RUNTIME_HOME", d):
                self.assertIsNone(runner._localize_repo_path({"name": "beethoven"}, "/p"))


class _StopAfterRepoGuard(Exception):
    """Raised from the first call after the repo guard, to end run_task there."""


class RunTaskRepoPathGuardTest(unittest.TestCase):
    """run_task should requeue (not crash) when the repo is inaccessible on this machine."""

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

    _PROJ = {"id": "p1", "name": "beethoven",
             "repo_path": "/Users/other/Documents/beethoven/claude-orchestrator",
             "test_cmd": "npm test"}

    def test_requeues_when_repo_missing_and_no_local_equivalent(self):
        task = self._make_task()
        state_updates = []

        def fake_set_state(tid, **kw):
            state_updates.append(kw)

        with patch.object(runner, "projects", return_value={"p1": self._PROJ}), \
             patch.object(runner, "_localize_repo_path", return_value=None), \
             patch.object(os.path, "isdir", return_value=False), \
             patch.object(runner, "set_state", side_effect=fake_set_state), \
             patch.object(runner.time, "sleep"):
            runner.run_task(task)

        self.assertEqual(len(state_updates), 1, state_updates)
        self.assertEqual(state_updates[0]["state"], "QUEUED")
        self.assertIn("not accessible", state_updates[0]["note"])
        # The note has to name the path, or an operator cannot tell which host holds the
        # clone — that is the entire reason this branch requeues instead of erroring.
        self.assertIn(self._PROJ["repo_path"], state_updates[0]["note"])

    def test_uses_localized_path_when_db_path_missing(self):
        """When localization succeeds, the localized path is what the task runs against.

        REWRITTEN 2026-08-24 (beyond the import fix). This used to patch
        kill_switch.is_paused to raise and then assert only that it had been reached —
        i.e. "run_task got past the guard", which a version of the guard that adopted the
        WRONG path would also satisfy. It also had to survive _normalize_task_base and
        _integration_base (a real `git fetch`) in between. Intercepting the first thing
        the guard hands the repo to asserts the substantive claim in the test's name.
        """
        task = self._make_task()
        seen = {}

        def stop(repo, proj, requested):
            seen["repo"] = repo
            seen["requested"] = requested
            raise _StopAfterRepoGuard()

        with tempfile.TemporaryDirectory() as local_repo:
            with patch.object(runner, "projects", return_value={"p1": self._PROJ}), \
                 patch.object(runner, "_localize_repo_path", return_value=local_repo), \
                 patch.object(os.path, "isdir", return_value=False), \
                 patch.object(runner, "set_state"), \
                 patch.object(runner, "_normalize_task_base", side_effect=stop), \
                 patch.object(runner.time, "sleep"):
                with self.assertRaises(_StopAfterRepoGuard):
                    runner.run_task(task)

            self.assertEqual(seen.get("repo"), local_repo)
            self.assertEqual(seen.get("requested"), "main")

    def test_localization_is_only_consulted_when_the_db_path_is_absent(self):
        # Added with the import fix: the guard is `if not os.path.isdir(repo)`. A repo
        # that IS present must not pay a mesh read (resilience_mesh.json is rewritten
        # every 60s, so reading it on every task is both wasted I/O and a race).
        task = self._make_task()

        def stop(repo, proj, requested):
            raise _StopAfterRepoGuard()

        with patch.object(runner, "projects", return_value={"p1": self._PROJ}), \
             patch.object(runner, "_localize_repo_path",
                          side_effect=AssertionError("mesh consulted for a present repo")), \
             patch.object(os.path, "isdir", return_value=True), \
             patch.object(runner, "set_state"), \
             patch.object(runner, "_normalize_task_base", side_effect=stop), \
             patch.object(runner.time, "sleep"):
            with self.assertRaises(_StopAfterRepoGuard):
                runner.run_task(task)


if __name__ == "__main__":
    unittest.main(verbosity=2)
