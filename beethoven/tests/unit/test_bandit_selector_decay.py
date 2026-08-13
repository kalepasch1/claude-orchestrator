#!/usr/bin/env python3
"""BanditSelector exponential decay (slice 4: add-decay-formula).

Acceptance from the task, verbatim: BanditSelector(2, 0.1, alpha=0.2), update arm 0 with
rewards [0.5, 0.7, 0.9], and the tracked average follows
``new_avg = alpha * reward + (1 - alpha) * old_avg`` —
first 0.5, then 0.2*0.7 + 0.8*0.5 = 0.54, then 0.2*0.9 + 0.8*0.54 = 0.612.

The rest guards the two things decay can quietly break: the default estimator (every
existing caller still gets a simple average) and fail-soft coercion of alpha.
"""
import os
import sys
import unittest

_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from beethoven.bandit_selector import (  # noqa: E402
    ORCH_BANDIT_DEFAULT_ALPHA, BanditSelector,
)


class AcceptanceTest(unittest.TestCase):
    def test_the_literal_acceptance_sequence(self):
        selector = BanditSelector(2, 0.1, alpha=0.2)
        selector.update(0, 0.5)
        self.assertAlmostEqual(selector.average(0), 0.5)
        selector.update(0, 0.7)
        self.assertAlmostEqual(selector.average(0), 0.2 * 0.7 + 0.8 * 0.5)  # 0.54
        selector.update(0, 0.9)
        self.assertAlmostEqual(selector.average(0), 0.2 * 0.9 + 0.8 * 0.54)  # 0.612

    def test_alpha_is_accepted_in_init_and_exposed(self):
        self.assertAlmostEqual(BanditSelector(2, 0.1, alpha=0.2).alpha, 0.2)


class DecayFormulaTest(unittest.TestCase):
    def test_the_first_observation_seeds_the_average_outright(self):
        """Blending against an unmeasured 0.0 would drag every arm's first reading down."""
        selector = BanditSelector(3, 0.0, alpha=0.5)
        selector.update(2, 10.0)
        self.assertAlmostEqual(selector.average(2), 10.0)

    def test_alpha_one_forgets_everything_but_the_latest_reward(self):
        selector = BanditSelector(2, 0.0, alpha=1.0)
        for reward in (1.0, 2.0, 3.0):
            selector.update(0, reward)
        self.assertAlmostEqual(selector.average(0), 3.0)

    def test_a_small_alpha_barely_moves_off_the_seed(self):
        selector = BanditSelector(2, 0.0, alpha=0.01)
        selector.update(0, 1.0)
        selector.update(0, 0.0)
        self.assertAlmostEqual(selector.average(0), 0.99)

    def test_decay_tracks_a_drifting_arm_where_a_simple_average_lags(self):
        """The reason decay exists: an arm that goes bad must stop looking good."""
        decayed = BanditSelector(2, 0.0, alpha=0.5)
        plain = BanditSelector(2, 0.0)
        for _ in range(20):
            decayed.update(0, 1.0)
            plain.update(0, 1.0)
        for _ in range(3):
            decayed.update(0, 0.0)
            plain.update(0, 0.0)
        self.assertLess(decayed.average(0), 0.2)
        self.assertGreater(plain.average(0), 0.8)

    def test_arms_decay_independently(self):
        selector = BanditSelector(2, 0.0, alpha=0.5)
        selector.update(0, 1.0)
        selector.update(1, 0.0)
        selector.update(0, 1.0)
        self.assertAlmostEqual(selector.average(0), 1.0)
        self.assertAlmostEqual(selector.average(1), 0.0)

    def test_raw_counts_and_sums_stay_undecayed(self):
        """Later slices (UCB1) need true pull counts, so only the average decays."""
        selector = BanditSelector(2, 0.0, alpha=0.2)
        for reward in (0.5, 0.7, 0.9):
            selector.update(0, reward)
        self.assertEqual(selector.counts[0], 3)
        self.assertAlmostEqual(selector.sums[0], 2.1)


class SelectionUsesTheDecayedValueTest(unittest.TestCase):
    def test_the_greedy_branch_follows_the_decayed_average(self):
        selector = BanditSelector(2, 0.0, alpha=0.9, seed=1)
        for _ in range(10):
            selector.update(0, 1.0)   # arm 0 was great for a long time
        selector.update(1, 0.5)
        for _ in range(3):
            selector.update(0, 0.0)   # then it collapsed
        self.assertEqual(selector.best_arm(), 1)
        self.assertEqual(selector.select(), 1)

    def test_stats_reports_alpha_and_the_decayed_averages(self):
        selector = BanditSelector(2, 0.1, alpha=0.2)
        for reward in (0.5, 0.7, 0.9):
            selector.update(0, reward)
        stats = selector.stats()
        self.assertAlmostEqual(stats["alpha"], 0.2)
        self.assertAlmostEqual(stats["averages"][0], 0.612)
        self.assertAlmostEqual(stats["sums"][0], 2.1)
        self.assertEqual(stats["total_pulls"], 3)

    def test_reset_clears_the_decayed_state_too(self):
        selector = BanditSelector(2, 0.0, alpha=0.5)
        selector.update(0, 5.0)
        selector.reset()
        self.assertEqual(selector.average(0), 0.0)
        selector.update(0, 1.0)
        self.assertAlmostEqual(selector.average(0), 1.0)


class DefaultsAndCoercionTest(unittest.TestCase):
    def test_omitting_alpha_keeps_the_simple_average(self):
        selector = BanditSelector(2, 0.1)
        self.assertIsNone(selector.alpha)
        for reward in (0.5, 0.7, 0.9):
            selector.update(0, reward)
        self.assertAlmostEqual(selector.average(0), 2.1 / 3)

    def test_the_recommended_alpha_is_available_but_not_imposed(self):
        self.assertGreater(ORCH_BANDIT_DEFAULT_ALPHA, 0.0)
        self.assertLessEqual(ORCH_BANDIT_DEFAULT_ALPHA, 1.0)
        self.assertIsNone(BanditSelector(2, 0.1).alpha)
        self.assertAlmostEqual(
            BanditSelector(2, 0.1, alpha=ORCH_BANDIT_DEFAULT_ALPHA).alpha,
            ORCH_BANDIT_DEFAULT_ALPHA)

    def test_alpha_above_one_is_clamped(self):
        self.assertAlmostEqual(BanditSelector(2, 0.1, alpha=5.0).alpha, 1.0)

    def test_zero_and_negative_alpha_disable_decay_rather_than_freezing_the_average(self):
        for bad in (0.0, -0.5):
            with self.subTest(alpha=bad):
                self.assertIsNone(BanditSelector(2, 0.1, alpha=bad).alpha)

    def test_garbage_alpha_disables_decay_without_raising(self):
        for bad in ("abc", [], {}, float("nan")):
            with self.subTest(alpha=bad):
                self.assertIsNone(BanditSelector(2, 0.1, alpha=bad).alpha)

    def test_a_numeric_string_alpha_is_accepted(self):
        self.assertAlmostEqual(BanditSelector(2, 0.1, alpha="0.25").alpha, 0.25)

    def test_seed_remains_the_third_positional_argument(self):
        """Existing positional callers must not be re-bound by the new parameter."""
        a = BanditSelector(4, 1.0, 7)
        b = BanditSelector(4, 1.0, 7)
        self.assertIsNone(a.alpha)
        self.assertEqual([a.select() for _ in range(10)],
                         [b.select() for _ in range(10)])


if __name__ == "__main__":
    unittest.main()
