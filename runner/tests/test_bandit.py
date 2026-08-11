#!/usr/bin/env python3
"""Tests for runner/bandit.py — predictive model routing (UCB1 + epsilon floor).

bandit.choose() decides which model every task in the fleet gets routed to, and
it had no tests at all. The properties that matter are the ones that keep it
from silently degenerating into "always pick the first candidate": the cold
start must fall back to the heuristic router, an untried arm must be tried, and
the reward must actually prefer cheap successes.
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bandit
import model_router


class FakeDB:
    def __init__(self, rows=None, raise_on_select=False):
        self.rows = rows or []
        self.raise_on_select = raise_on_select
        self.calls = 0

    def select(self, table, params):
        self.calls += 1
        if self.raise_on_select:
            raise RuntimeError("supabase down")
        return list(self.rows)


def outcome(model, usd=0.10, tests_passed=True, integrated=True, kind="build"):
    return {"model": model, "usd": usd, "tests_passed": tests_passed,
            "integrated": integrated, "kind": kind}


class BanditTestCase(unittest.TestCase):
    def setUp(self):
        # The outcomes cache is module-level with a 60s TTL; without this reset
        # the first test to run would decide every later test's data.
        bandit._cache.update(t=0, rows=[])

    tearDown = setUp


# ── reward ───────────────────────────────────────────────────────────────────

class TestReward(BanditTestCase):
    def test_passed_and_integrated_earns_full_credit(self):
        self.assertAlmostEqual(bandit._reward(outcome("m", usd=0.99)), 1.0 / 1.0, places=6)

    def test_passed_but_not_integrated_earns_partial_credit(self):
        r = bandit._reward(outcome("m", usd=0.99, integrated=False))
        self.assertAlmostEqual(r, 0.2 / 1.0, places=6)

    def test_failed_tests_earn_nothing_however_cheap(self):
        self.assertEqual(bandit._reward(outcome("m", usd=0.0, tests_passed=False)), 0.0)

    def test_cheaper_success_scores_higher(self):
        cheap = bandit._reward(outcome("m", usd=0.01))
        dear = bandit._reward(outcome("m", usd=1.00))
        self.assertGreater(cheap, dear)

    def test_zero_cost_does_not_divide_by_zero(self):
        self.assertEqual(bandit._reward(outcome("m", usd=0.0)), 1.0 / 0.01)

    def test_missing_and_null_cost_are_treated_as_free(self):
        self.assertEqual(bandit._reward({"tests_passed": True, "integrated": True}),
                         bandit._reward(outcome("m", usd=0.0)))
        self.assertEqual(bandit._reward(outcome("m", usd=None)),
                         bandit._reward(outcome("m", usd=0.0)))


# ── outcome fetching / cache ─────────────────────────────────────────────────

class TestOutcomesCache(BanditTestCase):
    def test_a_db_outage_yields_no_rows_rather_than_raising(self):
        self.assertEqual(bandit._outcomes(FakeDB(raise_on_select=True)), [])

    def test_second_call_within_the_ttl_does_not_hit_the_db(self):
        db = FakeDB([outcome("a")])
        bandit._outcomes(db)
        bandit._outcomes(db)
        self.assertEqual(db.calls, 1)

    def test_an_expired_cache_refetches(self):
        db = FakeDB([outcome("a")])
        bandit._outcomes(db)
        bandit._cache["t"] = 0
        bandit._outcomes(db)
        self.assertEqual(db.calls, 2)


# ── choose ───────────────────────────────────────────────────────────────────

class TestChooseColdStart(BanditTestCase):
    def test_no_data_falls_back_to_the_heuristic_router(self):
        with patch.object(model_router, "route", return_value={"model": "heuristic-pick"}) as route:
            picked = bandit.choose(FakeDB([]), "build", "some prompt")
        self.assertEqual(picked, "heuristic-pick")
        route.assert_called_once()

    def test_seven_rows_is_still_a_cold_start(self):
        rows = [outcome("m1") for _ in range(7)]
        with patch.object(model_router, "route", return_value={"model": "heuristic-pick"}):
            self.assertEqual(bandit.choose(FakeDB(rows), "build", "p"), "heuristic-pick")

    def test_rows_for_another_task_class_do_not_warm_this_one(self):
        rows = [outcome("m1", kind="legal") for _ in range(50)]
        with patch.object(model_router, "route", return_value={"model": "heuristic-pick"}):
            self.assertEqual(bandit.choose(FakeDB(rows), "build", "p"), "heuristic-pick")

    def test_rows_with_no_kind_default_to_build(self):
        rows = [{"model": "m1", "usd": 0.1, "tests_passed": True, "integrated": True}
                for _ in range(20)]
        with patch.object(bandit.random, "random", return_value=1.0):
            picked = bandit.choose(FakeDB(rows), "build", "p", candidates=["m1", "m2"])
        # Warm, so it must NOT have gone to the heuristic router.
        self.assertIn(picked, ("m1", "m2"))


class TestChooseExploration(BanditTestCase):
    def test_the_epsilon_branch_picks_uniformly_at_random(self):
        rows = [outcome("m1") for _ in range(20)]
        with patch.object(bandit.random, "random", return_value=0.0), \
             patch.object(bandit.random, "choice", return_value="explored") as choice:
            picked = bandit.choose(FakeDB(rows), "build", "p", candidates=["m1", "m2"])
        self.assertEqual(picked, "explored")
        choice.assert_called_once_with(["m1", "m2"])

    def test_above_epsilon_it_exploits_instead(self):
        rows = [outcome("m1") for _ in range(20)]
        with patch.object(bandit.random, "random", return_value=1.0), \
             patch.object(bandit.random, "choice") as choice:
            bandit.choose(FakeDB(rows), "build", "p", candidates=["m1"])
        choice.assert_not_called()


class TestChooseExploitation(BanditTestCase):
    def test_an_untried_candidate_is_tried(self):
        rows = [outcome("m1") for _ in range(20)]
        with patch.object(bandit.random, "random", return_value=1.0):
            picked = bandit.choose(FakeDB(rows), "build", "p", candidates=["m1", "never_tried"])
        self.assertEqual(picked, "never_tried")

    def test_with_equal_sample_counts_the_better_model_wins(self):
        rows = ([outcome("good", usd=0.01) for _ in range(20)]
                + [outcome("bad", usd=0.01, tests_passed=False) for _ in range(20)])
        with patch.object(bandit.random, "random", return_value=1.0):
            picked = bandit.choose(FakeDB(rows), "build", "p", candidates=["good", "bad"])
        self.assertEqual(picked, "good")

    def test_a_cheap_winner_beats_an_expensive_one_at_equal_success(self):
        rows = ([outcome("cheap", usd=0.01) for _ in range(20)]
                + [outcome("pricey", usd=5.00) for _ in range(20)])
        with patch.object(bandit.random, "random", return_value=1.0):
            picked = bandit.choose(FakeDB(rows), "build", "p", candidates=["cheap", "pricey"])
        self.assertEqual(picked, "cheap")

    def test_models_outside_the_candidate_list_are_ignored(self):
        rows = ([outcome("stranger", usd=0.01) for _ in range(30)]
                + [outcome("m1", usd=1.00) for _ in range(10)])
        with patch.object(bandit.random, "random", return_value=1.0):
            picked = bandit.choose(FakeDB(rows), "build", "p", candidates=["m1"])
        self.assertEqual(picked, "m1")

    def test_ucb_explores_a_thinly_sampled_arm(self):
        """UCB1's whole point: a barely-sampled arm gets a confidence bonus, so
        a bandit that always returned the current leader would be wrong."""
        rows = ([outcome("leader", usd=0.5) for _ in range(200)]
                + [outcome("thin", usd=0.5) for _ in range(1)])
        with patch.object(bandit.random, "random", return_value=1.0):
            picked = bandit.choose(FakeDB(rows), "build", "p", candidates=["leader", "thin"])
        self.assertEqual(picked, "thin")

    def test_it_always_returns_something_choosable(self):
        rows = [outcome("m1") for _ in range(20)]
        with patch.object(bandit.random, "random", return_value=1.0):
            picked = bandit.choose(FakeDB(rows), "build", "p", candidates=["m1", "m2", "m3"])
        self.assertIn(picked, ("m1", "m2", "m3"))

    def test_default_candidates_are_the_three_configured_models(self):
        self.assertEqual(bandit.MODELS,
                         [model_router.HAIKU, model_router.SONNET, model_router.OPUS])


class TestEpsilonConfig(BanditTestCase):
    def test_epsilon_is_a_probability(self):
        self.assertGreaterEqual(bandit.EPSILON, 0.0)
        self.assertLessEqual(bandit.EPSILON, 1.0)


if __name__ == "__main__":
    unittest.main()
