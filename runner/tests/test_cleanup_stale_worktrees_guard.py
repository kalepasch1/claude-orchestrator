#!/usr/bin/env python3
"""Regression: cleanup_stale_worktrees must only touch `agent/*` worktrees.

`git_auto_branch` carried two top-level definitions of `cleanup_stale_worktrees`.
Python keeps the last one, so the *unguarded* implementation was live: it derived
a slug with a bare `removeprefix(BRANCH_PREFIX)` and therefore mapped a non-agent
branch such as `orchestrator/dev` onto the slug `orchestrator/dev` — a single slug
collision away from `git worktree remove --force` on an operator's worktree.

These tests pin the surviving, guarded behaviour and assert the duplicate is gone.
"""
import ast
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import git_auto_branch  # noqa: E402


def _porcelain(entries):
    """Render `git worktree list --porcelain` output for (path, branch) pairs."""
    out = []
    for path, branch in entries:
        out.append(f"worktree {path}")
        out.append("HEAD 0123456789abcdef0123456789abcdef01234567")
        if branch is not None:
            out.append(f"branch refs/heads/{branch}")
        out.append("")
    return "\n".join(out)


class CleanupStaleWorktreesGuardTest(unittest.TestCase):
    def setUp(self):
        self._orig = {
            "_git": git_auto_branch._git,
            "_active_slugs": git_auto_branch._active_slugs,
            "_merged_slugs": git_auto_branch._merged_slugs,
            "_done_slugs": git_auto_branch._done_slugs,
            "isdir": os.path.isdir,
        }
        self.removed = []

    def tearDown(self):
        git_auto_branch._git = self._orig["_git"]
        git_auto_branch._active_slugs = self._orig["_active_slugs"]
        git_auto_branch._merged_slugs = self._orig["_merged_slugs"]
        git_auto_branch._done_slugs = self._orig["_done_slugs"]
        os.path.isdir = self._orig["isdir"]

    def _install(self, entries, terminal):
        os.path.isdir = lambda p: True
        listing = _porcelain(entries)

        def fake_git(args, repo):
            if args[:2] == ["worktree", "list"]:
                return listing, True
            if args[:2] == ["worktree", "remove"]:
                self.removed.append(args[-1])
                return "", True
            return "", True

        git_auto_branch._git = fake_git
        git_auto_branch._active_slugs = lambda: {}
        git_auto_branch._merged_slugs = lambda: dict(terminal)
        git_auto_branch._done_slugs = lambda: {}

    def test_single_definition_survives(self):
        """The shadowing duplicate must not come back."""
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "git_auto_branch.py")
        with open(path) as fh:
            tree = ast.parse(fh.read())
        defs = [n for n in tree.body
                if isinstance(n, ast.FunctionDef) and n.name == "cleanup_stale_worktrees"]
        assert len(defs) == 1, f"expected 1 cleanup_stale_worktrees, found {len(defs)}"

    def test_removes_terminal_agent_worktree(self):
        self._install([("/wt/done-slug", "agent/done-slug")], {"done-slug": ""})
        assert git_auto_branch.cleanup_stale_worktrees("/repo") == 1
        assert self.removed == ["/wt/done-slug"]

    def test_never_removes_non_agent_branch(self):
        """`orchestrator/dev` must be ignored even when it collides with a slug."""
        self._install(
            [("/wt/manual-restart-dev", "orchestrator/dev"), ("/wt/main", "master")],
            {"orchestrator/dev": "", "master": ""},
        )
        assert git_auto_branch.cleanup_stale_worktrees("/repo") == 0
        assert self.removed == []

    def test_keeps_active_and_detached_worktrees(self):
        self._install(
            [("/wt/live", "agent/live-slug"), ("/wt/baseline", None)],
            {"live-slug": ""},
        )
        git_auto_branch._active_slugs = lambda: {"live-slug": ""}
        assert git_auto_branch.cleanup_stale_worktrees("/repo") == 0
        assert self.removed == []

    def test_last_entry_without_trailing_blank_line(self):
        """splitlines() drops the trailing blank, so the last entry must still flush."""
        self._install([("/wt/a", "agent/a-slug"), ("/wt/b", "agent/b-slug")],
                      {"a-slug": "", "b-slug": ""})
        # rstrip the terminator the way an unterminated capture would
        listing = _porcelain([("/wt/a", "agent/a-slug"), ("/wt/b", "agent/b-slug")]).rstrip("\n")

        def fake_git(args, repo):
            if args[:2] == ["worktree", "list"]:
                return listing, True
            if args[:2] == ["worktree", "remove"]:
                self.removed.append(args[-1])
                return "", True
            return "", True

        git_auto_branch._git = fake_git
        assert git_auto_branch.cleanup_stale_worktrees("/repo") == 2
        assert self.removed == ["/wt/a", "/wt/b"]

    def test_missing_repo_is_fail_soft(self):
        os.path.isdir = lambda p: False
        assert git_auto_branch.cleanup_stale_worktrees("/nope") == 0
        assert git_auto_branch.cleanup_stale_worktrees("") == 0


if __name__ == "__main__":
    unittest.main()
