#!/usr/bin/env python3
"""The worktree cap must measure leakage, not provisioned capacity.

build_daemon pre-creates a worktree for each of the first ORCH_WARM_WORKTREES
queued tasks, per repo. Those are capacity. This guardrail exists to catch
runaway creation — but it counted the warm pool too, so raising the pool ate
silently into the leak budget.

That is exactly what happened. The pool default is 5 and the cap was set to 40
against it; the pool was later raised to 15 and the cap was not. The
orchestrator repo sat at 40-45 worktrees during entirely normal operation, and
with ORCH_GUARDRAIL_MODE=block every claim was refused with
"44 active worktrees (limit 40)". A well-provisioned fleet blocked itself, and
the message read like a leak — so the obvious response would have been to go
hunting for worktrees to delete.
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import workflow_guardrails as wg  # noqa: E402


def _repo_with(n_worktrees):
    """Patch _git so `worktree list --porcelain` reports n worktrees.

    git lists the main checkout first, so a repo with n additional worktrees
    prints n+1 "worktree " lines.
    """
    out = "".join(f"worktree /p/{i}\nHEAD abc\n\n" for i in range(n_worktrees + 1))
    return mock.patch.object(wg, "_git", lambda *a, **k: (0, out, ""))


class WorktreeCapTest(unittest.TestCase):
    def setUp(self):
        self._saved = {k: os.environ.get(k) for k in
                       ("ORCH_MAX_WORKTREES", "ORCH_WARM_WORKTREES",
                        "ORCH_GUARDRAIL_MODE")}
        os.environ["ORCH_MAX_WORKTREES"] = "40"
        os.environ["ORCH_WARM_WORKTREES"] = "15"
        os.environ["ORCH_GUARDRAIL_MODE"] = "block"

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_counts_worktrees_excluding_the_main_checkout(self):
        with _repo_with(12):
            self.assertEqual(wg.check_worktree_count("/repo")["count"], 12)

    def test_the_observed_outage_case_now_passes(self):
        # 44 worktrees, cap 40, warm pool 15 -> budget 55. This is the exact
        # number that was refusing every claim.
        with _repo_with(44):
            got = wg.check_worktree_count("/repo")
        self.assertTrue(got["passed"], got.get("violation"))

    def test_a_real_runaway_still_blocks(self):
        # Well past cap + pool: that is leakage, and it must still be caught.
        with _repo_with(80):
            got = wg.check_worktree_count("/repo")
        self.assertFalse(got["passed"])
        self.assertEqual(got["violation"]["guardrail"], "worktree_cap")

    def test_the_budget_moves_with_the_pool(self):
        # A future change to the pool size must not silently re-break the cap.
        os.environ["ORCH_WARM_WORKTREES"] = "0"
        with _repo_with(44):
            self.assertFalse(wg.check_worktree_count("/repo")["passed"])
        os.environ["ORCH_WARM_WORKTREES"] = "15"
        with _repo_with(44):
            self.assertTrue(wg.check_worktree_count("/repo")["passed"])

    def test_exactly_at_the_budget_is_allowed(self):
        with _repo_with(55):
            self.assertTrue(wg.check_worktree_count("/repo")["passed"])

    def test_one_over_the_budget_is_not(self):
        with _repo_with(56):
            self.assertFalse(wg.check_worktree_count("/repo")["passed"])

    def test_the_message_shows_the_arithmetic(self):
        # "44 active worktrees (limit 40)" sent the reader hunting for a leak.
        # The budget it was actually measured against belongs in the message.
        with _repo_with(80):
            reason = wg.check_worktree_count("/repo")["violation"]["detail"]
        self.assertIn("40", reason)
        self.assertIn("15", reason)
        self.assertIn("55", reason)

    def test_warn_mode_reports_without_blocking(self):
        os.environ["ORCH_GUARDRAIL_MODE"] = "warn"
        with _repo_with(80):
            got = wg.check_worktree_count("/repo")
        self.assertTrue(got["passed"])
        self.assertIn("violation", got)

    def test_an_unreadable_repo_does_not_block(self):
        # Fail-open: a guardrail that cannot measure must not refuse work.
        with mock.patch.object(wg, "_git", lambda *a, **k: (128, "", "not a repo")):
            got = wg.check_worktree_count("/nope")
        self.assertTrue(got["passed"])
        self.assertEqual(got["count"], 0)

    def test_a_negative_pool_setting_cannot_shrink_the_budget(self):
        os.environ["ORCH_WARM_WORKTREES"] = "-100"
        with _repo_with(30):
            self.assertTrue(wg.check_worktree_count("/repo")["passed"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
