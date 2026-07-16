import os
import sys
import types
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import queue_elimination as qe

REPO = "/fake/repo"


def _proc(returncode=0, stdout="", stderr=""):
    p = MagicMock()
    p.returncode = returncode
    p.stdout = stdout
    p.stderr = stderr
    return p


class WorktreePathTest(unittest.TestCase):
    def test_path_is_sibling_wt_dir_not_inside_repo(self):
        path = qe._worktree_path("/Users/x/repo", "elim-abc-123")
        self.assertEqual(path, "/Users/x/repo-wt/elim-abc-123")
        self.assertFalse(path.startswith("/Users/x/repo/"))


class ApplyAndVerifyNeverTouchesRepoCwdTest(unittest.TestCase):
    """The core regression this fix is for: no git checkout / apply / test / commit call may
    run with cwd=repo (the primary checkout) — only `git apply --check` (read-only, safe) and
    the worktree add/remove/branch-delete bookkeeping calls are allowed to target repo."""

    def _run_calls(self, run_mock):
        return [c.args[0] for c in run_mock.call_args_list]

    def test_check_failure_only_calls_apply_check_on_repo(self):
        with patch("os.path.isdir", return_value=True), \
             patch("subprocess.run", return_value=_proc(returncode=1)) as m:
            result = qe._apply_and_verify(REPO, "diff", "task123")
        self.assertFalse(result["success"])
        self.assertEqual(result["reason"], "diff doesn't apply")
        calls = m.call_args_list
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].args[0][:2], ["git", "apply"])
        self.assertEqual(calls[0].kwargs.get("cwd"), REPO)

    def test_no_checkout_command_ever_targets_repo(self):
        results = [
            _proc(returncode=0),          # apply --check (repo)
            _proc(returncode=0),          # worktree add (repo)
            _proc(returncode=0),          # worktree lock (repo)
            _proc(returncode=0),          # apply --3way (wt)
            _proc(returncode=0),          # test cmd (wt)
            _proc(returncode=0),          # git add -A (wt)
            _proc(returncode=0),          # git commit (wt)
            _proc(returncode=0),          # worktree remove (repo, cleanup)
        ]
        with patch("os.path.isdir", return_value=True), \
             patch("os.makedirs"), \
             patch("subprocess.run", side_effect=results) as m:
            qe._apply_and_verify(REPO, "diff", "task123")
        for call in m.call_args_list:
            cmd = call.args[0]
            if isinstance(cmd, list) and len(cmd) >= 2 and cmd[0] == "git":
                self.assertNotEqual(cmd[1], "checkout",
                                    f"a git checkout call was made: {cmd} cwd={call.kwargs.get('cwd')}")

    def test_worktree_add_runs_with_cwd_repo(self):
        results = [_proc(returncode=0), _proc(returncode=0, stderr="")]
        with patch("os.path.isdir", side_effect=[True, True]), patch("os.makedirs"), \
             patch("subprocess.run", side_effect=results + [_proc(1)]) as m:
            qe._apply_and_verify(REPO, "diff", "task123")
        add_call = m.call_args_list[1]
        self.assertEqual(add_call.args[0][:3], ["git", "worktree", "add"])
        self.assertEqual(add_call.kwargs.get("cwd"), REPO)

    def test_apply_and_test_run_with_cwd_worktree_not_repo(self):
        wt = qe._worktree_path(REPO, "PLACEHOLDER")
        results = [
            _proc(returncode=0),                 # apply --check
            _proc(returncode=0),                 # worktree add
            _proc(returncode=0),                 # worktree lock
            _proc(returncode=0),                 # apply --3way
            _proc(returncode=0),                 # test
            _proc(returncode=0), _proc(returncode=0),  # add -A, commit
            _proc(returncode=0),                 # cleanup
        ]
        with patch("os.path.isdir", return_value=True), patch("os.makedirs"), \
             patch("subprocess.run", side_effect=results) as m:
            qe._apply_and_verify(REPO, "diff", "task123")
        apply_call = next(c for c in m.call_args_list if c.args[0] == ["git", "apply", "--3way"])
        test_call = next(c for c in m.call_args_list if c.kwargs.get("shell") is True)
        self.assertEqual(apply_call.args[0], ["git", "apply", "--3way"])
        self.assertNotEqual(apply_call.kwargs.get("cwd"), REPO)
        self.assertNotEqual(test_call.kwargs.get("cwd"), REPO)


class ApplyAndVerifyOutcomesTest(unittest.TestCase):
    def test_worktree_add_failure_is_reported_and_repo_untouched(self):
        results = [_proc(returncode=0), _proc(returncode=1, stderr="already exists")]
        with patch("os.path.isdir", side_effect=[True, False]), patch("os.makedirs"), \
             patch("subprocess.run", side_effect=results) as m:
            result = qe._apply_and_verify(REPO, "diff", "task123")
        self.assertFalse(result["success"])
        self.assertIn("worktree add failed", result["reason"])

    def test_apply_failure_inside_worktree_cleans_up_without_keeping_branch(self):
        results = [
            _proc(returncode=0),   # check
            _proc(returncode=0),   # worktree add
            _proc(returncode=0),   # worktree lock
            _proc(returncode=1),   # apply --3way fails
        ]
        with patch("os.path.isdir", return_value=True), patch("os.makedirs"), \
             patch.object(qe, "_cleanup_worktree") as cleanup, \
             patch("subprocess.run", side_effect=results):
            result = qe._apply_and_verify(REPO, "diff", "task123")
        self.assertFalse(result["success"])
        self.assertEqual(result["reason"], "apply failed")
        cleanup.assert_called_once()
        self.assertFalse(cleanup.call_args.kwargs.get("keep_branch", cleanup.call_args.args[-1] if cleanup.call_args.args else None))

    def test_test_failure_cleans_up_without_keeping_branch(self):
        results = [
            _proc(returncode=0),   # check
            _proc(returncode=0),   # worktree add
            _proc(returncode=0),   # worktree lock
            _proc(returncode=0),   # apply --3way
            _proc(returncode=1),   # test fails
        ]
        with patch("os.path.isdir", return_value=True), patch("os.makedirs"), \
             patch.object(qe, "_cleanup_worktree") as cleanup, \
             patch("subprocess.run", side_effect=results):
            result = qe._apply_and_verify(REPO, "diff", "task123")
        self.assertFalse(result["success"])
        self.assertEqual(result["reason"], "tests failed")
        cleanup.assert_called_once()

    def test_success_keeps_branch_and_removes_worktree_dir(self):
        results = [
            _proc(returncode=0),   # check
            _proc(returncode=0),   # worktree add
            _proc(returncode=0),   # worktree lock
            _proc(returncode=0),   # apply --3way
            _proc(returncode=0),   # test passes
            _proc(returncode=0),   # git add -A
            _proc(returncode=0),   # git commit
        ]
        with patch("os.path.isdir", return_value=True), patch("os.makedirs"), \
             patch.object(qe, "_cleanup_worktree") as cleanup, \
             patch("subprocess.run", side_effect=results):
            result = qe._apply_and_verify(REPO, "diff", "task123")
        self.assertTrue(result["success"])
        self.assertIn("branch", result)
        cleanup.assert_called_once()
        call = cleanup.call_args
        keep = call.kwargs.get("keep_branch")
        if keep is None and call.args:
            keep = call.args[-1]
        self.assertTrue(keep)

    def test_exception_during_apply_cleans_up(self):
        with patch("os.path.isdir", return_value=True), patch("os.makedirs"), \
             patch.object(qe, "_cleanup_worktree") as cleanup, \
             patch("subprocess.run", side_effect=[_proc(0), _proc(0), _proc(0), RuntimeError("boom")]):
            result = qe._apply_and_verify(REPO, "diff", "task123")
        self.assertFalse(result["success"])
        self.assertIn("boom", result["reason"])
        cleanup.assert_called_once()


class CleanupWorktreeTest(unittest.TestCase):
    def test_cleanup_removes_worktree_and_deletes_branch_when_not_keeping(self):
        with patch("subprocess.run", return_value=_proc(0)) as m:
            qe._cleanup_worktree(REPO, "/some/wt", "branch1", keep_branch=False)
        cmds = [c.args[0] for c in m.call_args_list]
        self.assertIn(["git", "worktree", "remove", "--force", "/some/wt"], cmds)
        self.assertIn(["git", "branch", "-D", "branch1"], cmds)

    def test_cleanup_keeps_branch_when_requested(self):
        with patch("subprocess.run", return_value=_proc(0)) as m:
            qe._cleanup_worktree(REPO, "/some/wt", "branch1", keep_branch=True)
        cmds = [c.args[0] for c in m.call_args_list]
        self.assertIn(["git", "worktree", "remove", "--force", "/some/wt"], cmds)
        self.assertNotIn(["git", "branch", "-D", "branch1"], cmds)

    def test_cleanup_never_raises_on_subprocess_error(self):
        with patch("subprocess.run", side_effect=RuntimeError("boom")):
            qe._cleanup_worktree(REPO, "/some/wt", "branch1", keep_branch=False)  # must not raise

    def test_cleanup_all_calls_use_repo_cwd_not_worktree(self):
        with patch("subprocess.run", return_value=_proc(0)) as m:
            qe._cleanup_worktree(REPO, "/some/wt", "branch1", keep_branch=False)
        for call in m.call_args_list:
            self.assertEqual(call.kwargs.get("cwd"), REPO)


if __name__ == "__main__":
    unittest.main()
