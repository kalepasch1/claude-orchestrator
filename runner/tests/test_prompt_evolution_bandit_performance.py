#!/usr/bin/env python3
"""Performance/analysis layer of prompt_evolution_bandit.

test_prompt_evolution_bandit.py covers the arm mechanics (they live in
BanditSelector). This file covers the part that used to be a stub: reading real
rewards out of `outcomes.experiment_variant` and explaining the accept() decision.

The gates worth pinning down here are the ones that would fail silently:

  * the experiment_id prefix filter — without it a model-routing experiment's
    "control"/"candidate" rows are folded in as prompt variants and the arm
    statistics are poisoned by data about a different experiment entirely;
  * the reward scale — accept()'s MARGIN default of 0.05 is a *rate* difference,
    so a per-dollar reward (bandit._reward, unbounded above) would make the gate
    meaningless. Rewards must stay in [0, 1];
  * the 1000-row PostgREST cap — asking for more does not widen the window, it
    only hides the truncation;
  * fail-soft — a DB outage must yield a cold start, not an exception that wedges
    the runner that called warm_start().
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import prompt_evolution_bandit as peb  # noqa: E402


class _FakeDb:
    """db-module stand-in. Records the params it was asked for."""

    def __init__(self, rows=None, raise_on_select=False):
        self.rows = rows or []
        self.raise_on_select = raise_on_select
        self.last_params = None
        self.calls = 0

    def select(self, table, params=None):
        self.calls += 1
        self.last_params = params or {}
        if self.raise_on_select:
            raise RuntimeError("supabase unreachable")
        assert table == "outcomes", table
        return list(self.rows)


def _row(variant, tests_passed=True, integrated=True, experiment_id="prompt-x"):
    return {"experiment_id": experiment_id, "experiment_variant": variant,
            "tests_passed": tests_passed, "integrated": integrated}


class TestOutcomeReward(unittest.TestCase):

    def test_reward_tiers(self):
        self.assertEqual(peb._outcome_reward(_row("a", True, True)), 1.0)
        self.assertEqual(peb._outcome_reward(_row("a", True, False)), 0.2)
        self.assertEqual(peb._outcome_reward(_row("a", False, False)), 0.0)

    def test_reward_is_bounded_so_the_accept_margin_stays_meaningful(self):
        for tp in (True, False):
            for integ in (True, False):
                r = peb._outcome_reward(_row("a", tp, integ))
                self.assertGreaterEqual(r, 0.0)
                self.assertLessEqual(r, 1.0)

    def test_integrated_without_tests_is_not_full_credit(self):
        # A merge that never passed tests is not evidence the template is good.
        self.assertEqual(peb._outcome_reward(_row("a", False, True)), 0.0)

    def test_missing_keys_do_not_raise(self):
        self.assertEqual(peb._outcome_reward({}), 0.0)


class TestLoadPerformance(unittest.TestCase):

    def test_groups_rewards_by_variant(self):
        db = _FakeDb([_row("base"), _row("cot"), _row("base", True, False)])
        perf = peb.load_performance(db)
        self.assertEqual(sorted(perf), ["base", "cot"])
        self.assertEqual(perf["base"], [1.0, 0.2])
        self.assertEqual(perf["cot"], [1.0])

    def test_filters_to_prompt_experiments(self):
        db = _FakeDb([])
        peb.load_performance(db)
        self.assertEqual(db.last_params.get("experiment_id"), "like.prompt%")

    def test_experiment_prefix_is_overridable(self):
        db = _FakeDb([])
        peb.load_performance(db, experiment_prefix="tpl")
        self.assertEqual(db.last_params.get("experiment_id"), "like.tpl%")

    def test_empty_prefix_disables_the_filter(self):
        db = _FakeDb([])
        peb.load_performance(db, experiment_prefix="")
        self.assertNotIn("experiment_id", db.last_params)

    def test_null_variants_are_excluded_server_side(self):
        db = _FakeDb([])
        peb.load_performance(db)
        self.assertEqual(db.last_params.get("experiment_variant"), "not.is.null")

    def test_window_is_deterministically_ordered(self):
        # An unordered sample window is not reproducible between runs.
        db = _FakeDb([])
        peb.load_performance(db)
        self.assertIn("created_at.desc", db.last_params.get("order", ""))

    def test_limit_is_capped_at_the_postgrest_page_size(self):
        db = _FakeDb([])
        peb.load_performance(db, limit=50000)
        self.assertEqual(db.last_params.get("limit"), str(peb._MAX_ROWS))

    def test_garbage_limit_falls_back_to_the_cap(self):
        db = _FakeDb([])
        peb.load_performance(db, limit="not-a-number")
        self.assertEqual(db.last_params.get("limit"), str(peb._MAX_ROWS))

    def test_rows_with_no_variant_are_skipped(self):
        db = _FakeDb([{"experiment_variant": None, "tests_passed": True},
                      {"experiment_variant": "", "tests_passed": True},
                      _row("real")])
        self.assertEqual(list(peb.load_performance(db)), ["real"])

    def test_db_failure_is_a_cold_start_not_an_exception(self):
        db = _FakeDb(raise_on_select=True)
        self.assertEqual(peb.load_performance(db), {})


class TestWarmStart(unittest.TestCase):

    def setUp(self):
        peb.reset()
        self.addCleanup(peb.reset)

    def test_folds_history_into_the_singleton(self):
        db = _FakeDb([_row("base"), _row("base"), _row("cot", True, False)])
        self.assertEqual(peb.warm_start(db), 3)
        s = peb.stats()
        self.assertEqual(s["counts"]["base"], 2)
        self.assertEqual(s["counts"]["cot"], 1)
        self.assertAlmostEqual(s["average_reward"]["base"], 1.0)
        self.assertAlmostEqual(s["average_reward"]["cot"], 0.2)

    def test_retired_variants_are_not_resurrected_as_arms(self):
        db = _FakeDb([_row("base"), _row("deleted_variant")])
        folded = peb.warm_start(db, arm_ids=["base"])
        self.assertEqual(folded, 1)
        self.assertNotIn("deleted_variant", peb.stats().get("counts", {}))

    def test_db_failure_starts_cold_without_raising(self):
        db = _FakeDb(raise_on_select=True)
        self.assertEqual(peb.warm_start(db), 0)


class TestAnalyze(unittest.TestCase):

    def setUp(self):
        peb.reset()
        self.addCleanup(peb.reset)

    def test_no_data(self):
        a = peb.analyze()
        self.assertEqual(a["blocked_by"], "no-data")
        self.assertEqual(a["leader"], "")
        self.assertFalse(a["accepted"])

    def test_single_arm_has_no_incumbent_to_beat(self):
        peb.update("solo", 1.0)
        a = peb.analyze()
        self.assertEqual(a["leader"], "solo")
        self.assertEqual(a["blocked_by"], "no-incumbent")
        self.assertFalse(a["accepted"])

    def test_insufficient_pulls_is_distinguished_from_insufficient_margin(self):
        peb.update("cot", 1.0)          # 1 pull, way ahead
        peb.update("base", 0.0)
        a = peb.analyze()
        self.assertEqual(a["leader"], "cot")
        self.assertEqual(a["runner_up"], "base")
        self.assertEqual(a["blocked_by"], "insufficient-pulls")

    def test_insufficient_margin_when_arms_are_tied(self):
        for _ in range(peb.MIN_PULLS + 2):
            peb.update("cot", 0.5)
            peb.update("base", 0.5)
        a = peb.analyze()
        self.assertEqual(a["blocked_by"], "insufficient-margin")
        self.assertAlmostEqual(a["margin"], 0.0)
        self.assertFalse(a["accepted"])

    def test_a_clear_winner_is_accepted_and_agrees_with_accept(self):
        for _ in range(peb.MIN_PULLS + 2):
            peb.update("cot", 1.0)
            peb.update("base", 0.0)
        a = peb.analyze()
        self.assertEqual(a["leader"], "cot")
        self.assertEqual(a["blocked_by"], "")
        self.assertTrue(a["accepted"])
        self.assertEqual(a["accepted"], peb.accept("cot"))

    def test_arms_are_ranked_best_first(self):
        peb.update("low", 0.1)
        peb.update("high", 0.9)
        peb.update("mid", 0.5)
        self.assertEqual(list(peb.analyze()["arms"]), ["high", "mid", "low"])

    def test_arm_filter_restricts_the_analysis(self):
        peb.update("a", 1.0)
        peb.update("b", 0.0)
        a = peb.analyze(arm_ids=["a"])
        self.assertEqual(list(a["arms"]), ["a"])
        self.assertEqual(a["blocked_by"], "no-incumbent")

    def test_thresholds_are_reported_so_the_remedy_is_obvious(self):
        a = peb.analyze()
        self.assertEqual(a["min_pulls"], peb.MIN_PULLS)
        self.assertAlmostEqual(a["required_margin"], peb.MARGIN)


if __name__ == "__main__":
    unittest.main()
