"""Regression tests for nested agent worktrees inside the primary checkout.

Pins the 2026-07-16 incident: claude-orchestrator/claude-orchestrator-wt/agent-cade-inbound-triage
was a worktree nested inside the primary checkout AND committed as a tracked gitlink.
Once its gitdir was pruned the gitlink dangled and every `git status` in the repo died
with 'fatal: not a git repository', silently disabling sentinel's dirty-check.

Stdlib + unittest.mock only (runner convention).
"""
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import worktree_isolation


class TestIsNestedIn(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_nested_path_detected(self):
        repo = os.path.join(self.tmp, "repo")
        os.makedirs(os.path.join(repo, "repo-wt", "slug"))
        self.assertTrue(
            worktree_isolation.is_nested_in(os.path.join(repo, "repo-wt", "slug"), repo)
        )

    def test_sibling_path_is_not_nested(self):
        """The correct convention: <repo>-wt is a SIBLING of <repo>."""
        repo = os.path.join(self.tmp, "repo")
        sibling = os.path.join(self.tmp, "repo-wt", "slug")
        os.makedirs(repo)
        os.makedirs(sibling)
        self.assertFalse(worktree_isolation.is_nested_in(sibling, repo))

    def test_repo_itself_is_not_nested(self):
        repo = os.path.join(self.tmp, "repo")
        os.makedirs(repo)
        self.assertFalse(worktree_isolation.is_nested_in(repo, repo))

    def test_sibling_prefix_collision_is_not_nested(self):
        """'/x/repo-wt' must not count as inside '/x/repo' via string prefix."""
        repo = os.path.join(self.tmp, "repo")
        other = os.path.join(self.tmp, "repo-wt")
        os.makedirs(repo)
        os.makedirs(other)
        self.assertFalse(worktree_isolation.is_nested_in(other, repo))


class TestValidateRejectsNested(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_validate_task_worktree_rejects_nested_worktree(self):
        repo = os.path.join(self.tmp, "repo")
        nested = os.path.join(repo, "repo-wt", "myslug")
        os.makedirs(nested)
        with self.assertRaises(worktree_isolation.WorktreeIsolationError) as ctx:
            worktree_isolation.validate_task_worktree(repo, "myslug", nested)
        self.assertIn("nested", str(ctx.exception).lower())

    def test_validate_task_worktree_rejects_primary_checkout(self):
        repo = os.path.join(self.tmp, "repo")
        os.makedirs(repo)
        with self.assertRaises(worktree_isolation.WorktreeIsolationError):
            worktree_isolation.validate_task_worktree(repo, "myslug", repo)


class TestSentinelQuarantine(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.repo = os.path.join(self.tmp, "claude-orchestrator")
        os.makedirs(self.repo)

    def _sentinel(self):
        import sentinel
        return sentinel

    def _make_nested(self, name, gitdir):
        wt = os.path.join(self.repo, "claude-orchestrator-wt", name)
        os.makedirs(wt)
        with open(os.path.join(wt, ".git"), "w") as f:
            f.write(f"gitdir: {gitdir}\n")
        return wt

    def test_dangling_nested_worktree_is_quarantined_not_deleted(self):
        sentinel = self._sentinel()
        wt = self._make_nested("agent-dead", os.path.join(self.repo, ".git", "worktrees", "gone"))
        with open(os.path.join(wt, "unsaved.txt"), "w") as f:
            f.write("precious uncommitted work")
        quarantine = os.path.join(self.tmp, "_quarantine")

        with mock.patch.object(sentinel, "REPO", self.repo), \
             mock.patch.object(sentinel, "QUARANTINE", quarantine), \
             mock.patch.object(sentinel, "log"), mock.patch.object(sentinel, "emit"):
            sentinel.nested_worktree_guard()

        self.assertFalse(os.path.isdir(wt), "dangling nested worktree should be moved out")
        moved = os.listdir(quarantine)
        self.assertEqual(len(moved), 1)
        # The point of moving instead of deleting: content survives.
        recovered = os.path.join(quarantine, moved[0], "unsaved.txt")
        self.assertTrue(os.path.isfile(recovered))
        with open(recovered) as f:
            self.assertEqual(f.read(), "precious uncommitted work")

    def test_live_nested_worktree_is_left_alone(self):
        """If the gitdir still exists, an agent may be mid-run. Never yank it."""
        sentinel = self._sentinel()
        live_gitdir = os.path.join(self.repo, ".git", "worktrees", "alive")
        os.makedirs(live_gitdir)
        wt = self._make_nested("agent-alive", live_gitdir)
        quarantine = os.path.join(self.tmp, "_quarantine")

        with mock.patch.object(sentinel, "REPO", self.repo), \
             mock.patch.object(sentinel, "QUARANTINE", quarantine), \
             mock.patch.object(sentinel, "log"), mock.patch.object(sentinel, "emit"):
            sentinel.nested_worktree_guard()

        self.assertTrue(os.path.isdir(wt), "live worktree must not be quarantined")

    def test_no_wt_dir_is_a_noop(self):
        sentinel = self._sentinel()
        with mock.patch.object(sentinel, "REPO", self.repo), \
             mock.patch.object(sentinel, "QUARANTINE", os.path.join(self.tmp, "_q")), \
             mock.patch.object(sentinel, "log"), mock.patch.object(sentinel, "emit"):
            sentinel.nested_worktree_guard()  # must not raise


if __name__ == "__main__":
    unittest.main()
