"""Missing an ambitious target is not the same as making things worse.

build_proposal sets required_margin = max(1.10, predicted * 0.5), and predicted is capped
at min(headroom, 10). A bottleneck with 16.09x of measured headroom therefore demands a
5.0x improvement. Under the original binary rule anything short of that was 'regressed' --
and two things act on that word: settle() reverts the commit, and the release value gate
holds any batch carrying one. A genuine 1.6x win (a 32.17% quarantine rate cut to 20%)
would have been reverted and would have blocked the release.

Three verdicts now:
    validated      mult >= required_margin      hit its own declared target
    underdelivered 1.0 <= mult <  margin        improved, but by less than predicted
    regressed      mult < 1.0                   actually made the metric worse
"""
import os
import sys
import unittest

RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RUNNER)
import improvement_verify as iv  # noqa: E402

# The real proposal the miner produced on 2026-09-01.
REAL = {"baseline_value": 32.17, "comparator": "lt", "required_margin": 5.0,
        "evaluate_after": None, "id": "p1", "task_slug": "improve-quarantine_rate_pct"}


def verdict(realized, p=None):
    return iv.evaluate(dict(p or REAL), injected=realized)["verdict"]


class VerdictSemanticsTests(unittest.TestCase):
    def test_hitting_the_target_validates(self):
        self.assertEqual(verdict(6.0), "validated")     # 5.36x

    def test_a_real_win_short_of_target_is_not_a_regression(self):
        """32.17% -> 20% is a 1.6x improvement. It must never be called a regression."""
        self.assertEqual(verdict(20.0), "underdelivered")

    def test_getting_worse_is_a_regression(self):
        self.assertEqual(verdict(40.0), "regressed")    # 0.80x

    def test_exactly_flat_is_a_regression_boundary(self):
        self.assertEqual(verdict(32.17), "underdelivered")  # 1.0x — no worse

    def test_exactly_on_margin_validates(self):
        self.assertEqual(verdict(32.17 / 5.0), "validated")

    # ── the perfect-outcome bug ──────────────────────────────────────────────
    def test_reaching_zero_is_the_best_outcome_not_unmeasurable(self):
        """A lower-is-better metric hitting 0 is total success; it used to return None."""
        r = iv.evaluate(dict(REAL), injected=0.0)
        self.assertEqual(r["verdict"], "validated")
        self.assertEqual(r["multiplier"], iv.PERFECT_CAP)

    def test_perfect_cap_is_finite(self):
        """An infinite multiplier would poison every calibration average."""
        self.assertTrue(0 < iv.PERFECT_CAP < float("inf"))

    def test_gt_metric_from_zero_baseline(self):
        p = {"baseline_value": 0.0, "comparator": "gt", "required_margin": 2.0,
             "evaluate_after": None}
        self.assertEqual(iv.evaluate(p, injected=5.0)["verdict"], "validated")

    # ── the falsy-zero margin ────────────────────────────────────────────────
    def test_zero_margin_is_honoured_not_replaced(self):
        p = {"baseline_value": 10.0, "comparator": "lt", "required_margin": 0.0,
             "evaluate_after": None}
        self.assertEqual(iv.evaluate(p, injected=9.0)["margin"], 0.0)

    def test_missing_margin_still_falls_back(self):
        p = {"baseline_value": 10.0, "comparator": "lt", "required_margin": None,
             "evaluate_after": None}
        self.assertEqual(iv.evaluate(p, injected=9.0)["margin"], iv.DEFAULT_MARGIN)

    # ── settle must not revert a win ─────────────────────────────────────────
    def test_underdelivered_is_never_reverted(self):
        reverted = []
        real_update, real_revert, real_cal = iv.db.update, iv.revert_commit, iv._record_calibration
        iv.db.update = lambda *a, **k: None
        iv.revert_commit = lambda *a, **k: reverted.append(a) or {"ok": True}
        iv._record_calibration = lambda *a, **k: None
        try:
            out = iv.settle(dict(REAL), injected=20.0)
        finally:
            iv.db.update, iv.revert_commit, iv._record_calibration = real_update, real_revert, real_cal
        self.assertEqual(out["verdict"], "underdelivered")
        self.assertFalse(out["rolled_back"])
        self.assertEqual(reverted, [], "a genuine improvement was reverted")

    def test_true_regression_is_still_reverted(self):
        reverted = []
        real_update, real_revert = iv.db.update, iv.revert_commit
        real_cal, real_repo = iv._record_calibration, iv._repo_for
        iv.db.update = lambda *a, **k: None
        iv.revert_commit = lambda *a, **k: reverted.append(a) or {"ok": True, "revert_sha": "abc"}
        iv._record_calibration = lambda *a, **k: None
        iv._repo_for = lambda app: "/tmp/norepo"
        try:
            out = iv.settle(dict(REAL), injected=40.0)
        finally:
            iv.db.update, iv.revert_commit = real_update, real_revert
            iv._record_calibration, iv._repo_for = real_cal, real_repo
        self.assertEqual(out["verdict"], "regressed")
        self.assertEqual(len(reverted), 1, "a real regression was not reverted")


if __name__ == "__main__":
    unittest.main()
