#!/usr/bin/env python3
"""BanditSelector's epsilon-greedy POLICY had no tests.

`runner/tests/test_bandit_selector.py` has 13 cases and every one of them tests the
constructor: arm validation, dedupe, epsilon/decay range, repr, instance isolation.
Nothing exercised `select`, `update_reward`, `best_arm`, `current_epsilon` or
`stats` — the algorithm itself. The class docstring meanwhile still said "this slice
is initialization only, the selection algorithm lands in a later slice", so the
untested half also looked unwritten, and slice 5 of this task was queued asking for
methods that already existed.

These pin the policy. Selection is made deterministic with an injected `rng` rather
than by seeding the global `random` module, which is what the `rng` parameter is for.

Run: python3 -m unittest runner.tests.test_bandit_selector_policy -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("ORCH_DB_URL", "")
os.environ.setdefault("ORCH_DB_ENABLED", "false")

from bandit import BanditSelector

ARMS = ["a", "b", "c"]


class _RNG:
    """Deterministic stand-in for `random`. `values` feeds random(); choice() is first."""

    def __init__(self, values=(), choice_index=0):
        self.values = list(values)
        self.choice_index = choice_index
        self.choice_calls = 0

    def random(self):
        return self.values.pop(0) if self.values else 1.0

    def choice(self, seq):
        self.choice_calls += 1
        return list(seq)[self.choice_index]


def _drain(selector, reward=0.0):
    """Pull every untried arm once so the policy is past its cold start."""
    for arm in selector.arm_ids:
        selector.update_reward(arm, reward)


class ColdStartTest(unittest.TestCase):
    """Untried arms are taken first — the classic epsilon-greedy failure if not."""

    def test_first_selection_is_the_first_untried_arm(self):
        b = BanditSelector(ARMS)
        self.assertEqual(b.select(rng=_RNG()), "a")

    def test_every_arm_is_tried_before_any_is_exploited(self):
        b = BanditSelector(ARMS)
        picked = []
        for _ in ARMS:
            arm = b.select(rng=_RNG())
            picked.append(arm)
            b.update_reward(arm, 0.0)
        self.assertEqual(sorted(picked), sorted(ARMS))

    def test_cold_start_ignores_epsilon_entirely(self):
        # rng that would always explore; untried arms must still win.
        b = BanditSelector(ARMS, epsilon=1.0, decay=0.0)
        rng = _RNG(values=[0.0])
        self.assertEqual(b.select(rng=rng), "a")
        self.assertEqual(rng.choice_calls, 0)

    def test_a_high_reward_arm_does_not_starve_the_untried_ones(self):
        b = BanditSelector(ARMS, epsilon=0.0, decay=0.0)
        b.update_reward("a", 100.0)
        self.assertEqual(b.select(rng=_RNG()), "b")


class ExploitTest(unittest.TestCase):
    def test_exploits_the_best_arm_when_not_exploring(self):
        b = BanditSelector(ARMS, epsilon=0.0, decay=0.0)
        _drain(b)
        b.update_reward("b", 5.0)
        self.assertEqual(b.select(rng=_RNG(values=[0.99])), "b")

    def test_best_arm_is_the_highest_mean_not_the_highest_total(self):
        b = BanditSelector(ARMS, epsilon=0.0, decay=0.0)
        _drain(b)
        for _ in range(10):
            b.update_reward("a", 1.0)          # mean 1.0 over many pulls
        b.update_reward("b", 5.0)              # mean 2.5 over few
        self.assertEqual(b.best_arm(), "b")

    def test_ties_break_on_declared_arm_order(self):
        b = BanditSelector(ARMS)
        _drain(b, reward=1.0)
        self.assertEqual(b.best_arm(), "a")
        self.assertEqual(b.best_arm(), "a")    # reproducible, not dict-order dependent


class ExploreTest(unittest.TestCase):
    def test_explores_when_the_draw_is_below_epsilon(self):
        b = BanditSelector(ARMS, epsilon=1.0, decay=0.0)
        _drain(b)
        rng = _RNG(values=[0.0], choice_index=2)
        self.assertEqual(b.select(rng=rng), "c")
        self.assertEqual(rng.choice_calls, 1)

    def test_zero_epsilon_never_explores(self):
        b = BanditSelector(ARMS, epsilon=0.0, decay=0.0)
        _drain(b)
        b.update_reward("a", 9.0)
        rng = _RNG(values=[0.0])
        self.assertEqual(b.select(rng=rng), "a")
        self.assertEqual(rng.choice_calls, 0)

    def test_selection_without_an_rng_still_returns_a_known_arm(self):
        b = BanditSelector(ARMS)
        _drain(b)
        self.assertIn(b.select(), ARMS)


class EpsilonDecayTest(unittest.TestCase):
    def test_epsilon_decays_with_steps(self):
        b = BanditSelector(ARMS, epsilon=0.5, decay=0.5)
        first = b.current_epsilon()
        b.update_reward("a", 1.0)
        self.assertLess(b.current_epsilon(), first)

    def test_zero_decay_holds_epsilon_constant(self):
        b = BanditSelector(ARMS, epsilon=0.3, decay=0.0)
        _drain(b)
        self.assertAlmostEqual(b.current_epsilon(), 0.3)

    def test_epsilon_never_goes_negative(self):
        b = BanditSelector(ARMS, epsilon=1.0, decay=1.0)
        for _ in range(5):
            b.update_reward("a", 1.0)
        self.assertGreaterEqual(b.current_epsilon(), 0.0)

    def test_epsilon_stays_within_bounds(self):
        b = BanditSelector(ARMS, epsilon=1.0, decay=0.1)
        for _ in range(20):
            b.update_reward("a", 1.0)
            self.assertTrue(0.0 <= b.current_epsilon() <= 1.0)


class UpdateTest(unittest.TestCase):
    def test_incremental_mean_matches_the_arithmetic_mean(self):
        b = BanditSelector(ARMS)
        for r in (1.0, 2.0, 6.0):
            b.update_reward("a", r)
        self.assertAlmostEqual(b.average_reward["a"], 3.0)

    def test_counts_track_pulls_per_arm(self):
        b = BanditSelector(ARMS)
        b.update_reward("a", 1.0)
        b.update_reward("a", 1.0)
        b.update_reward("b", 1.0)
        self.assertEqual((b.counts["a"], b.counts["b"], b.counts["c"]), (2, 1, 0))

    def test_steps_count_every_update(self):
        b = BanditSelector(ARMS)
        _drain(b)
        self.assertEqual(b.steps, 3)

    def test_unknown_arm_is_refused_not_created(self):
        b = BanditSelector(ARMS)
        with self.assertRaises(KeyError):
            b.update_reward("typo", 1.0)
        self.assertEqual(set(b.counts), set(ARMS))

    def test_non_numeric_reward_is_refused(self):
        b = BanditSelector(ARMS)
        with self.assertRaises(TypeError):
            b.update_reward("a", "lots")

    def test_numeric_string_reward_is_accepted(self):
        b = BanditSelector(ARMS)
        b.update_reward("a", "2.0")
        self.assertAlmostEqual(b.average_reward["a"], 2.0)

    def test_negative_rewards_are_allowed(self):
        b = BanditSelector(ARMS, epsilon=0.0, decay=0.0)
        _drain(b)
        b.update_reward("a", -5.0)
        self.assertNotEqual(b.best_arm(), "a")


class StatsTest(unittest.TestCase):
    def test_stats_reports_every_field(self):
        b = BanditSelector(ARMS)
        _drain(b)
        snapshot = b.stats()
        for key in ("steps", "epsilon", "counts", "average_reward", "best_arm"):
            self.assertIn(key, snapshot)

    def test_stats_is_a_copy_not_a_live_view(self):
        b = BanditSelector(ARMS)
        snapshot = b.stats()
        snapshot["counts"]["a"] = 999
        self.assertEqual(b.counts["a"], 0)

    def test_len_is_the_arm_count(self):
        self.assertEqual(len(BanditSelector(ARMS)), 3)




class SpecAliasTest(unittest.TestCase):
    """The queued spec named `update` / `get_stats`; both must exist and delegate."""

    def test_update_alias_exists_and_delegates(self):
        b = BanditSelector(ARMS)
        b.update("a", 4.0)
        self.assertEqual(b.counts["a"], 1)
        self.assertAlmostEqual(b.average_reward["a"], 4.0)

    def test_get_stats_alias_matches_stats(self):
        b = BanditSelector(ARMS)
        _drain(b)
        self.assertEqual(b.get_stats(), b.stats())

    def test_update_alias_refuses_unknown_arms_too(self):
        with self.assertRaises(KeyError):
            BanditSelector(ARMS).update("typo", 1.0)

    def test_get_stats_is_also_a_copy(self):
        b = BanditSelector(ARMS)
        b.get_stats()["counts"]["a"] = 999
        self.assertEqual(b.counts["a"], 0)


class ConvergenceTest(unittest.TestCase):
    """End-to-end: the policy finds the genuinely better arm."""

    def test_the_better_arm_wins_after_enough_evidence(self):
        payoff = {"a": 0.1, "b": 0.9, "c": 0.2}
        b = BanditSelector(ARMS, epsilon=0.2, decay=0.05)
        rng = _RNG(values=[0.99] * 200)
        for _ in range(60):
            arm = b.select(rng=rng)
            b.update_reward(arm, payoff[arm])
        self.assertEqual(b.best_arm(), "b")

    def test_a_single_arm_selector_always_returns_it(self):
        b = BanditSelector(["only"], epsilon=1.0)
        self.assertEqual(b.select(rng=_RNG(values=[0.0])), "only")
        b.update_reward("only", 1.0)
        self.assertEqual(b.select(rng=_RNG(values=[0.0])), "only")


if __name__ == "__main__":
    unittest.main(verbosity=2)
