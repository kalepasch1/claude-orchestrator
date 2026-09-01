"""A generic stored base_branch must not outrank projects.default_base.

2026-09-01. db._guard_task_base_branch rewrites a generic "main"/"master" to the
project's default_base, but it is insert-only. _normalize_task_base then checked the
*stored* value first, so any row written by an unguarded path -- or written before the
default changed -- was sent back to the production branch at execution time. With the
fleet consolidating onto orchestrator/dev, that is the difference between one shared
development branch and the three-way main/master/dev split that produced 1,237 tasks
cut against a branch that no longer existed.

Deliberate, non-generic bases (release/*, hotfix/*) must still win, or a release lane
would silently be dragged onto dev.
"""
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest

RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RUNNER)


def _load(name, fname):
    spec = importlib.util.spec_from_file_location(name, os.path.join(RUNNER, fname))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


runner = _load("_runner_sdb", "runner.py")
prewarm = _load("_prewarm_sdb", "prewarm.py")


def _git(repo, *a):
    return subprocess.run(["git", *a], cwd=repo, capture_output=True, text=True, timeout=30)


def _repo_with(branches, prod="main"):
    d = tempfile.mkdtemp(prefix="strictbase-")
    _git(d, "init", "-q", "-b", prod)
    _git(d, "config", "user.email", "t@t.t")
    _git(d, "config", "user.name", "t")
    with open(os.path.join(d, "f.txt"), "w") as fh:
        fh.write("x")
    _git(d, "add", "-A")
    _git(d, "commit", "-m", "base", "--no-gpg-sign")
    for b in branches:
        if b != prod:
            _git(d, "branch", b)
    return d


PROJ = {"default_base": "orchestrator/dev", "prod_branch": "main"}


class StrictDefaultBaseTests(unittest.TestCase):
    def setUp(self):
        self.prev = os.environ.pop("ORCH_STRICT_DEFAULT_BASE", None)
        self.repo = _repo_with(["main", "orchestrator/dev", "release/2026-09"])

    def tearDown(self):
        os.environ.pop("ORCH_STRICT_DEFAULT_BASE", None)
        if self.prev is not None:
            os.environ["ORCH_STRICT_DEFAULT_BASE"] = self.prev

    def test_stored_main_yields_to_default_base(self):
        self.assertEqual(
            runner._normalize_task_base(self.repo, PROJ, "main"), "orchestrator/dev",
            "a stored generic 'main' still outranks the project default")

    def test_stored_master_yields_to_default_base(self):
        self.assertEqual(runner._normalize_task_base(self.repo, PROJ, "master"),
                         "orchestrator/dev")

    def test_empty_request_uses_default_base(self):
        for req in ("", None):
            self.assertEqual(runner._normalize_task_base(self.repo, PROJ, req),
                             "orchestrator/dev", repr(req))

    def test_deliberate_branch_still_wins(self):
        """A release lane must never be dragged onto dev."""
        self.assertEqual(
            runner._normalize_task_base(self.repo, PROJ, "release/2026-09"),
            "release/2026-09")

    def test_falls_back_when_default_absent_from_repo(self):
        """A default that does not resolve here must not strand the task."""
        repo = _repo_with(["main"])
        self.assertEqual(runner._normalize_task_base(repo, PROJ, "main"), "main")

    def test_prewarm_agrees_with_runner(self):
        """A worktree warmed on the wrong base is inherited silently by the agent."""
        for req in ("main", "master", "", "release/2026-09"):
            self.assertEqual(
                prewarm._normalize_base(self.repo, PROJ, req),
                runner._normalize_task_base(self.repo, PROJ, req),
                f"prewarm and runner disagree for {req!r}")

    def test_opt_out_restores_requested_first(self):
        os.environ["ORCH_STRICT_DEFAULT_BASE"] = "false"
        self.assertEqual(runner._normalize_task_base(self.repo, PROJ, "main"), "main")

    def test_strict_is_the_default(self):
        self.assertTrue(runner._strict_default_base())


if __name__ == "__main__":
    unittest.main()
