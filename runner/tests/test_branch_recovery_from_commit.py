"""Finished work whose branch ref was pruned is recoverable from its recorded commit.

Measured 2026-09-01 across smarter / apparently-law / tomorrow: 101 tasks in DONE, only
10 still carrying an artifact_branch. 79 have no branch but DO have an artifact_commit,
and a sample of 28 found every one of those commits still present in its repository. The
work was never lost -- only the ref was. _materialize_branch resolved by branch NAME
alone, so the train reported "branch missing", queued a rebuild, and eventually abandoned
finished, reachable code.

Closing those tasks as unrecoverable would have destroyed 79 pieces of completed work.
"""
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest

RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RUNNER)
_spec = importlib.util.spec_from_file_location("_mt_recovery", os.path.join(RUNNER, "merge_train.py"))
mt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mt)


def _git(repo, *a):
    return subprocess.run(["git", *a], cwd=repo, capture_output=True, text=True, timeout=30)


def _repo_with_orphan_commit():
    """A repo where agent/work existed, was committed, then had its ref deleted."""
    d = tempfile.mkdtemp(prefix="recov-")
    _git(d, "init", "-q", "-b", "main")
    _git(d, "config", "user.email", "t@t.t")
    _git(d, "config", "user.name", "t")
    open(os.path.join(d, "base.txt"), "w").write("base")
    _git(d, "add", "-A"); _git(d, "commit", "-m", "base", "--no-gpg-sign")
    _git(d, "checkout", "-q", "-b", "agent/work")
    open(os.path.join(d, "feature.txt"), "w").write("the finished work")
    _git(d, "add", "-A"); _git(d, "commit", "-m", "agent: the finished work", "--no-gpg-sign")
    sha = _git(d, "rev-parse", "HEAD").stdout.strip()
    _git(d, "checkout", "-q", "main")
    _git(d, "branch", "-D", "agent/work")          # the ref is pruned; the commit remains
    return d, sha


class BranchRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.repo, self.sha = _repo_with_orphan_commit()
        self.task = {"artifact_commit": self.sha, "slug": "work"}

    def tearDown(self):
        os.environ.pop("ORCH_RECOVER_BRANCH_FROM_COMMIT", None)

    def test_the_ref_is_really_gone_but_the_commit_is_not(self):
        """Pin the premise, or the rest of this file proves nothing."""
        self.assertFalse(mt._branch_exists(self.repo, "agent/work"))
        self.assertEqual(
            _git(self.repo, "cat-file", "-e", self.sha + "^{commit}").returncode, 0)

    def test_branch_is_recovered_from_the_recorded_commit(self):
        self.assertTrue(mt._materialize_branch(self.repo, "agent/work", self.task))
        self.assertTrue(mt._branch_exists(self.repo, "agent/work"))
        self.assertEqual(_git(self.repo, "rev-parse", "agent/work").stdout.strip(), self.sha)

    def test_recovered_branch_carries_the_actual_work(self):
        mt._materialize_branch(self.repo, "agent/work", self.task)
        blob = _git(self.repo, "show", "agent/work:feature.txt").stdout
        self.assertIn("the finished work", blob)

    def test_without_the_task_it_still_fails_as_before(self):
        """The fallback needs the task; nothing else changes."""
        self.assertFalse(mt._materialize_branch(self.repo, "agent/work"))

    def test_a_commit_not_in_this_repo_is_not_invented(self):
        bogus = {"artifact_commit": "0" * 40}
        self.assertFalse(mt._materialize_branch(self.repo, "agent/work", bogus))
        self.assertFalse(mt._branch_exists(self.repo, "agent/work"))

    def test_empty_commit_is_handled(self):
        for bad in ({"artifact_commit": ""}, {"artifact_commit": None}, {}, None):
            self.assertFalse(mt._recover_branch_from_artifact_commit(self.repo, "agent/x", bad))

    def test_flag_disables_recovery(self):
        os.environ["ORCH_RECOVER_BRANCH_FROM_COMMIT"] = "false"
        self.assertFalse(mt._recover_branch_from_artifact_commit(self.repo, "agent/work", self.task))

    def test_recovery_is_on_by_default(self):
        self.assertTrue(mt._recover_branch_from_artifact_commit(self.repo, "agent/work", self.task))

    def test_existing_branch_short_circuits(self):
        _git(self.repo, "branch", "agent/work", self.sha)
        self.assertTrue(mt._materialize_branch(self.repo, "agent/work", self.task))


if __name__ == "__main__":
    unittest.main()
