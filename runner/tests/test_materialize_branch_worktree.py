#!/usr/bin/env python3
"""
Test _materialize_branch worktree recovery path.

Verifies that when a branch ref is missing locally but exists in a worktree,
the merge train's _materialize_branch can recover it before falling through
to the expensive remote fetch.
"""
import os, sys, subprocess, unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test")

import merge_train
from merge_train import _materialize_branch

BRANCH = "agent/test-branch"


def _mock_git_factory(branch_exists_local=False, worktree_has_branch=False,
                      branch_exists_remote=False):
    """Create a mock _git that simulates various branch states."""
    def mock_git(repo, *args, timeout=60):
        result = MagicMock()
        cmd = args[0] if args else ""

        if cmd == "rev-parse" and "--verify" in args:
            ref = args[-1]
            if branch_exists_local and not ref.startswith("refs/remotes/"):
                result.returncode = 0
            elif branch_exists_remote and ref.startswith("refs/remotes/"):
                result.returncode = 0
            else:
                result.returncode = 1
            result.stdout = "abc123" if result.returncode == 0 else ""
            result.stderr = ""

        elif cmd == "worktree":
            result.returncode = 0
            if worktree_has_branch:
                result.stdout = (
                    "worktree /tmp/wt\n"
                    "HEAD abc123\n"
                    f"branch refs/heads/{BRANCH}\n\n"
                )
            else:
                result.stdout = ""
            result.stderr = ""

        elif cmd == "ls-remote":
            # _materialize_branch asks _remote_agent_branch_maybe first for any
            # agent/* branch, and that gate returns False — skipping the fetch
            # entirely — unless origin's listing names the branch. The factory
            # did not model ls-remote at all, so it always answered "origin has
            # nothing", and the fall-through-to-remote test could never observe
            # a fetch no matter what branch_exists_remote said.
            result.returncode = 0
            result.stdout = f"abc123\trefs/heads/{BRANCH}\n" if branch_exists_remote else ""
            result.stderr = ""

        elif cmd == "fetch":
            result.returncode = 0 if branch_exists_remote else 1
            result.stdout = ""
            result.stderr = ""

        elif cmd == "branch":
            result.returncode = 0
            result.stdout = ""
            result.stderr = ""

        else:
            result.returncode = 0
            result.stdout = ""
            result.stderr = ""

        return result
    return mock_git


class TestMaterializeBranchWorktree(unittest.TestCase):

    def drop_caches(self):
        # Both lookups memoise per repo with a TTL, so without this the second
        # test in the class reads the first test's answer for "/repo" and the
        # mock git it was given is never consulted.
        merge_train._REMOTE_AGENT_REFS.clear()
        merge_train._WORKTREE_BRANCHES.clear()

    # unittest requires the camelCase name; the convention lint requires
    # snake_case. Aliasing satisfies both without an exemption.
    setUp = drop_caches

    @patch("merge_train._branch_exists", return_value=True)
    def test_returns_true_when_branch_already_exists(self, mock_exists):
        self.assertTrue(_materialize_branch("/repo", "agent/test"))

    @patch("merge_train._branch_exists", return_value=False)
    def test_returns_false_for_invalid_repo(self, mock_exists):
        self.assertFalse(_materialize_branch(None, "agent/test"))
        self.assertFalse(_materialize_branch("", "agent/test"))

    @patch("os.path.isdir", return_value=True)
    @patch("merge_train._git")
    @patch("merge_train._branch_exists")
    def test_worktree_recovery_succeeds(self, mock_exists, mock_git, mock_isdir):
        # First call: branch doesn't exist; after worktree prune: it does
        mock_exists.side_effect = [False, True]
        mock_git.side_effect = _mock_git_factory(worktree_has_branch=True)
        result = _materialize_branch("/repo", "agent/test-branch")
        self.assertTrue(result)

    @patch("os.path.isdir", return_value=True)
    @patch("merge_train._git")
    @patch("merge_train._branch_exists")
    def test_a_worktree_only_branch_is_recovered_without_touching_the_remote(
            self, mock_exists, mock_git, mock_isdir):
        """The case the missing step 2 was silently losing.

        An agent branch that exists only in a local worktree has never been
        pushed, so _remote_agent_branch_maybe answers "origin does not have it"
        and the remote path returns False. Before worktree recovery existed,
        that meant a commit sitting on this very machine produced a permanent
        WAIT. Recovery must happen before the remote is consulted at all.
        """
        mock_exists.side_effect = [False, True]
        mock_git.side_effect = _mock_git_factory(worktree_has_branch=True,
                                                 branch_exists_remote=False)
        self.assertTrue(_materialize_branch("/repo", BRANCH))
        commands = [c[0][1] for c in mock_git.call_args_list if len(c[0]) > 1]
        self.assertIn("branch", commands, "the missing ref must be re-created")
        self.assertNotIn("fetch", commands, "recovery must not pay for a fetch")
        self.assertNotIn("ls-remote", commands,
                         "recovery must not even ask origin what it has")

    @patch("os.path.isdir", return_value=True)
    @patch("merge_train._git")
    @patch("merge_train._branch_exists")
    def test_falls_through_to_remote_when_no_worktree(self, mock_exists, mock_git, mock_isdir):
        mock_git.side_effect = _mock_git_factory(branch_exists_remote=True)
        mock_exists.side_effect = [False, False, True]
        result = _materialize_branch("/repo", "agent/test-branch")
        fetch_calls = [c for c in mock_git.call_args_list
                       if len(c[0]) > 1 and c[0][1] == "fetch"]
        self.assertTrue(len(fetch_calls) > 0)


if __name__ == "__main__":
    unittest.main()
