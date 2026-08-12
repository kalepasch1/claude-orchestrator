#!/usr/bin/env python3
"""Tests for beethoven/bandit_selector.py (slice 4: basic bandit).

Acceptance test from the task: instantiate BanditSelector(3, 0.1), call
select() 20 times and verify all returned values are in [0, 1, 2]; call
update() a few times and verify the tracking structure is populated.
"""
import os
import sys
import unittest

_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from beethoven.bandit_selector import BanditSelector  # noqa: E402


class AcceptanceTest(unittest.TestCase):
    """The literal acceptance criteria for this slice."""

    def test_twenty_selects_are_all_valid_arms(self):
        selector = BanditSelector(3, 0.1)
        picks = [selector.select() for _ in range(20)]
        self.assertEqual(len(picks), 20)
        for pick in picks:
            self.assertIn(pick, [0, 1, 2])

    def test_update_populates_tracking_structure(self):
        selector = BanditSelector(3, 0.1)
        selector.update(0, 1.0)
        selector.update(1, 0.5)
        selector.update(0, 0.0)
        self.assertEqual(selector.counts, [2, 1, 0])
        self.assertEqual(selector.sums, [1.0, 0.5, 0.0])
        self.assertAlmostEqual(selector.average(0), 0.5)
        self.assertAlmostEqual(selector.average(1), 0.5)
        self.assertEqual(selector.average(2), 0.0)


class ConstructionTest(unittest.TestCase):
    def test_fields_initialised(self):
        selector = BanditSelector(4, 0.25)
        self.assertEqual(selector.n_arms, 4)
        self.assertAlmostEqual(selector.epsilon, 0.25)
        self.assertEqual(selector.counts, [0, 0, 0, 0])
        self.assertEqual(selector.sums, [0.0, 0.0, 0.0, 0.0])

    def test_bad_n_arms_is_fail_soft(self):
        for bad in (0, -5, None, "x", 1.9):
            self.assertGreaterEqual(BanditSelector(bad, 0.1).n_arms, 1)

    def test_n_arms_is_clamped(self):
        selector = BanditSelector(10 ** 9, 0.1)
        self.assertLessEqual(selector.n_arms, 1024)

    def test_epsilon_is_clamped_to_unit_interval(self):
        self.assertEqual(BanditSelector(3, -1.0).epsilon, 0.0)
        self.assertEqual(BanditSelector(3, 5.0).epsilon, 1.0)

    def test_bad_epsilon_falls_back_to_default(self):
        self.assertAlmostEqual(BanditSelector(3, None).epsilon, 0.1)
        self.assertAlmostEqual(BanditSelector(3, "nope").epsilon, 0.1)
        self.assertAlmostEqual(BanditSelector(3, float("nan")).epsilon, 0.1)


class SelectTest(unittest.TestCase):
    def test_single_arm_always_returns_zero(self):
        selector = BanditSelector(1, 0.5)
        self.assertEqual({selector.select() for _ in range(10)}, {0})

    def test_pure_exploration_covers_all_arms(self):
        selector = BanditSelector(3, 1.0, seed=7)
        picks = {selector.select() for _ in range(200)}
        self.assertEqual(picks, {0, 1, 2})

    def test_untried_arms_are_tried_before_greedy_locks_on(self):
        selector = BanditSelector(3, 0.0, seed=7)
        selector.update(0, 100.0)
        picks = {selector.select() for _ in range(50)}
        # arm 0 has a huge average but 1 and 2 are untried, so they must appear.
        self.assertTrue({1, 2}.issubset(picks))

    def test_greedy_exploits_best_arm_once_all_tried(self):
        selector = BanditSelector(3, 0.0, seed=7)
        selector.update(0, 0.1)
        selector.update(1, 0.9)
        selector.update(2, 0.2)
        self.assertEqual({selector.select() for _ in range(30)}, {1})

    def test_selection_is_reproducible_with_a_seed(self):
        first = [BanditSelector(5, 0.5, seed=42).select() for _ in range(1)]
        a = BanditSelector(5, 0.5, seed=42)
        b = BanditSelector(5, 0.5, seed=42)
        self.assertEqual([a.select() for _ in range(20)], [b.select() for _ in range(20)])
        self.assertEqual(len(first), 1)

    def test_always_in_range_across_many_configurations(self):
        for n_arms in (1, 2, 3, 8):
            for epsilon in (0.0, 0.1, 0.5, 1.0):
                selector = BanditSelector(n_arms, epsilon, seed=1)
                for _ in range(50):
                    self.assertIn(selector.select(), range(n_arms))


class UpdateTest(unittest.TestCase):
    def test_average_uses_simple_sum_over_count(self):
        selector = BanditSelector(2, 0.1)
        for reward in (1.0, 2.0, 3.0):
            selector.update(0, reward)
        self.assertEqual(selector.counts[0], 3)
        self.assertAlmostEqual(selector.average(0), 2.0)

    def test_out_of_range_arm_is_ignored(self):
        selector = BanditSelector(2, 0.1)
        selector.update(5, 1.0)
        selector.update(-1, 1.0)
        self.assertEqual(selector.counts, [0, 0])

    def test_bad_arm_or_reward_is_ignored_not_raised(self):
        selector = BanditSelector(2, 0.1)
        for arm, reward in ((None, 1.0), ("x", 1.0), (0, None), (0, "x"), (0, float("nan"))):
            selector.update(arm, reward)
        self.assertEqual(selector.counts, [0, 0])

    def test_negative_rewards_are_accepted(self):
        selector = BanditSelector(2, 0.1)
        selector.update(0, -1.0)
        self.assertAlmostEqual(selector.average(0), -1.0)

    def test_integer_like_arm_is_accepted(self):
        selector = BanditSelector(2, 0.1)
        selector.update("1", 1.0)
        self.assertEqual(selector.counts[1], 1)


class ObservabilityTest(unittest.TestCase):
    def test_stats_reports_the_full_picture(self):
        selector = BanditSelector(3, 0.2)
        selector.update(0, 1.0)
        selector.update(2, 3.0)
        stats = selector.stats()
        self.assertEqual(stats["n_arms"], 3)
        self.assertAlmostEqual(stats["epsilon"], 0.2)
        self.assertEqual(stats["counts"], [1, 0, 1])
        self.assertEqual(stats["total_pulls"], 2)
        self.assertAlmostEqual(stats["averages"][2], 3.0)

    def test_best_arm(self):
        selector = BanditSelector(3, 0.1)
        self.assertEqual(selector.best_arm(), 0)
        selector.update(2, 5.0)
        self.assertEqual(selector.best_arm(), 2)

    def test_reset_clears_tracking(self):
        selector = BanditSelector(2, 0.1)
        selector.update(0, 1.0)
        selector.reset()
        self.assertEqual(selector.counts, [0, 0])
        self.assertEqual(selector.sums, [0.0, 0.0])

    def test_average_out_of_range_is_zero(self):
        selector = BanditSelector(2, 0.1)
        self.assertEqual(selector.average(99), 0.0)
        self.assertEqual(selector.average("x"), 0.0)


class ConvergenceTest(unittest.TestCase):
    def test_bandit_favours_the_high_reward_arm_over_time(self):
        selector = BanditSelector(3, 0.1, seed=11)
        payoffs = {0: 0.1, 1: 0.2, 2: 0.9}
        for _ in range(500):
            arm = selector.select()
            selector.update(arm, payoffs[arm])
        self.assertEqual(selector.best_arm(), 2)
        self.assertGreater(selector.counts[2], selector.counts[0])
        self.assertGreater(selector.counts[2], selector.counts[1])


if __name__ == "__main__":
    unittest.main()
