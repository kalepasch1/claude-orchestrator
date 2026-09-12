#!/usr/bin/env python3
"""The merge-train regression guard must give each task its own regression repair budget.

REPORTED: "merge-train-regression-guard: quarantined as regressfail after 2 repair
attempts" — 26 tasks in 7 days, 16 still in the last 14.

ROOT CAUSE: the guard gated on `transient_retries`, which is a SINGLE column shared by
every transient cause. conflict, testfail, buildfail, missing-branch, approval_merge and
dag_optimizer all increment it. A task that had already burned the budget on two
CONFLICTS therefore arrived at the regression guard with tr=2 >= cap=2 and was
quarantined on its FIRST regression finding, with zero chances to restore the deleted
symbols — while writing "after 2 repair attempts" into its own note. Premature, and a
false statement in the audit trail.

FIX: the regression count is read back from the `[regression-quarantine N/cap]` marker
the guard already writes, so the budget is genuinely per-cause with no schema change,
and `transient_retries` still advances so the GLOBAL non-convergence ceiling in
agentic_repair is unaffected.

Proof: python3 -m pytest runner/tests/test_merge_train_regression_budget.py -q
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import merge_train  # noqa: E402


class TestRegressionAttemptCount(unittest.TestCase):
    def test_no_note_means_no_regression_attempts_yet(self):
        self.assertEqual(merge_train._regression_attempts({}), 0)
        self.assertEqual(merge_train._regression_attempts({"note": None}), 0)
        self.assertEqual(merge_train._regression_attempts({"note": ""}), 0)

    def test_an_unrelated_note_means_zero(self):
        task = {"note": "integrate CONFLICT — could not rebase; [conflict-redo 2/2]"}
        self.assertEqual(merge_train._regression_attempts(task), 0)

    def test_the_marker_is_read_back(self):
        task = {"note": "integrate REGRESSFAIL ... [regression-quarantine 1/2] findings"}
        self.assertEqual(merge_train._regression_attempts(task), 1)

    def test_the_highest_marker_wins(self):
        task = {"note": "[regression-quarantine 1/2] ... later ... "
                        "[regression-quarantine 2/2]"}
        self.assertEqual(merge_train._regression_attempts(task), 2)

    def test_whitespace_variants_still_parse(self):
        self.assertEqual(
            merge_train._regression_attempts({"note": "[regression-quarantine  3 / 5 ]"}), 3)

    def test_it_never_raises(self):
        for bad in (None, "task", 7, [], {"note": 5}, {"note": b"x"}):
            self.assertEqual(merge_train._regression_attempts(bad), 0, bad)

    def test_it_errs_toward_giving_the_budget(self):
        """A wrong quarantine strands committed work; an extra pass costs one cycle."""
        self.assertEqual(merge_train._regression_attempts({"note": "[regression-quarantine ]"}), 0)


class TestBudgetIsPerCause(unittest.TestCase):
    """The regression budget must not be consumed by unrelated failure causes."""

    def _patch_for(self, task, cap="2"):
        captured = {}

        def _fake_task_patch(t, patch):
            captured["patch"] = patch

        saved = {
            "_task_patch": merge_train._task_patch,
            "agentic_repair": merge_train.agentic_repair,
            "db": merge_train.db,
            "_attribute_train_outcome": merge_train._attribute_train_outcome,
            "_log": merge_train._log,
            "_pm": merge_train._pm,
        }
        merge_train._task_patch = _fake_task_patch
        merge_train.agentic_repair = type("_AR", (), {
            "repair_patch": staticmethod(
                lambda *a, **k: {"state": "QUEUED", "account": None})})
        merge_train.db = type("_DB", (), {
            "update": staticmethod(lambda *a, **k: None),
            "insert": staticmethod(lambda *a, **k: None)})
        merge_train._attribute_train_outcome = lambda *a, **k: None
        merge_train._log = lambda *a, **k: None
        merge_train._pm = None
        os.environ["MERGE_REGRESSION_REDO_CAP"] = cap
        try:
            merge_train._quarantine_regression_failure(
                repo="/tmp/repo", card={"id": "c1"}, slug="s1", task=task,
                pname="beethoven", branch="agent/s1", base="master",
                detail="app.py::run deleted")
        finally:
            for name, value in saved.items():
                setattr(merge_train, name, value)
            os.environ.pop("MERGE_REGRESSION_REDO_CAP", None)
        return captured.get("patch", {})

    def test_conflict_retries_no_longer_consume_the_regression_budget(self):
        """The reported bug, directly: tr=2 from conflicts, first regression finding."""
        patch = self._patch_for({"transient_retries": 2, "note": "conflict stuff"})
        self.assertNotEqual(patch.get("state"), "QUARANTINED",
                            "quarantined on the FIRST regression finding")
        self.assertIn("[regression-quarantine 1/2]", patch.get("note", ""))

    def test_a_fresh_task_gets_a_repair_not_a_quarantine(self):
        patch = self._patch_for({})
        self.assertNotEqual(patch.get("state"), "QUARANTINED")

    def test_the_budget_still_runs_out_after_cap_regression_attempts(self):
        patch = self._patch_for({"note": "[regression-quarantine 2/2]",
                                 "transient_retries": 2})
        self.assertEqual(patch.get("state"), "QUARANTINED")

    def test_the_quarantine_note_states_the_real_count(self):
        patch = self._patch_for({"note": "[regression-quarantine 2/2]"})
        self.assertIn("after 2 regression repair attempts", patch.get("note", ""))

    def test_the_global_counter_still_advances(self):
        """The fleet-wide non-convergence ceiling must not be reset by the per-cause fix."""
        patch = self._patch_for({"transient_retries": 7, "note": "conflict stuff"})
        self.assertEqual(patch.get("transient_retries"), 8)

    def test_the_marker_increments_across_passes(self):
        patch = self._patch_for({"note": "[regression-quarantine 1/2]"})
        self.assertIn("[regression-quarantine 2/2]", patch.get("note", ""))

    def test_a_higher_cap_grants_more_regression_attempts(self):
        patch = self._patch_for({"note": "[regression-quarantine 2/5]"}, cap="5")
        self.assertNotEqual(patch.get("state"), "QUARANTINED")


if __name__ == "__main__":
    unittest.main()
