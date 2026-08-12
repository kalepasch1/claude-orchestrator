"""Regression tests for the 2026-08-12 reserved-worktree incident.

WHAT HAPPENED. `approval_merge._free_branch()` resolves a branch to whichever
worktree has it checked out and runs `git worktree remove --force` on it. Its
only exemption was the PRIMARY checkout, so every LINKED worktree was fair
game — including the one an operator had the integration branch
(orchestrator/dev) checked out in. That night an agent wrote into
apparently-wt/promote-20260811 while it was in use and left a conflicted index
with no MERGE_HEAD and four raw conflict markers in a tracked .ts file.
`--force` would not have stopped at uncommitted work either.

`worktree_isolation.validate_task_worktree()` already encoded the right rule —
a task checkout is always `agent/<slug>` — but the destructive paths never
called it. These tests pin the extracted predicate and the call site together,
so the two cannot drift apart again.

Stdlib + unittest.mock only (runner convention).
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import worktree_isolation


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


class ReservedWorktreeBase(unittest.TestCase):
    """A real repo with a real linked worktree — the predicate shells out to git."""

    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.repo = os.path.join(self.tmp, "repo")
        os.makedirs(self.repo)
        _git(self.repo, "init", "-q", "-b", "master")
        _git(self.repo, "config", "user.email", "t@example.com")
        _git(self.repo, "config", "user.name", "t")
        open(os.path.join(self.repo, "f.txt"), "w").write("x\n")
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-qm", "init")

    def _worktree(self, name, branch):
        wt = os.path.join(self.tmp, "repo-wt", name)
        os.makedirs(os.path.dirname(wt), exist_ok=True)
        _git(self.repo, "worktree", "add", "-q", "-b", branch, wt)
        return wt


class TestReservedWorktreeReason(ReservedWorktreeBase):
    def test_agent_worktree_is_disposable(self):
        wt = self._worktree("some-slug", "agent/some-slug")
        self.assertIsNone(worktree_isolation.reserved_worktree_reason(self.repo, wt))
        self.assertTrue(worktree_isolation.is_disposable_worktree(self.repo, wt))

    def test_integration_branch_worktree_is_protected(self):
        """The exact incident: a linked worktree holding orchestrator/dev."""
        wt = self._worktree("promote-20260811", "orchestrator/dev")
        reason = worktree_isolation.reserved_worktree_reason(self.repo, wt)
        self.assertIsNotNone(reason, "orchestrator/dev worktree must never be disposable")
        self.assertIn("orchestrator/dev", reason)
        self.assertFalse(worktree_isolation.is_disposable_worktree(self.repo, wt))

    def test_primary_checkout_is_protected(self):
        reason = worktree_isolation.reserved_worktree_reason(self.repo, self.repo)
        self.assertIsNotNone(reason)
        self.assertIn("primary checkout", reason)

    def test_non_agent_branch_is_protected(self):
        """The positive form of the rule — only agent/<slug> is disposable."""
        wt = self._worktree("landing", "landing-revamp-20260811")
        reason = worktree_isolation.reserved_worktree_reason(self.repo, wt)
        self.assertIsNotNone(reason)
        self.assertIn("not an agent/<slug>", reason)

    def test_detached_head_is_protected(self):
        """Refuse rather than guess: a detached worktree is not provably a task."""
        wt = self._worktree("detachme", "agent/detachme")
        sha = _git(wt, "rev-parse", "HEAD").stdout.strip()
        _git(wt, "checkout", "-q", "--detach", sha)
        reason = worktree_isolation.reserved_worktree_reason(self.repo, wt)
        self.assertIsNotNone(reason)
        self.assertIn("detached", reason)

    def test_marker_file_protects_an_otherwise_disposable_worktree(self):
        wt = self._worktree("markme", "agent/markme")
        self.assertIsNone(worktree_isolation.reserved_worktree_reason(self.repo, wt))
        open(os.path.join(wt, worktree_isolation.RESERVED_MARKER), "w").close()
        reason = worktree_isolation.reserved_worktree_reason(self.repo, wt)
        self.assertIsNotNone(reason)
        self.assertIn(worktree_isolation.RESERVED_MARKER, reason)

    def test_reserved_branch_set_is_configurable(self):
        wt = self._worktree("custom", "release/2026-08")
        os.environ["ORCH_RESERVED_BRANCHES"] = "release/2026-08"
        self.addCleanup(os.environ.pop, "ORCH_RESERVED_BRANCHES", None)
        self.assertEqual(worktree_isolation.reserved_branches(), ("release/2026-08",))
        reason = worktree_isolation.reserved_worktree_reason(self.repo, wt)
        self.assertIn("release/2026-08", reason)


class TestFreeBranchRefusesProtectedWorktrees(ReservedWorktreeBase):
    """The call site, not just the predicate — this is what actually deletes."""

    def _free_branch(self, branch):
        import approval_merge
        return approval_merge._free_branch(self.repo, branch)

    def test_does_not_remove_the_integration_worktree(self):
        wt = self._worktree("promote-20260811", "orchestrator/dev")
        probe = os.path.join(wt, "uncommitted.txt")
        open(probe, "w").write("work that --force would have destroyed\n")

        self.assertFalse(self._free_branch("orchestrator/dev"),
                         "_free_branch must report failure rather than remove a protected worktree")
        self.assertTrue(os.path.isdir(wt), "the protected worktree was removed")
        self.assertTrue(os.path.isfile(probe), "uncommitted work was destroyed")

    def test_still_removes_a_genuine_agent_worktree(self):
        """The guard must not neuter the function's actual job."""
        wt = self._worktree("stale-slug", "agent/stale-slug")
        self.assertTrue(self._free_branch("agent/stale-slug"))
        self.assertFalse(os.path.isdir(wt), "a stale agent worktree should still be freed")
