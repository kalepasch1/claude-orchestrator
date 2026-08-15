#!/usr/bin/env python3
"""Pins branch_durability: freeing a branch NAME must never destroy its COMMITS.

The upstream cause of the phantom-merge epidemic was branches destroyed before promotion:
3,332 recover-missing-branch-* tasks (23.6% of all output) re-doing work that had already
been done. Four code paths force-deleted branches with no durability check. These tests
pin the contract they now share.

Run: python3 -m pytest tests/test_branch_durability.py -q
"""
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner"))
import branch_durability as bd  # noqa: E402


def git(repo, *a):
    r = subprocess.run(["git", *a], cwd=repo, capture_output=True, text=True)
    assert r.returncode == 0, f"git {a}: {r.stderr}"
    return r.stdout.strip()


def rc(repo, *a):
    return subprocess.run(["git", *a], cwd=repo, capture_output=True, text=True).returncode


class BranchDurability(unittest.TestCase):
    def setUp(self):
        self.origin = tempfile.mkdtemp(prefix="bd-origin-")
        self.repo = tempfile.mkdtemp(prefix="bd-repo-")
        git(self.origin, "init", "-q", "--bare", "-b", "master")
        git(self.repo, "init", "-q", "-b", "master")
        git(self.repo, "config", "user.email", "t@t")
        git(self.repo, "config", "user.name", "t")
        with open(os.path.join(self.repo, "README"), "w") as f:
            f.write("base\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "base")
        git(self.repo, "remote", "add", "origin", self.origin)
        git(self.repo, "push", "-q", "origin", "master")
        # an agent branch with real, unpushed, unmerged work
        git(self.repo, "checkout", "-q", "-b", "agent/work-slice-1")
        with open(os.path.join(self.repo, "feature.py"), "w") as f:
            f.write("def feature():\n    return 42\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "feat: real work")
        self.tip = git(self.repo, "rev-parse", "HEAD")
        git(self.repo, "checkout", "-q", "master")

    def test_local_only_branch_is_not_on_origin(self):
        self.assertFalse(bd.is_on_origin(self.repo, "agent/work-slice-1"))

    def test_safe_delete_preserves_commits(self):
        """The commits must survive deletion — that is the whole point."""
        r = bd.safe_delete(self.repo, "agent/work-slice-1", reason="unit test")
        self.assertTrue(r["local_deleted"])
        # branch name is gone, so a rebuild gets a clean slate
        self.assertNotEqual(rc(self.repo, "rev-parse", "--verify", "agent/work-slice-1"), 0)
        # ...but the commit object is still reachable, so the work is recoverable
        self.assertEqual(rc(self.repo, "cat-file", "-e", self.tip), 0)
        archived = git(self.repo, "for-each-ref", "--format=%(objectname)", bd.ARCHIVE_NS)
        self.assertIn(self.tip, archived,
                      "tip was not archived — deleting the branch destroyed the only copy")

    def test_safe_delete_pushes_to_origin_before_removing(self):
        bd.safe_delete(self.repo, "agent/work-slice-1", reason="unit test")
        self.assertEqual(rc(self.origin, "rev-parse", "--verify", "agent/work-slice-1"), 0,
                         "local-only work was deleted without ever reaching origin")

    def test_remote_is_kept_when_commits_are_reachable_nowhere_else(self):
        """delete_remote must not strip the last durable copy."""
        r = bd.safe_delete(self.repo, "agent/work-slice-1", reason="redo",
                           delete_remote=True)
        self.assertFalse(r["remote_deleted"])
        self.assertEqual(rc(self.origin, "rev-parse", "--verify", "agent/work-slice-1"), 0)

    def test_remote_is_deleted_once_work_has_landed(self):
        """After the work is merged and pushed, cleaning the remote ref is safe."""
        git(self.repo, "merge", "-q", "--no-ff", "agent/work-slice-1", "-m", "Merge work")
        git(self.repo, "push", "-q", "origin", "master")
        git(self.repo, "push", "-q", "origin", "agent/work-slice-1")
        git(self.repo, "fetch", "-q", "origin")
        r = bd.safe_delete(self.repo, "agent/work-slice-1", reason="post-merge",
                           delete_remote=True)
        self.assertTrue(r["local_deleted"])
        self.assertTrue(r["remote_deleted"])
        self.assertEqual(rc(self.repo, "cat-file", "-e", self.tip), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
