"""The guards worktree_gc defines must be the guards worktree_gc runs.

_is_dirty() and _recently_active() have been in worktree_gc since it was
written, both documented as failing CLOSED, and neither was called by anything
in the product. gc_repo() -- the only code path that removes a worktree -- had
an inline os.path.getmtime() in place of _recently_active(), no dirty check at
all, and a comment above the removal reading

    # All guards passed (task terminal, clean, aged)

"clean" was never checked. The removal is `git worktree remove --force`, which
discards uncommitted AND untracked files without asking, so an agent's
in-progress edits in a slot whose task row had already gone terminal were
deleted with no record that they had existed.

The inline recency check was also weaker than the function it stood in for: it
stat'd only the working directory, while an executor working in a slot touches
.git/index and the admin dir; and on OSError it fell THROUGH to removal, where
_recently_active returns True.
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import worktree_gc

REPO = "/tmp/app"
SLOT = "/tmp/app-wt/old-task"
PORCELAIN = "worktree %s\nHEAD def\nbranch refs/heads/agent/old-task\n\n" % SLOT
CLEAN = ""
DIRTY = " M some/file.ts\n"
UNTRACKED_ONLY = "?? notes.md\n"


class _GC(unittest.TestCase):
    """gc_repo over one unprotected, non-main agent slot."""

    def _gc(self, status_stdout=CLEAN, status_rc=0, recently_active=False):
        self.calls = []

        def run(args, cwd=None, capture_output=False, text=False, **kw):
            self.calls.append(args)
            if args[:3] == ["git", "worktree", "list"]:
                return MagicMock(stdout=PORCELAIN, returncode=0)
            if args[:2] == ["git", "status"]:
                return MagicMock(stdout=status_stdout, returncode=status_rc)
            return MagicMock(stdout="", returncode=0)

        fake_db = MagicMock()
        fake_db.select.side_effect = [[], [], [], []]
        with patch.object(worktree_gc, "db", fake_db), \
             patch.object(worktree_gc.os.path, "isdir", return_value=True), \
             patch.object(worktree_gc, "_recently_active", return_value=recently_active), \
             patch.object(worktree_gc.subprocess, "run", side_effect=run):
            return worktree_gc.gc_repo(REPO)

    def assert_not_removed(self, removed):
        self.assertEqual(removed, 0)
        self.assertNotIn(["git", "worktree", "remove", "--force", SLOT], self.calls)


class DirtyWorktreesSurvive(_GC):
    def test_modified_files_stop_the_removal(self):
        self.assert_not_removed(self._gc(status_stdout=DIRTY))

    def test_untracked_files_stop_the_removal(self):
        """--force deletes untracked files too, so they count as work."""
        self.assert_not_removed(self._gc(status_stdout=UNTRACKED_ONLY))

    def test_an_unreadable_status_stops_the_removal(self):
        """_is_dirty fails closed; gc_repo must honour that, not route around it."""
        self.assert_not_removed(self._gc(status_stdout="", status_rc=128))

    def test_a_clean_worktree_is_still_removed(self):
        """The guard must not be so eager that nothing is ever reclaimed."""
        removed = self._gc(status_stdout=CLEAN)
        self.assertEqual(removed, 1)
        self.assertIn(["git", "worktree", "remove", "--force", SLOT], self.calls)


class ActiveWorktreesSurvive(_GC):
    def test_a_recently_active_slot_is_not_removed(self):
        self.assert_not_removed(self._gc(recently_active=True))

    def test_recency_is_checked_before_the_branch_is_pushed(self):
        """An active slot should cost nothing: no status, no push, no unlock."""
        self._gc(recently_active=True)
        verbs = {tuple(c[:2]) for c in self.calls}
        self.assertNotIn(("git", "push"), verbs)
        self.assertNotIn(("git", "status"), verbs)


class TheGuardsAreReachable(unittest.TestCase):
    """Regression on the shape of the bug: a guard defined but never invoked."""

    def test_gc_repo_calls_both_guards(self):
        seen = []

        def run(args, cwd=None, capture_output=False, text=False, **kw):
            if args[:3] == ["git", "worktree", "list"]:
                return MagicMock(stdout=PORCELAIN, returncode=0)
            return MagicMock(stdout="", returncode=0)

        fake_db = MagicMock()
        fake_db.select.side_effect = [[], [], [], []]
        with patch.object(worktree_gc, "db", fake_db), \
             patch.object(worktree_gc.os.path, "isdir", return_value=True), \
             patch.object(worktree_gc, "_recently_active",
                          side_effect=lambda p: seen.append("recent") or False), \
             patch.object(worktree_gc, "_is_dirty",
                          side_effect=lambda p: seen.append("dirty") or False), \
             patch.object(worktree_gc.subprocess, "run", side_effect=run):
            worktree_gc.gc_repo(REPO)

        self.assertIn("recent", seen)
        self.assertIn("dirty", seen)


if __name__ == "__main__":
    unittest.main()
