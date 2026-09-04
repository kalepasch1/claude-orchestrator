"""Missing-branch recovery: normal path, and the edge cases that look like it.

Owner module is runner/branch_recovery.py (detect_missing_branches /
recover_missing_branches). The existing suites cover repository validation and
patch application; what was missing is the batch recovery loop's own decisions
and, most importantly, the distinction the module's own comments call out:

    a non-zero `git ls-remote` collapses "branch genuinely absent", "PAT
    expired", "repo deleted" and "network down" into one False.

Confusing a transient outage with a lost branch sends recoverable work to the
unrecoverable pile, so "truly missing" and "could not tell" are pinned as
separate outcomes here rather than assumed.
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import branch_recovery as br


class TestDetectMissingBranches(unittest.TestCase):
    def test_reports_only_the_branches_that_are_absent(self):
        present = {"agent/kept"}
        with patch.object(br, "_is_git_repo", return_value=True), \
             patch.object(br, "_branch_exists_local",
                          side_effect=lambda repo, b: b in present):
            missing = br.detect_missing_branches("/repo", ["agent/kept", "agent/gone"])
        self.assertEqual(missing, ["agent/gone"])

    def test_nothing_missing_returns_empty_not_none(self):
        with patch.object(br, "_is_git_repo", return_value=True), \
             patch.object(br, "_branch_exists_local", return_value=True):
            self.assertEqual(br.detect_missing_branches("/repo", ["agent/a", "agent/b"]), [])

    def test_a_non_repo_path_is_fail_soft(self):
        # Must not raise, and must not claim every branch is missing — that would
        # queue a recovery for work that was never lost.
        with patch.object(br, "_is_git_repo", return_value=False):
            self.assertEqual(br.detect_missing_branches("/not/a/repo", ["agent/a"]), [])

    def test_disabled_module_detects_nothing(self):
        with patch.object(br, "ENABLED", False):
            self.assertEqual(br.detect_missing_branches("/repo", ["agent/a"]), [])


class TestTransientRemoteFailureIsNotAMissingBranch(unittest.TestCase):
    """`ls-remote` failing is not evidence the branch is gone."""

    def test_absent_branch_reports_false(self):
        with patch.object(br, "_git", return_value=(0, "", "")):
            self.assertFalse(br._branch_on_remote("/repo", "agent/gone"))

    def test_present_branch_reports_true(self):
        with patch.object(br, "_git", return_value=(0, "abc123\trefs/heads/agent/x", "")):
            self.assertTrue(br._branch_on_remote("/repo", "agent/x"))

    def test_a_network_failure_also_reports_false_which_is_why_validation_exists(self):
        # Documented behaviour, pinned so the ambiguity stays visible: a DNS
        # failure is indistinguishable here from a genuinely absent branch.
        with patch.object(br, "_git",
                          return_value=(128, "", "fatal: Could not resolve host: github.com")):
            self.assertFalse(br._branch_on_remote("/repo", "agent/x"))

    def test_repository_validation_separates_unreachable_from_missing(self):
        # The actual protection: recovery must be able to say "could not tell"
        # instead of "lost". validate_repository is what distinguishes them.
        self.assertTrue(hasattr(br, "validate_repository"))
        with patch.object(br, "_is_git_repo", return_value=True), \
             patch.object(br, "_git",
                          return_value=(128, "", "fatal: Could not resolve host: github.com")):
            verdict = br.validate_repository("/repo")
        self.assertFalse(verdict.get("ok"))
        self.assertNotIn(verdict.get("reason"), (None, "", "exhausted"))


class TestRecoverMissingBranchesBatch(unittest.TestCase):
    def test_an_existing_branch_is_skipped_not_recovered(self):
        # The normal steady state: nothing was lost, so nothing must be rewritten.
        with patch.object(br, "_is_git_repo", return_value=True), \
             patch.object(br, "_branch_exists_local", return_value=True):
            out = br.recover_missing_branches([{"slug": "s1", "repo": "/repo"}])
        self.assertEqual(out["reviewed"], 1)
        self.assertEqual(out["skipped"], 1)
        self.assertEqual(out["merged"], 0)
        self.assertEqual(out["details"][0]["reason"], "branch already exists locally")

    def test_entries_without_slug_or_repo_are_skipped(self):
        out = br.recover_missing_branches([{"slug": "", "repo": "/repo"},
                                           {"slug": "s", "repo": ""}])
        self.assertEqual(out["skipped"], 2)
        self.assertEqual(out["merged"], 0)

    def test_a_malformed_entry_does_not_abort_the_batch(self):
        with patch.object(br, "_is_git_repo", return_value=True), \
             patch.object(br, "_branch_exists_local", return_value=True):
            out = br.recover_missing_branches(["not-a-dict", {"slug": "s1", "repo": "/repo"}])
        self.assertEqual(out["reviewed"], 2)
        self.assertEqual(out["skipped"], 2)

    def test_project_isolation_refuses_another_projects_branch(self):
        # Recovering into the wrong repo is worse than not recovering.
        out = br.recover_missing_branches(
            [{"slug": "s1", "repo": "/repo", "project": "apparently"}], project="tomorrow")
        self.assertEqual(out["skipped"], 1)
        self.assertIn("project isolation", out["details"][0]["reason"])

    def test_an_invalid_repo_path_is_quarantined_not_silently_dropped(self):
        with patch.object(br, "_is_git_repo", return_value=False):
            out = br.recover_missing_branches([{"slug": "s1", "repo": "/gone"}])
        self.assertEqual(out["quarantined"], 1)
        self.assertIn("invalid git path", out["details"][0]["reason"])

    def test_an_empty_batch_is_a_no_op(self):
        out = br.recover_missing_branches([])
        self.assertEqual(out, {"reviewed": 0, "merged": 0, "quarantined": 0,
                               "skipped": 0, "details": []})

    def test_disabled_module_recovers_nothing(self):
        with patch.object(br, "ENABLED", False):
            out = br.recover_missing_branches([{"slug": "s1", "repo": "/repo"}])
        self.assertEqual(out["reviewed"], 0)

    def test_a_recovery_failure_is_quarantined_with_its_reason(self):
        fake = type("M", (), {
            "recover": staticmethod(lambda *a, **k: {"ok": False, "reason": "no patch found"}),
            "_apply_diff_to_branch": staticmethod(lambda *a, **k: {"ok": False}),
        })
        with patch.object(br, "_is_git_repo", return_value=True), \
             patch.object(br, "_branch_exists_local", return_value=False), \
             patch.object(br, "_library_patch", return_value=None), \
             patch.dict(sys.modules, {"patch_recovery": fake}):
            out = br.recover_missing_branches([{"slug": "s1", "repo": "/repo"}])
        self.assertEqual(out["quarantined"], 1)
        self.assertIn("no patch found", out["details"][0]["reason"])

    def test_recovery_succeeds_only_when_the_focused_tests_pass(self):
        fake = type("M", (), {
            "recover": staticmethod(lambda *a, **k: {"ok": True, "method": "reflog"}),
            "_apply_diff_to_branch": staticmethod(lambda *a, **k: {"ok": True, "method": "library"}),
        })
        common = dict(spec=None)
        with patch.object(br, "_is_git_repo", return_value=True), \
             patch.object(br, "_branch_exists_local", return_value=False), \
             patch.object(br, "_library_patch", return_value=None), \
             patch.object(br, "_mark_task_state", return_value=None), \
             patch.dict(sys.modules, {"patch_recovery": fake}):
            with patch.object(br, "_run_focused_tests", return_value=(True, "")):
                good = br.recover_missing_branches([{"slug": "s1", "repo": "/repo"}])
            with patch.object(br, "_run_focused_tests", return_value=(False, "2 failed")):
                bad = br.recover_missing_branches([{"slug": "s2", "repo": "/repo"}])
        self.assertEqual(good["merged"], 1)
        # A green apply with red tests must NOT be reported as recovered.
        self.assertEqual(bad["merged"], 0)
        self.assertEqual(bad["quarantined"], 1)
        self.assertIn("focused tests failed", bad["details"][0]["reason"])

    def test_an_unexpected_exception_quarantines_rather_than_aborting(self):
        def boom(*a, **k):
            raise RuntimeError("git exploded")
        with patch.object(br, "_is_git_repo", side_effect=boom):
            out = br.recover_missing_branches([{"slug": "s1", "repo": "/repo"},
                                               {"slug": "s2", "repo": "/repo"}])
        self.assertEqual(out["reviewed"], 2, "the loop must continue past a failure")
        self.assertEqual(out["quarantined"], 2)


if __name__ == "__main__":
    unittest.main()
