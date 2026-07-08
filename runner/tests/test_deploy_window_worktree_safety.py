import os
import sys
import types
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import deploy_window as dw

REPO = "/fake/repo"


def _proc(returncode=0, stdout="", stderr=""):
    p = MagicMock()
    p.returncode = returncode
    p.stdout = stdout
    p.stderr = stderr
    return p


class WorktreePathTest(unittest.TestCase):
    def test_path_is_sibling_wt_dir(self):
        path = dw._worktree_path("/x/repo", "main")
        self.assertEqual(path, "/x/repo-wt/deploy-main")

    def test_slashes_in_branch_name_are_sanitized(self):
        path = dw._worktree_path("/x/repo", "release/1.0")
        self.assertNotIn("/", os.path.basename(path))


class RunInBranchWorktreeTest(unittest.TestCase):
    def test_uses_force_flag_so_an_already_checked_out_branch_still_works(self):
        with patch("os.makedirs"), patch("os.path.isdir", return_value=True), \
             patch("subprocess.run", side_effect=[_proc(0), _proc(0)]) as m:
            result = dw._run_in_branch_worktree(REPO, "main", lambda wt: "ran")
        self.assertEqual(result, "ran")
        add_call = m.call_args_list[0]
        self.assertIn("-f", add_call.args[0])
        self.assertEqual(add_call.kwargs.get("cwd"), REPO)

    def test_returns_none_when_worktree_add_fails(self):
        with patch("os.makedirs"), patch("os.path.isdir", return_value=False), \
             patch("subprocess.run", return_value=_proc(1)):
            result = dw._run_in_branch_worktree(REPO, "main", lambda wt: "should not run")
        self.assertIsNone(result)

    def test_ops_never_called_when_worktree_missing_after_add(self):
        called = []
        with patch("os.makedirs"), patch("os.path.isdir", return_value=False), \
             patch("subprocess.run", return_value=_proc(0)):
            dw._run_in_branch_worktree(REPO, "main", lambda wt: called.append(wt))
        self.assertEqual(called, [])

    def test_worktree_always_removed_even_when_ops_raises(self):
        with patch("os.makedirs"), patch("os.path.isdir", return_value=True), \
             patch("subprocess.run", side_effect=[_proc(0), _proc(0)]) as m:
            with self.assertRaises(RuntimeError):
                dw._run_in_branch_worktree(REPO, "main", lambda wt: (_ for _ in ()).throw(RuntimeError("boom")))
        remove_call = m.call_args_list[-1]
        self.assertEqual(remove_call.args[0][:3], ["git", "worktree", "remove"])

    def test_removal_failure_does_not_mask_ops_result(self):
        with patch("os.makedirs"), patch("os.path.isdir", return_value=True), \
             patch("subprocess.run", side_effect=[_proc(0), RuntimeError("remove failed")]):
            result = dw._run_in_branch_worktree(REPO, "main", lambda wt: "success value")
        self.assertEqual(result, "success value")

    def test_ops_receives_the_worktree_path_not_repo(self):
        seen = {}
        with patch("os.makedirs"), patch("os.path.isdir", return_value=True), \
             patch("subprocess.run", side_effect=[_proc(0), _proc(0)]):
            dw._run_in_branch_worktree(REPO, "main", lambda wt: seen.setdefault("wt", wt))
        self.assertNotEqual(seen["wt"], REPO)
        self.assertEqual(seen["wt"], dw._worktree_path(REPO, "main"))


class FfMergeNeverTouchesRepoTest(unittest.TestCase):
    def test_success_path(self):
        with patch("os.makedirs"), patch("os.path.isdir", return_value=True), \
             patch("subprocess.run", side_effect=[_proc(0), _proc(0), _proc(0)]) as m:
            ok = dw._ff_merge(REPO, "staging", "main")
        self.assertTrue(ok)
        # none of the calls should be a checkout in repo
        for call in m.call_args_list:
            cmd = call.args[0]
            if isinstance(cmd, list) and len(cmd) >= 2:
                self.assertNotEqual(cmd[1], "checkout")

    def test_merge_runs_with_cwd_worktree(self):
        with patch("os.makedirs"), patch("os.path.isdir", return_value=True), \
             patch("subprocess.run", side_effect=[_proc(0), _proc(0), _proc(0)]) as m:
            dw._ff_merge(REPO, "staging", "main")
        merge_call = m.call_args_list[1]
        self.assertEqual(merge_call.args[0], ["git", "merge", "--ff-only", "staging"])
        self.assertNotEqual(merge_call.kwargs.get("cwd"), REPO)

    def test_merge_conflict_returns_false(self):
        with patch("os.makedirs"), patch("os.path.isdir", return_value=True), \
             patch("subprocess.run", side_effect=[_proc(0), _proc(1), _proc(0)]):
            ok = dw._ff_merge(REPO, "staging", "main")
        self.assertFalse(ok)

    def test_worktree_creation_failure_returns_false_not_raise(self):
        with patch("os.makedirs"), patch("os.path.isdir", return_value=False), \
             patch("subprocess.run", return_value=_proc(1)):
            ok = dw._ff_merge(REPO, "staging", "main")
        self.assertFalse(ok)

    def test_exception_returns_false(self):
        with patch("os.makedirs"), patch("subprocess.run", side_effect=RuntimeError("boom")):
            ok = dw._ff_merge(REPO, "staging", "main")
        self.assertFalse(ok)


class EvaluateProjectRollbackTest(unittest.TestCase):
    def test_rollback_uses_worktree_not_repo_checkout(self):
        canary_mock = types.SimpleNamespace(evaluate=lambda url: {"verdict": "rollback", "reason": "p95 too high"})
        db_mock = types.SimpleNamespace(insert=lambda *a, **kw: None)
        with patch.object(dw, "canary", canary_mock), patch.object(dw, "db", db_mock), \
             patch("subprocess.check_output", return_value="3\n"), \
             patch("os.makedirs"), patch("os.path.isdir", return_value=True), \
             patch("subprocess.run", side_effect=[_proc(0), _proc(0), _proc(0)]) as m:
            dw._evaluate_project(REPO, "proj", "http://metrics")
        for call in m.call_args_list:
            cmd = call.args[0]
            if isinstance(cmd, list) and len(cmd) >= 2:
                self.assertNotEqual(cmd[1], "checkout")

    def test_rollback_records_approval_even_if_worktree_fails(self):
        canary_mock = types.SimpleNamespace(evaluate=lambda url: {"verdict": "rollback", "reason": "errors spiked"})
        inserted = []
        db_mock = types.SimpleNamespace(insert=lambda t, r: inserted.append(r))
        with patch.object(dw, "canary", canary_mock), patch.object(dw, "db", db_mock), \
             patch("subprocess.check_output", return_value="1\n"), \
             patch.object(dw, "_run_in_branch_worktree", side_effect=RuntimeError("boom")):
            dw._evaluate_project(REPO, "proj", "http://metrics")
        self.assertEqual(len(inserted), 1)
        self.assertIn("rollback", inserted[0]["title"].lower())

    def test_promote_path_still_calls_ff_merge(self):
        canary_mock = types.SimpleNamespace(evaluate=lambda url: {"verdict": "promote", "reason": "all green"})
        db_mock = types.SimpleNamespace(insert=lambda *a, **kw: None)
        with patch.object(dw, "canary", canary_mock), patch.object(dw, "db", db_mock), \
             patch("subprocess.check_output", return_value="2\n"), \
             patch.object(dw, "_ff_merge", return_value=True) as ff:
            dw._evaluate_project(REPO, "proj", "http://metrics")
        ff.assert_called_once_with(REPO, dw.STAGING, dw.MAIN)


if __name__ == "__main__":
    unittest.main()
