#!/usr/bin/env python3
"""Tests for bandit.PerformanceTracker and the acceptance gate in choose().

Two questions are kept separate throughout, because conflating them is the failure the
acceptance gate exists to prevent: "which arm has the higher mean" (tracking accuracy)
and "is that difference established" (acceptance logic).
"""
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import bandit


class TrackingAccuracyTest(unittest.TestCase):
    def setUp(self):
        self.t = bandit.PerformanceTracker()

    def test_counts_and_totals(self):
        self.t.extend("haiku", [1.0, 2.0, 3.0])
        self.assertEqual(self.t.n("haiku"), 3)
        self.assertAlmostEqual(self.t.total("haiku"), 6.0)

    def test_mean(self):
        self.t.extend("haiku", [1.0, 2.0, 3.0, 4.0])
        self.assertAlmostEqual(self.t.mean("haiku"), 2.5)

    def test_mean_of_an_unobserved_arm_is_none_not_zero(self):
        # Zero would be a claim about performance; None says "never ran".
        self.assertIsNone(self.t.mean("never-ran"))
        self.assertEqual(self.t.n("never-ran"), 0)

    def test_sample_variance_and_stddev(self):
        self.t.extend("haiku", [2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0])
        # Sample (n-1) variance of this classic set is 32/7.
        self.assertAlmostEqual(self.t.variance("haiku"), 32.0 / 7.0)
        self.assertAlmostEqual(self.t.stddev("haiku"), math.sqrt(32.0 / 7.0))

    def test_variance_is_none_below_two_samples(self):
        self.t.record("haiku", 1.0)
        self.assertIsNone(self.t.variance("haiku"))
        self.assertIsNone(self.t.stddev("haiku"))
        self.assertIsNone(self.t.stderr("haiku"))
        self.assertIsNone(self.t.confidence_interval("haiku"))

    def test_stderr_shrinks_as_samples_grow(self):
        self.t.extend("a", [1.0, 3.0] * 5)
        few = self.t.stderr("a")
        self.t.extend("a", [1.0, 3.0] * 45)
        self.assertLess(self.t.stderr("a"), few)

    def test_confidence_interval_brackets_the_mean(self):
        self.t.extend("haiku", [1.0, 2.0, 3.0, 4.0, 5.0])
        lo, hi = self.t.confidence_interval("haiku")
        self.assertLess(lo, self.t.mean("haiku"))
        self.assertGreater(hi, self.t.mean("haiku"))

    def test_confidence_interval_matches_the_normal_approximation(self):
        self.t.extend("haiku", [1.0, 2.0, 3.0, 4.0, 5.0])
        lo, hi = self.t.confidence_interval("haiku", confidence=0.95)
        expected_half = 1.96 * self.t.stderr("haiku")
        self.assertAlmostEqual(hi - lo, 2 * expected_half, places=6)

    def test_higher_confidence_widens_the_interval(self):
        self.t.extend("haiku", [1.0, 2.0, 3.0, 4.0, 5.0])
        narrow = self.t.confidence_interval("haiku", confidence=0.80)
        wide = self.t.confidence_interval("haiku", confidence=0.99)
        self.assertGreater(narrow[0], wide[0], "99% must reach lower")
        self.assertLess(narrow[1], wide[1], "99% must reach higher")
        self.assertLess(narrow[1] - narrow[0], wide[1] - wide[0])

    def test_zero_variance_gives_a_degenerate_interval_not_an_invented_width(self):
        self.t.extend("haiku", [2.0] * 10)
        lo, hi = self.t.confidence_interval("haiku")
        self.assertAlmostEqual(lo, 2.0)
        self.assertAlmostEqual(hi, 2.0)

    def test_non_numeric_rewards_are_ignored_not_raised_on(self):
        for bad in (None, "x", [], {}, object()):
            self.assertFalse(self.t.record("haiku", bad))
        self.assertEqual(self.t.n("haiku"), 0)

    def test_nan_and_inf_are_rejected(self):
        for bad in (float("nan"), float("inf"), float("-inf")):
            self.assertFalse(self.t.record("haiku", bad))
        self.assertEqual(self.t.n("haiku"), 0)

    def test_numeric_strings_are_accepted(self):
        self.assertTrue(self.t.record("haiku", "2.5"))
        self.assertAlmostEqual(self.t.mean("haiku"), 2.5)

    def test_extend_reports_how_many_were_accepted(self):
        self.assertEqual(self.t.extend("haiku", [1.0, "nope", 2.0, None]), 2)
        self.assertEqual(self.t.extend("haiku", None), 0)

    def test_max_samples_keeps_the_most_recent(self):
        t = bandit.PerformanceTracker(max_samples=5)
        t.extend("haiku", [0.0] * 5)
        t.extend("haiku", [10.0] * 5)
        self.assertEqual(t.n("haiku"), 5)
        self.assertAlmostEqual(t.mean("haiku"), 10.0)

    def test_rewards_accessor_returns_a_copy(self):
        self.t.extend("haiku", [1.0, 2.0])
        got = self.t.rewards("haiku")
        got.append(999.0)
        self.assertEqual(self.t.n("haiku"), 2)

    def test_reset_one_arm_and_all_arms(self):
        self.t.extend("a", [1.0]); self.t.extend("b", [2.0])
        self.t.reset("a")
        self.assertEqual(self.t.n("a"), 0)
        self.assertEqual(self.t.n("b"), 1)
        self.t.reset()
        self.assertEqual(self.t.n("b"), 0)

    def test_arms_are_ordered_best_mean_first(self):
        self.t.extend("low", [1.0, 1.0]); self.t.extend("high", [9.0, 9.0])
        self.assertEqual(self.t.arms()[0], "high")

    def test_best_picks_the_highest_mean_and_none_when_empty(self):
        self.assertIsNone(self.t.best())
        self.t.extend("low", [1.0]); self.t.extend("high", [5.0])
        self.assertEqual(self.t.best(), "high")
        self.assertEqual(self.t.best(candidates=["low"]), "low")

    def test_summary_reports_every_arm(self):
        self.t.extend("a", [1.0, 2.0, 3.0])
        self.t.record("b", 1.0)
        s = self.t.summary()
        self.assertEqual(set(s), {"a", "b"})
        self.assertEqual(s["a"]["n"], 3)
        self.assertIsNotNone(s["a"]["ci_low"])
        self.assertIsNone(s["b"]["ci"], "one sample cannot yield an interval")


class AcceptanceLogicTest(unittest.TestCase):
    def setUp(self):
        self.t = bandit.PerformanceTracker()

    def _load(self, arm, value, n, spread=0.0):
        # Alternating +/- spread keeps the mean exactly `value` with controllable variance.
        self.t.extend(arm, [value + (spread if i % 2 else -spread) for i in range(n)])

    def test_accepts_a_clearly_and_amply_better_arm(self):
        self._load("winner", 9.0, 40, spread=0.1)
        self._load("loser", 1.0, 40, spread=0.1)
        v = self.t.acceptance("winner", "loser", min_samples=12)
        self.assertTrue(v["accepted"])
        self.assertIn("exceeds baseline ci high", v["reason"])

    def test_refuses_on_thin_data_even_when_the_mean_is_much_higher(self):
        # The exact trap: a big apparent lead on three samples.
        self._load("winner", 9.0, 3, spread=0.1)
        self._load("loser", 1.0, 3, spread=0.1)
        v = self.t.acceptance("winner", "loser", min_samples=12)
        self.assertFalse(v["accepted"])
        self.assertIn("insufficient samples", v["reason"])
        self.assertGreater(v["mean"], v["baseline_mean"], "the mean IS higher; that is not enough")

    def test_refuses_when_the_intervals_overlap(self):
        self._load("a", 5.0, 40, spread=4.0)
        self._load("b", 4.8, 40, spread=4.0)
        v = self.t.acceptance("a", "b", min_samples=12)
        self.assertFalse(v["accepted"])
        self.assertIn("intervals overlap", v["reason"])

    def test_refuses_a_worse_arm(self):
        self._load("worse", 1.0, 40, spread=0.1)
        self._load("better", 9.0, 40, spread=0.1)
        self.assertFalse(self.t.accepts("worse", "better", min_samples=12))

    def test_an_arm_is_never_accepted_over_itself(self):
        self._load("a", 9.0, 40, spread=0.1)
        v = self.t.acceptance("a", "a", min_samples=12)
        self.assertFalse(v["accepted"])
        self.assertIn("same arm", v["reason"])

    def test_unobserved_baseline_is_refused_not_crashed(self):
        self._load("a", 9.0, 40, spread=0.1)
        v = self.t.acceptance("a", "never-ran", min_samples=12)
        self.assertFalse(v["accepted"])
        self.assertEqual(v["baseline_n"], 0)

    def test_verdict_carries_the_evidence(self):
        self._load("a", 9.0, 40, spread=0.1)
        self._load("b", 1.0, 40, spread=0.1)
        v = self.t.acceptance("a", "b", min_samples=12)
        for key in ("arm", "baseline", "n", "baseline_n", "mean", "baseline_mean",
                    "ci", "baseline_ci", "accepted", "reason"):
            self.assertIn(key, v)

    def test_min_samples_floor_is_honored(self):
        self._load("a", 9.0, 5, spread=0.1)
        self._load("b", 1.0, 5, spread=0.1)
        self.assertFalse(self.t.accepts("a", "b", min_samples=12))
        self.assertTrue(self.t.accepts("a", "b", min_samples=4))

    def test_stricter_confidence_makes_acceptance_harder(self):
        self._load("a", 5.0, 30, spread=2.0)
        self._load("b", 3.6, 30, spread=2.0)
        loose = self.t.accepts("a", "b", min_samples=12, confidence=0.80)
        strict = self.t.accepts("a", "b", min_samples=12, confidence=0.99)
        self.assertTrue(loose)
        self.assertFalse(strict)

    def test_accepted_leader_requires_beating_every_rival(self):
        self._load("best", 9.0, 40, spread=0.1)
        self._load("mid", 5.0, 40, spread=0.1)
        self._load("worst", 1.0, 40, spread=0.1)
        self.assertEqual(self.t.accepted_leader(min_samples=12), "best")

    def test_accepted_leader_is_none_while_any_rival_is_within_reach(self):
        self._load("a", 5.0, 40, spread=4.0)
        self._load("b", 4.9, 40, spread=4.0)
        self.assertIsNone(self.t.accepted_leader(min_samples=12))

    def test_accepted_leader_is_none_with_fewer_than_two_arms(self):
        self._load("only", 9.0, 40, spread=0.1)
        self.assertIsNone(self.t.accepted_leader(min_samples=12))
        self.assertIsNone(bandit.PerformanceTracker().accepted_leader())

    def test_accepted_leader_respects_the_candidate_pool(self):
        self._load("best", 9.0, 40, spread=0.1)
        self._load("mid", 5.0, 40, spread=0.1)
        self._load("worst", 1.0, 40, spread=0.1)
        self.assertEqual(self.t.accepted_leader(["mid", "worst"], min_samples=12), "mid")


class ZTableTest(unittest.TestCase):
    def test_known_levels(self):
        self.assertAlmostEqual(bandit._z_for(0.95), 1.96, places=2)
        self.assertAlmostEqual(bandit._z_for(0.99), 2.576, places=2)

    def test_garbage_falls_back_to_95_percent(self):
        for bad in (None, "x", -1, 0, 1, 42, [], {}):
            self.assertAlmostEqual(bandit._z_for(bad), 1.96, places=2)


class FakeDB:
    def __init__(self, rows):
        self.rows = rows

    def select(self, table, params):
        return list(self.rows)


def _row(model, kind="build", passed=True, integrated=True, usd=0.01):
    return {"model": model, "kind": kind, "tests_passed": passed,
            "integrated": integrated, "usd": usd}


class ChooseIntegrationTest(unittest.TestCase):
    """The gate must be wired in, and must not disturb the paths it does not own."""

    def setUp(self):
        bandit._cache.update(t=0, rows=[])
        # EPSILON is read at import time, so the env var alone would not take effect —
        # set the module attribute and restore it afterwards.
        self._epsilon = bandit.EPSILON
        self._env = {k: os.environ.get(k) for k in
                     ("BANDIT_ACCEPTANCE", "BANDIT_EPSILON", "BANDIT_ACCEPT_MIN_SAMPLES")}

    def tearDown(self):
        bandit._cache.update(t=0, rows=[])
        bandit.EPSILON = self._epsilon
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_cold_start_still_defers_to_the_heuristic_router(self):
        # Backward compatibility: under 8 rows nothing about this path changed.
        db = FakeDB([_row("m1") for _ in range(3)])
        import model_router
        self.assertEqual(bandit.choose(db, "build", "add a small helper"),
                         model_router.route("add a small helper")["model"])

    def test_tracker_from_outcomes_filters_by_task_class(self):
        db = FakeDB([_row("m1", kind="build"), _row("m2", kind="bugfix")])
        t = bandit.tracker_from_outcomes(db, "build")
        self.assertEqual(t.n("m1"), 1)
        self.assertEqual(t.n("m2"), 0)

    def test_tracker_from_outcomes_filters_by_candidate_pool(self):
        db = FakeDB([_row("m1"), _row("m2")])
        t = bandit.tracker_from_outcomes(db, "build", candidates=["m1"])
        self.assertEqual(t.n("m1"), 1)
        self.assertEqual(t.n("m2"), 0)

    def test_tracker_from_outcomes_treats_a_missing_kind_as_build(self):
        db = FakeDB([{"model": "m1", "tests_passed": True, "integrated": True, "usd": 0.01}])
        self.assertEqual(bandit.tracker_from_outcomes(db, "build").n("m1"), 1)

    def test_accepted_arm_is_chosen_and_exploration_is_skipped(self):
        # Epsilon forced to 1.0: without the gate, choose() would explore at random every
        # time. A deterministic result over many calls proves the gate short-circuits it.
        bandit.EPSILON = 1.0
        arms = ["cheap-winner", "pricey-loser"]
        rows = ([_row("cheap-winner", usd=0.01) for _ in range(30)] +
                [_row("pricey-loser", usd=5.00) for _ in range(30)])
        db = FakeDB(rows)
        picks = {bandit.choose(db, "build", "anything", candidates=arms) for _ in range(25)}
        self.assertEqual(picks, {"cheap-winner"})

    def test_the_kill_switch_restores_the_old_behavior(self):
        arms = ["cheap-winner", "pricey-loser"]
        rows = ([_row("cheap-winner", usd=0.01) for _ in range(30)] +
                [_row("pricey-loser", usd=5.00) for _ in range(30)])
        db = FakeDB(rows)

        import importlib
        os.environ["BANDIT_ACCEPTANCE"] = "false"
        importlib.reload(bandit)
        try:
            bandit.EPSILON = 1.0
            bandit._cache.update(t=0, rows=[])
            picks = {bandit.choose(db, "build", "anything", candidates=arms)
                     for _ in range(60)}
            # Pure exploration again: both arms show up, so the gate really was what
            # produced the deterministic answer above.
            self.assertEqual(picks, set(arms))
        finally:
            os.environ["BANDIT_ACCEPTANCE"] = "true"
            importlib.reload(bandit)
            bandit._cache.update(t=0, rows=[])

    def test_ambiguous_data_falls_through_to_ucb1_and_still_returns_a_candidate(self):
        bandit.EPSILON = 0.0                          # no exploration; UCB1 only
        rows = ([_row("a", usd=0.50) for _ in range(10)] +
                [_row("b", usd=0.52) for _ in range(10)])
        db = FakeDB(rows)
        pick = bandit.choose(db, "build", "anything", candidates=["a", "b"])
        self.assertIn(pick, ("a", "b"))

    def test_an_untried_candidate_is_still_tried(self):
        bandit.EPSILON = 0.0
        rows = [_row("known") for _ in range(20)]
        db = FakeDB(rows)
        self.assertEqual(bandit.choose(db, "build", "anything",
                                       candidates=["known", "untried"]), "untried")


class BackwardCompatibilityTest(unittest.TestCase):
    def test_public_surface_is_preserved(self):
        for name in ("MODELS", "EPSILON", "choose", "_reward", "_outcomes"):
            self.assertTrue(hasattr(bandit, name), name)

    def test_reward_formula_is_unchanged(self):
        self.assertAlmostEqual(bandit._reward(_row("m", usd=0.99)), 1.0)
        self.assertAlmostEqual(bandit._reward(_row("m", integrated=False, usd=0.19)), 1.0)
        self.assertAlmostEqual(bandit._reward(_row("m", passed=False, usd=1.0)), 0.0)

    def test_choose_signature_still_accepts_the_original_three_arguments(self):
        db = FakeDB([_row("m1") for _ in range(3)])
        self.assertIsInstance(bandit.choose(db, "build", "prompt"), str)


if __name__ == "__main__":
    unittest.main()
