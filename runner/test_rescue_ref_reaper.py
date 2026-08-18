"""Tests for the repo-wide orch-rescue reaper.

Measured 2026-08-12 in apparently: 209 refs under refs/orch-rescue resolving to
191 unique SHAs, 133 of which nothing had ever classified. Cause: the existing
pruner is called only from rescue() and scopes by worktree name, and agent
worktrees are removed after push — so an orphaned worktree's refs become
unreachable by the only code that could retire them.

The property that matters most here is the one that must NEVER regress: a ref
whose content is not already in the base is never deleted, whatever its age.
"""

import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import worktree_ownership_guard as g  # noqa: E402


def run(cwd, *args):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True)


class ReaperTests(unittest.TestCase):
    def setUp(self):
        self.repo = tempfile.mkdtemp(prefix="reaper-test-")
        run(self.repo, "git", "init", "-q", "-b", "master")
        run(self.repo, "git", "config", "user.email", "t@example.com")
        run(self.repo, "git", "config", "user.name", "t")
        with open(os.path.join(self.repo, "a.txt"), "w") as fh:
            fh.write("one\n")
        run(self.repo, "git", "add", "-A")
        run(self.repo, "git", "commit", "-q", "-m", "base")
        self.base = run(self.repo, "git", "rev-parse", "HEAD").stdout.strip()

    def _commit(self, name, content):
        with open(os.path.join(self.repo, name), "w") as fh:
            fh.write(content)
        run(self.repo, "git", "add", "-A")
        run(self.repo, "git", "commit", "-q", "-m", "work " + name)
        return run(self.repo, "git", "rev-parse", "HEAD").stdout.strip()

    def _ref(self, name, sha):
        run(self.repo, "git", "update-ref", g.RESCUE_PREFIX + "/" + name, sha)

    def test_discharged_ref_is_reported_but_not_deleted_when_dry_run(self):
        self._ref("20260803T000000-gone-worktree-aaaaaaaa", self.base)
        report = g.reap_rescue_refs(self.repo, base="master", dry_run=True)
        self.assertEqual(report["scanned"], 1)
        self.assertEqual(report["discharged"], 1)
        self.assertEqual(report["deleted"], 0)
        self.assertTrue(report["dry_run"])
        self.assertIn(g.RESCUE_PREFIX, run(
            self.repo, "git", "for-each-ref", "--format=%(refname)", g.RESCUE_PREFIX).stdout)

    def test_orphaned_discharged_ref_is_reaped_when_asked(self):
        """The leak: this worktree no longer exists, so nothing else can reap it."""
        self._ref("20260803T000000-gone-worktree-aaaaaaaa", self.base)
        report = g.reap_rescue_refs(self.repo, base="master", dry_run=False)
        self.assertEqual(report["deleted"], 1)
        self.assertEqual(run(self.repo, "git", "for-each-ref", "--format=%(refname)",
                             g.RESCUE_PREFIX).stdout.strip(), "")

    def test_unmerged_ref_is_never_deleted(self):
        """A rescue ref is the last copy. This must never regress."""
        run(self.repo, "git", "checkout", "-q", "-b", "side")
        sha = self._commit("b.txt", "unshipped work\n")
        run(self.repo, "git", "checkout", "-q", "master")
        self._ref("20260101T000000-ancient-worktree-bbbbbbbb", sha)
        report = g.reap_rescue_refs(self.repo, base="master", dry_run=False)
        self.assertEqual(report["retained"], 1)
        self.assertEqual(report["deleted"], 0)
        self.assertIn("bbbbbbbb", run(self.repo, "git", "for-each-ref",
                                      "--format=%(refname)", g.RESCUE_PREFIX).stdout)

    def test_mixed_backlog_keeps_only_the_valuable(self):
        self._ref("20260803T000000-x-11111111", self.base)
        self._ref("20260804T000000-y-22222222", self.base)
        run(self.repo, "git", "checkout", "-q", "-b", "side2")
        keep = self._commit("c.txt", "keep me\n")
        run(self.repo, "git", "checkout", "-q", "master")
        self._ref("20260805T000000-z-33333333", keep)
        report = g.reap_rescue_refs(self.repo, base="master", dry_run=False)
        self.assertEqual(report["scanned"], 3)
        self.assertEqual(report["deleted"], 2)
        self.assertEqual(report["retained"], 1)
        remaining = run(self.repo, "git", "for-each-ref", "--format=%(refname)",
                        g.RESCUE_PREFIX).stdout
        self.assertIn("33333333", remaining)

    def test_limit_caps_deletions(self):
        for i in range(4):
            self._ref("2026080%dT000000-x-0000000%d" % (i + 1, i), self.base)
        report = g.reap_rescue_refs(self.repo, base="master", dry_run=False, limit=2)
        self.assertEqual(report["deleted"], 2)

    def test_empty_repo_is_fail_soft(self):
        report = g.reap_rescue_refs(self.repo, base="master", dry_run=False)
        self.assertEqual(report["scanned"], 0)
        self.assertEqual(report["deleted"], 0)

    def test_bad_repo_and_bad_base_never_raise(self):
        for repo, base in (("/nonexistent/repo", "master"), (self.repo, ""),
                           (self.repo, "no-such-ref")):
            report = g.reap_rescue_refs(repo, base=base, dry_run=False)
            self.assertEqual(report["deleted"], 0)

    def test_orphaned_refs_are_invisible_to_the_per_worktree_lister(self):
        """The mechanism of the leak, stated as a test.

        _rescue_refs runs git INSIDE the worktree directory. Agent worktrees are
        removed after push, so once the directory is gone the call cannot even
        run — the refs it would have retired become unreachable by the only code
        that retires them. _all_rescue_refs sees them regardless.
        """
        self._ref("20260803T000000-worktree-alpha-aaaaaaaa", self.base)
        self._ref("20260803T000001-worktree-beta-bbbbbbbb", self.base)
        self.assertEqual(len(g._all_rescue_refs(self.repo)), 2)
        gone = os.path.join(self.repo, "worktree-alpha")   # removed after push
        self.assertFalse(os.path.isdir(gone))
        self.assertEqual(g._rescue_refs(gone), [],
                         "the per-worktree lister cannot see an orphan's refs")
        self.assertEqual(g._prune_rescue_refs(gone), 0,
                         "and therefore can never retire them")


if __name__ == "__main__":
    unittest.main()
