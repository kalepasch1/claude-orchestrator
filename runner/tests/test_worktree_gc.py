import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import worktree_gc


class WorktreeGCTest(unittest.TestCase):

    def test_removes_stale_sibling_worktree_without_substring_false_positive(self):
        repo = "/tmp/app"
        stale = "/tmp/app-wt/old-task"
        porcelain = f"""worktree {repo}
HEAD abc
branch refs/heads/main

worktree {stale}
HEAD def
branch refs/heads/agent/old-task

"""
        db = MagicMock()
        db.select.side_effect = [[], [], [], []]
        calls = []

        def run(args, cwd=None, capture_output=False, text=False):
            calls.append(args)
            if args[:3] == ["git", "worktree", "list"]:
                return MagicMock(stdout=porcelain, returncode=0)
            return MagicMock(stdout="", returncode=0)

        with patch.object(worktree_gc, "db", db), \
             patch.object(worktree_gc.os.path, "isdir", return_value=True), \
             patch.object(worktree_gc.subprocess, "run", side_effect=run):
            removed = worktree_gc.gc_repo(repo)

        self.assertEqual(removed, 1)
        self.assertIn(["git", "worktree", "remove", "--force", stale], calls)

    def test_approved_merge_card_protects_worktree(self):
        repo = "/tmp/app"
        protected = "/tmp/app-wt/keep-task"
        porcelain = f"""worktree {protected}
HEAD def
branch refs/heads/agent/keep-task

"""
        db = MagicMock()
        db.select.side_effect = [
            [], [], [],
            [{"slug": "keep-task", "kind": "integrate", "status": "approved", "decided_by": None}],
        ]
        calls = []

        def run(args, cwd=None, capture_output=False, text=False):
            calls.append(args)
            if args[:3] == ["git", "worktree", "list"]:
                return MagicMock(stdout=porcelain, returncode=0)
            return MagicMock(stdout="", returncode=0)

        with patch.object(worktree_gc, "db", db), \
             patch.object(worktree_gc.os.path, "isdir", return_value=True), \
             patch.object(worktree_gc.subprocess, "run", side_effect=run):
            removed = worktree_gc.gc_repo(repo)

        self.assertEqual(removed, 0)
        self.assertNotIn(["git", "worktree", "remove", "--force", protected], calls)


if __name__ == "__main__":
    unittest.main()
