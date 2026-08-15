#!/usr/bin/env python3
"""`BanditSelector.update(arm_id, reward)` — the public name, pinned.

`update` is the API the queued spec named and the one callers write against; the
arithmetic lives in `update_reward`. Between them there were exactly two incidental
assertions in the whole suite (`test_bandit_selector_policy.py` lines 218 and 229), so
the learning method that decides which model the fleet routes to was effectively
unpinned: an alias could be dropped, the incremental mean could drift to a
sum/count formulation, or the step counter could stop advancing, and nothing would fail.

Two things get special attention here:

  * **Behaviour preservation vs a golden reference.** Each update is checked against a
    naive recompute-from-full-history mean. The incremental form (mean += (r-mean)/n)
    is only worth having if it agrees with the obvious implementation, so the obvious
    implementation is the oracle rather than hand-copied expected constants.
  * **decay=0 and decay=1 endpoints.** Both are legal per the constructor's [0,1]
    contract and they sit at opposite extremes of the exploration schedule — no decay
    at all, and collapse to pure exploitation after a single update. Each is a
    plausible off-by-one in `(1 - decay) ** steps`.

Run: python3 -m unittest runner.tests.test_bandit_selector_update -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bandit import BanditSelector  # noqa: E402

ARMS = ("a", "b", "c")


def golden_mean(rewards):
    """Naive reference: recompute the mean from the full history."""
    return sum(rewards) / len(rewards) if rewards else 0.0


class TestUpdateNormalCase(unittest.TestCase):
    def test_single_update_sets_mean_and_count(self):
        b = BanditSelector(ARMS)
        self.assertAlmostEqual(b.update("a", 1.0), 1.0)
        self.assertEqual(b.counts["a"], 1)
        self.assertAlmostEqual(b.average_reward["a"], 1.0)

    def test_returns_the_new_mean_for_that_arm(self):
        b = BanditSelector(ARMS)
        b.update("a", 0.0)
        self.assertAlmostEqual(b.update("a", 1.0), 0.5)

    def test_matches_the_golden_reference_over_a_long_run(self):
        # The whole point of the incremental form is that it agrees with the obvious one.
        b = BanditSelector(ARMS)
        history = []
        for i in range(200):
            reward = (i % 7) / 7.0
            history.append(reward)
            returned = b.update("a", reward)
            self.assertAlmostEqual(returned, golden_mean(history), places=9)
        self.assertEqual(b.counts["a"], 200)

    def test_arms_are_independent(self):
        b = BanditSelector(ARMS)
        b.update("a", 1.0)
        b.update("a", 1.0)
        b.update("b", 0.0)
        self.assertAlmostEqual(b.average_reward["a"], 1.0)
        self.assertAlmostEqual(b.average_reward["b"], 0.0)
        self.assertEqual(b.counts["c"], 0)

    def test_update_is_an_alias_not_a_second_implementation(self):
        # A copied implementation is how the two names drift apart silently.
        self.assertIs(BanditSelector(ARMS).update.__func__,
                      BanditSelector.update)
        by_alias = BanditSelector(ARMS)
        by_impl = BanditSelector(ARMS)
        for reward in (0.25, 0.75, 1.0):
            by_alias.update("a", reward)
            by_impl.update_reward("a", reward)
        self.assertEqual(by_alias.average_reward, by_impl.average_reward)
        self.assertEqual(by_alias.counts, by_impl.counts)

    def test_steps_advance_once_per_update(self):
        # `steps` drives epsilon decay; if it stops advancing the bandit explores forever.
        b = BanditSelector(ARMS)
        for expected in range(1, 6):
            b.update("a", 1.0)
            self.assertEqual(b.steps, expected)

    def test_best_arm_follows_the_evidence(self):
        b = BanditSelector(ARMS)
        b.update("a", 0.1)
        b.update("b", 0.9)
        b.update("c", 0.5)
        self.assertEqual(b.best_arm(), "b")


class TestUpdateDecayEndpoints(unittest.TestCase):
    def test_decay_zero_never_reduces_exploration(self):
        b = BanditSelector(ARMS, epsilon=0.5, decay=0.0)
        for _ in range(50):
            b.update("a", 1.0)
        self.assertAlmostEqual(b.current_epsilon(), 0.5)

    def test_decay_one_collapses_to_pure_exploitation_after_one_update(self):
        # (1-1)**1 == 0. A single update must take exploration to exactly zero.
        b = BanditSelector(ARMS, epsilon=1.0, decay=1.0)
        self.assertAlmostEqual(b.current_epsilon(), 1.0)
        b.update("a", 1.0)
        self.assertAlmostEqual(b.current_epsilon(), 0.0)

    def test_decay_never_pushes_epsilon_below_zero(self):
        b = BanditSelector(ARMS, epsilon=0.9, decay=0.5)
        for _ in range(200):
            b.update("a", 1.0)
        self.assertGreaterEqual(b.current_epsilon(), 0.0)

    def test_decay_does_not_touch_the_reward_mean(self):
        # Exploration schedule and reward accounting must stay independent.
        for decay in (0.0, 0.01, 0.5, 1.0):
            with self.subTest(decay=decay):
                b = BanditSelector(ARMS, epsilon=0.3, decay=decay)
                b.update("a", 1.0)
                b.update("a", 0.0)
                self.assertAlmostEqual(b.average_reward["a"], 0.5)


class TestUpdateRejectsBadInput(unittest.TestCase):
    def test_missing_arm_id_raises_keyerror(self):
        with self.assertRaises(KeyError):
            BanditSelector(ARMS).update("typo", 1.0)

    def test_missing_arm_does_not_register_itself(self):
        # A silently-created arm would dilute the real arms' statistics forever.
        b = BanditSelector(ARMS)
        with self.assertRaises(KeyError):
            b.update("ghost", 1.0)
        self.assertNotIn("ghost", b.counts)
        self.assertEqual(b.steps, 0)

    def test_non_numeric_reward_raises_typeerror(self):
        b = BanditSelector(ARMS)
        for bad in ("high", None, object(), [1.0], {}):
            with self.subTest(reward=bad):
                with self.assertRaises(TypeError):
                    b.update("a", bad)

    def test_rejected_reward_leaves_state_untouched(self):
        b = BanditSelector(ARMS)
        b.update("a", 1.0)
        before = (dict(b.counts), dict(b.average_reward), b.steps)
        with self.assertRaises(TypeError):
            b.update("a", "not-a-number")
        self.assertEqual((dict(b.counts), dict(b.average_reward), b.steps), before)

    def test_numeric_strings_and_bools_are_coerced_like_float(self):
        # float("0.5") and float(True) both succeed, so these are accepted by contract.
        b = BanditSelector(ARMS)
        self.assertAlmostEqual(b.update("a", "0.5"), 0.5)
        self.assertAlmostEqual(b.update("b", True), 1.0)

    def test_none_arm_id_is_refused(self):
        with self.assertRaises(KeyError):
            BanditSelector(ARMS).update(None, 1.0)


class TestUpdateBoundaryValues(unittest.TestCase):
    def test_zero_and_one_rewards(self):
        b = BanditSelector(ARMS)
        b.update("a", 0.0)
        b.update("a", 1.0)
        self.assertAlmostEqual(b.average_reward["a"], 0.5)

    def test_negative_rewards_are_accepted(self):
        # Nothing in the contract restricts reward to [0,1]; a penalty signal is valid.
        b = BanditSelector(ARMS)
        b.update("a", -1.0)
        self.assertAlmostEqual(b.average_reward["a"], -1.0)

    def test_very_large_and_very_small_magnitudes(self):
        b = BanditSelector(ARMS)
        b.update("a", 1e12)
        b.update("a", -1e12)
        self.assertAlmostEqual(b.average_reward["a"], 0.0, places=3)
        b.update("b", 1e-12)
        self.assertAlmostEqual(b.average_reward["b"], 1e-12)

    def test_integer_rewards_do_not_truncate_the_mean(self):
        # Integer division here would report 0 for a genuinely 0.5-mean arm.
        b = BanditSelector(ARMS)
        b.update("a", 1)
        b.update("a", 0)
        self.assertAlmostEqual(b.average_reward["a"], 0.5)

    def test_repeated_identical_rewards_stay_exact(self):
        b = BanditSelector(ARMS)
        for _ in range(1000):
            b.update("a", 0.3)
        self.assertAlmostEqual(b.average_reward["a"], 0.3, places=9)

    def test_single_arm_selector_is_supported(self):
        b = BanditSelector(("only",))
        b.update("only", 0.7)
        self.assertAlmostEqual(b.average_reward["only"], 0.7)
        self.assertEqual(b.best_arm(), "only")


class TestUpdateVisibleThroughStats(unittest.TestCase):
    def test_stats_reflect_updates_and_cannot_mutate_state(self):
        b = BanditSelector(ARMS)
        b.update("a", 1.0)
        snapshot = b.get_stats()
        self.assertEqual(snapshot["steps"], 1)
        self.assertEqual(snapshot["counts"]["a"], 1)
        snapshot["counts"]["a"] = 999
        self.assertEqual(b.counts["a"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
