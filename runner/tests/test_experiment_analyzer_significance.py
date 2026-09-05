"""`significant_win` must mean something.

Adapted from the pareto-2080 patch this task points at, whose two load-bearing fixes were
(a) a value that looked defensive but substituted a meaningless number
(`deadlineDays` where `jd.deadlineDays` was meant) and (b) a missing fit term without
which predictions were not faithful to the observations (the intercept in
pricingGridReconstruction). experiment_analyzer.py carried one of each:

* `improvement = (canm - cm) / max(cm, 0.001)` — when every control run scored 0, the
  divisor collapsed to 0.001 and one passing candidate test read as a 100,000% lift, so
  the arm was adopted on a single observation.
* the module docstring promises it "identifies statistically significant winners" and it
  defines `_stddev`, but nothing ever called it — the verdict was a bare 5% effect-size
  threshold, so two indistinguishably noisy arms were declared a significant win.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import experiment_analyzer as ea  # noqa: E402


def _outcomes(control, candidate, cost=1.0):
    rows = [{"variant": "control", "tests_passed": v, "cost_usd": cost} for v in control]
    rows += [{"variant": "candidate", "tests_passed": v, "cost_usd": cost} for v in candidate]
    return rows


class FakeDB:
    def __init__(self, rows):
        self.rows = rows

    def select(self, _table, _params=None):
        return list(self.rows)


def _analyze(control, candidate, cost=1.0, monkeypatch=None):
    fake = FakeDB(_outcomes(control, candidate, cost))
    original = ea.db
    ea.db = fake
    try:
        return ea.analyze_experiment("exp-1")
    finally:
        ea.db = original


class TestRelativeImprovement:
    def test_a_zero_control_no_longer_manufactures_a_1000x_lift(self):
        """The old max(cm, 0.001) divisor turned 1 passing test into +100000%."""
        assert ea._relative_improvement(0.0, 1.0) == 1.0

    def test_both_zero_is_no_improvement(self):
        assert ea._relative_improvement(0.0, 0.0) == 0.0

    def test_a_real_ratio_is_unchanged(self):
        assert ea._relative_improvement(4.0, 5.0) == pytest.approx(0.25)

    def test_a_regression_is_negative(self):
        assert ea._relative_improvement(4.0, 2.0) == pytest.approx(-0.5)


class TestSeparationFromNoise:
    def test_two_noisy_overlapping_arms_do_not_separate(self):
        separated, detail = ea._separated_from_noise([0, 10, 0, 10], [0, 10, 10, 0])
        assert separated is False
        assert "sigma" in detail

    def test_two_consistent_and_different_arms_separate(self):
        separated, detail = ea._separated_from_noise([1, 1, 1], [5, 5, 5])
        assert separated is True
        assert "spread=0" in detail

    def test_identical_deterministic_arms_do_not_separate(self):
        separated, _ = ea._separated_from_noise([3, 3, 3], [3, 3, 3])
        assert separated is False

    def test_an_unmeasurable_spread_does_not_block(self):
        """Fail-open: never reject on a test that could not be computed."""
        separated, detail = ea._separated_from_noise([1], [5])
        assert separated is True
        assert detail == "sep=unmeasured"


class TestVerdicts:
    def test_noise_is_no_longer_adopted(self):
        result = _analyze([0, 10, 0, 10], [0, 10, 10, 0])
        assert result["status"] == "inconclusive"
        assert result["recommendation"] == "continue"

    def test_a_clean_win_is_still_adopted(self):
        """Preserve existing behaviour where the signal is real."""
        result = _analyze([1, 1, 1], [5, 5, 5])
        assert result["status"] == "significant_win"
        assert result["recommendation"] == "adopt"

    def test_a_clean_loss_is_still_rejected(self):
        result = _analyze([5, 5, 5], [1, 1, 1])
        assert result["status"] == "significant_loss"
        assert result["recommendation"] == "reject"

    def test_an_expensive_win_is_not_adopted(self):
        fake = FakeDB(
            [{"variant": "control", "tests_passed": 1, "cost_usd": 1.0} for _ in range(3)]
            + [{"variant": "candidate", "tests_passed": 5, "cost_usd": 10.0} for _ in range(3)]
        )
        original = ea.db
        ea.db = fake
        try:
            result = ea.analyze_experiment("exp-1")
        finally:
            ea.db = original
        assert result["cost_ok"] is False
        assert result["recommendation"] != "adopt"

    def test_the_verdict_reports_whether_it_separated(self):
        result = _analyze([1, 1, 1], [5, 5, 5])
        assert result["separated"] is True
        assert "sep=" in result["detail"]

    def test_insufficient_data_is_unchanged(self):
        result = _analyze([1], [5])
        assert result["status"] == "insufficient_data"
        assert result["recommendation"] == "continue"

    def test_no_db_is_still_fail_soft(self):
        original = ea.db
        ea.db = None
        try:
            result = ea.analyze_experiment("exp-1")
        finally:
            ea.db = original
        assert result["status"] == "insufficient_data"
        assert result["recommendation"] == "no_data"
