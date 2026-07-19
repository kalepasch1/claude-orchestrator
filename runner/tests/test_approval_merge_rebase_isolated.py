import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import approval_merge

REPO = "/fake/repo"


def _proc(returncode=0, stdout="", stderr=""):
    p = MagicMock()
    p.returncode = returncode
    p.stdout = stdout
    p.stderr = stderr
    return p


class RebaseIsolatedNeverTouchesRepoCheckoutTest(unittest.TestCase):
    def test_no_checkout_command_targets_repo(self):
        results = [_proc(0), _proc(0), _proc(0)]  # worktree add, rebase, worktree remove
        with patch("os.makedirs"), patch("os.path.isdir", return_value=True), \
             patch("subprocess.run", side_effect=results) as m:
            approval_merge._rebase_isolated(REPO, "main", "agent/x")
        for call in m.call_args_list:
            cmd = call.args[0]
            if isinstance(cmd, list) and len(cmd) >= 2 and cmd[0] == "git":
                self.assertNotEqual(cmd[1], "checkout")

    def test_uses_forced_worktree_add(self):
        with patch("os.makedirs"), patch("os.path.isdir", return_value=True), \
             patch("subprocess.run", side_effect=[_proc(0), _proc(0), _proc(0)]) as m:
            approval_merge._rebase_isolated(REPO, "main", "agent/x")
        add_call = m.call_args_list[0]
        self.assertEqual(add_call.args[0][:3], ["git", "worktree", "add"])
        self.assertIn("-f", add_call.args[0])
        self.assertEqual(add_call.kwargs.get("cwd"), REPO)

    def test_rebase_runs_in_worktree_not_repo(self):
        with patch("os.makedirs"), patch("os.path.isdir", return_value=True), \
             patch("subprocess.run", side_effect=[_proc(0), _proc(0), _proc(0)]) as m:
            approval_merge._rebase_isolated(REPO, "main", "agent/x")
        rebase_call = m.call_args_list[1]
        self.assertEqual(rebase_call.args[0], ["git", "rebase", "main"])
        self.assertNotEqual(rebase_call.kwargs.get("cwd"), REPO)


class RebaseIsolatedOutcomesTest(unittest.TestCase):
    def test_success_returns_true(self):
        with patch("os.makedirs"), patch("os.path.isdir", return_value=True), \
             patch("subprocess.run", side_effect=[_proc(0), _proc(0), _proc(0)]):
            ok = approval_merge._rebase_isolated(REPO, "main", "agent/x")
        self.assertTrue(ok)

    def test_conflict_aborts_and_returns_false(self):
        with patch("os.makedirs"), patch("os.path.isdir", return_value=True), \
             patch("subprocess.run", side_effect=[_proc(0), _proc(1), _proc(0), _proc(0)]) as m:
            ok = approval_merge._rebase_isolated(REPO, "main", "agent/x")
        self.assertFalse(ok)
        abort_call = m.call_args_list[2]
        self.assertEqual(abort_call.args[0], ["git", "rebase", "--abort"])
        self.assertNotEqual(abort_call.kwargs.get("cwd"), REPO)

    def test_worktree_add_failure_returns_false(self):
        with patch("os.makedirs"), patch("os.path.isdir", return_value=False), \
             patch("subprocess.run", return_value=_proc(1)):
            ok = approval_merge._rebase_isolated(REPO, "main", "agent/x")
        self.assertFalse(ok)

    def test_worktree_always_removed_on_success(self):
        with patch("os.makedirs"), patch("os.path.isdir", return_value=True), \
             patch("subprocess.run", side_effect=[_proc(0), _proc(0), _proc(0)]) as m:
            approval_merge._rebase_isolated(REPO, "main", "agent/x")
        self.assertEqual(m.call_args_list[-1].args[0][:3], ["git", "worktree", "remove"])

    def test_worktree_always_removed_on_conflict(self):
        with patch("os.makedirs"), patch("os.path.isdir", return_value=True), \
             patch("subprocess.run", side_effect=[_proc(0), _proc(1), _proc(0), _proc(0)]) as m:
            approval_merge._rebase_isolated(REPO, "main", "agent/x")
        self.assertEqual(m.call_args_list[-1].args[0][:3], ["git", "worktree", "remove"])

    def test_slashes_in_branch_name_sanitized_in_worktree_path(self):
        with patch("os.makedirs"), patch("os.path.isdir", return_value=True), \
             patch("subprocess.run", side_effect=[_proc(0), _proc(0), _proc(0)]) as m:
            approval_merge._rebase_isolated(REPO, "main", "agent/x/y")
        add_call = m.call_args_list[0]
        wt_path = add_call.args[0][3]
        self.assertNotIn("/", os.path.basename(wt_path))


class IntegrateUsesIsolatedRebaseTest(unittest.TestCase):
    def test_integrate_diverged_branch_calls_rebase_isolated(self):
        with patch.object(approval_merge, "_free_branch"), \
             patch("subprocess.run", side_effect=[_proc(1)]) as m, \
             patch.object(approval_merge, "_rebase_isolated", return_value=False) as ri:
            result = approval_merge._integrate(REPO, "agent/x", "main")
        ri.assert_called_once_with(REPO, "main", "agent/x")
        self.assertEqual(result, "CONFLICT")


class OutcomeTestsPassedCheckTest(unittest.TestCase):
    def test_no_task_id_returns_true(self):
        self.assertTrue(approval_merge._last_outcome_tests_passed(None))

    def test_outcome_tests_passed_true(self):
        with patch("approval_merge.db.select", return_value=[{"tests_passed": True}]):
            self.assertTrue(approval_merge._last_outcome_tests_passed("task-1"))

    def test_outcome_tests_passed_false(self):
        with patch("approval_merge.db.select", return_value=[{"tests_passed": False}]):
            self.assertFalse(approval_merge._last_outcome_tests_passed("task-1"))

    def test_no_outcome_row_returns_true(self):
        with patch("approval_merge.db.select", return_value=[]):
            self.assertTrue(approval_merge._last_outcome_tests_passed("task-1"))

    def test_db_exception_returns_true(self):
        with patch("approval_merge.db.select", side_effect=Exception("db error")):
            self.assertTrue(approval_merge._last_outcome_tests_passed("task-1"))


class ShouldAutoapproveGatesTest(unittest.TestCase):
    def _card(self, kind="integrate"):
        return {"kind": kind}

    def _task(self, kind="build", task_id="t-1"):
        return {"kind": kind, "id": task_id}

    def test_autoapprove_disabled_returns_false(self):
        with patch.object(approval_merge, "AUTOAPPROVE_ENABLED", False):
            self.assertFalse(approval_merge._should_autoapprove(self._card(), self._task()))

    def test_wrong_card_kind_returns_false(self):
        with patch("approval_merge.db.select", return_value=[{"tests_passed": True}]):
            self.assertFalse(approval_merge._should_autoapprove(self._card("legal"), self._task()))

    def test_wrong_task_kind_returns_false(self):
        with patch("approval_merge.db.select", return_value=[{"tests_passed": True}]):
            self.assertFalse(approval_merge._should_autoapprove(self._card(), self._task("research")))

    def test_tests_failed_returns_false(self):
        with patch("approval_merge.db.select", return_value=[{"tests_passed": False}]):
            self.assertFalse(approval_merge._should_autoapprove(self._card(), self._task()))

    def test_all_criteria_met_returns_true(self):
        with patch("approval_merge.db.select", return_value=[{"tests_passed": True}]):
            self.assertTrue(approval_merge._should_autoapprove(self._card(), self._task()))

    def test_no_outcome_history_returns_true(self):
        with patch("approval_merge.db.select", return_value=[]):
            self.assertTrue(approval_merge._should_autoapprove(self._card(), self._task()))


if __name__ == "__main__":
    unittest.main()


class RebaseConflictDetailsTest(unittest.TestCase):
    def test_returns_overlapping_files(self):
        def fake_run(cmd, **kwargs):
            if "merge-base" in cmd:
                return _proc(0, stdout="abc123\n")
            elif "diff" in cmd and cmd[-1] == "main":
                return _proc(0, stdout="file1.py\nfile2.py\n")
            elif "diff" in cmd:
                return _proc(0, stdout="file2.py\nfile3.py\n")
            return _proc(0)
        with patch("subprocess.run", side_effect=fake_run):
            result = approval_merge._rebase_conflict_details(REPO, "main", "agent/x")
        self.assertEqual(result["conflicting_files"], ["file2.py"])
        self.assertEqual(result["base_only"], 1)
        self.assertEqual(result["branch_only"], 1)

    def test_returns_empty_on_merge_base_failure(self):
        with patch("subprocess.run", return_value=_proc(1)):
            result = approval_merge._rebase_conflict_details(REPO, "main", "agent/x")
        self.assertEqual(result["conflicting_files"], [])

    def test_caps_conflicting_files_at_20(self):
        files = "\n".join(f"f{i}.py" for i in range(30))
        def fake_run(cmd, **kwargs):
            if "merge-base" in cmd:
                return _proc(0, stdout="abc\n")
            return _proc(0, stdout=files + "\n")
        with patch("subprocess.run", side_effect=fake_run):
            result = approval_merge._rebase_conflict_details(REPO, "main", "agent/x")
        self.assertLessEqual(len(result["conflicting_files"]), 20)
