#!/usr/bin/env python3
"""Epsilon-greedy policy for the prompt-evolution bandit.

Covers the four behaviours the slice specifies — exploration at high epsilon,
exploitation at epsilon=0, reward updating, and an end-to-end simulation — plus the
edges that make an epsilon-greedy bandit quietly wrong rather than loudly broken:

  * a greedy policy starting from all-zero means locks onto whichever arm it happened
    to pull first and never learns about the rest, so untried arms must be taken first;
  * a running sum divided by a separately-tracked count drifts, so the mean is folded
    incrementally;
  * an unknown arm id that silently registers itself dilutes the real arms' statistics
    and the typo never surfaces, so it must raise.

Randomness is injected rather than globally seeded: seeding random.seed() in a test
perturbs every other consumer of that stream in the same process.
"""
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bandit  # noqa: E402


class _ScriptedRng:
    """random-compatible stub. `values` drives random(); choice() takes the first arm."""

    def __init__(self, values, pick=0):
        self._values = list(values)
        self._pick = pick
        self.choice_calls = 0

    def random(self):
        return self._values.pop(0) if self._values else 1.0

    def choice(self, seq):
        self.choice_calls += 1
        return seq[self._pick]


def _warmed(arms, epsilon=0.1, decay=0.0, rewards=None):
    """A selector with every arm pulled once, so `select` is past the untried phase."""
    s = bandit.BanditSelector(arms, epsilon=epsilon, decay=decay)
    for a in arms:
        s.update_reward(a, (rewards or {}).get(a, 0.0))
    return s


class TestExploration(unittest.TestCase):
    """1) With epsilon high, selection explores."""

    def test_epsilon_one_always_explores(self):
        s = _warmed(["a", "b", "c"], epsilon=1.0, rewards={"a": 10.0})
        rng = _ScriptedRng([0.0] * 5, pick=2)
        for _ in range(5):
            # Explores despite 'a' being clearly best.
            self.assertEqual(s.select(rng=rng), "c")
        self.assertEqual(rng.choice_calls, 5)

    def test_exploration_can_return_any_arm(self):
        s = _warmed(["a", "b", "c"], epsilon=1.0, rewards={"a": 10.0})
        seen = {s.select(rng=_ScriptedRng([0.0], pick=i)) for i in range(3)}
        self.assertEqual(seen, {"a", "b", "c"})

    def test_untried_arms_are_taken_before_any_exploit(self):
        s = bandit.BanditSelector(["a", "b", "c"], epsilon=0.0)
        rng = _ScriptedRng([1.0] * 3)          # would always exploit
        picked = []
        for _ in range(3):
            arm = s.select(rng=rng)
            picked.append(arm)
            s.update_reward(arm, 0.0)
        self.assertEqual(sorted(picked), ["a", "b", "c"],
                         "every arm must be tried before greedy takes over")


class TestExploitation(unittest.TestCase):
    """2) With epsilon = 0, the best arm is always chosen."""

    def test_epsilon_zero_always_exploits(self):
        s = _warmed(["a", "b", "c"], epsilon=0.0, rewards={"a": 1.0, "b": 5.0, "c": 2.0})
        rng = _ScriptedRng([0.0] * 10)         # would explore if epsilon allowed it
        for _ in range(10):
            self.assertEqual(s.select(rng=rng), "b")
        self.assertEqual(rng.choice_calls, 0, "epsilon=0 must never call choice()")

    def test_best_arm_tracks_the_highest_mean(self):
        s = _warmed(["a", "b"], epsilon=0.0, rewards={"a": 1.0, "b": 2.0})
        self.assertEqual(s.best_arm(), "b")
        s.update_reward("a", 100.0)
        self.assertEqual(s.best_arm(), "a")

    def test_ties_break_deterministically_on_declared_order(self):
        a = _warmed(["x", "y"], epsilon=0.0, rewards={"x": 1.0, "y": 1.0})
        self.assertEqual(a.best_arm(), "x")
        self.assertEqual([a.best_arm() for _ in range(5)], ["x"] * 5)


class TestRewardUpdating(unittest.TestCase):
    """3) update_reward correctly updates count and average_reward."""

    def test_count_increments(self):
        s = bandit.BanditSelector(["a", "b"])
        s.update_reward("a", 1.0)
        s.update_reward("a", 1.0)
        self.assertEqual(s.counts["a"], 2)
        self.assertEqual(s.counts["b"], 0)

    def test_running_mean_is_correct(self):
        s = bandit.BanditSelector(["a"])
        for r in (1.0, 2.0, 6.0):
            s.update_reward("a", r)
        self.assertAlmostEqual(s.average_reward["a"], 3.0)

    def test_incremental_mean_matches_a_full_recompute(self):
        rewards = [0.3, 1.5, 2.25, 9.0, 0.0, 4.4, 7.1]
        s = bandit.BanditSelector(["a"])
        for r in rewards:
            s.update_reward("a", r)
        self.assertAlmostEqual(s.average_reward["a"], sum(rewards) / len(rewards))

    def test_first_reward_becomes_the_mean(self):
        s = bandit.BanditSelector(["a"])
        s.update_reward("a", 7.0)
        self.assertAlmostEqual(s.average_reward["a"], 7.0)

    def test_arms_do_not_contaminate_each_other(self):
        s = bandit.BanditSelector(["a", "b"])
        s.update_reward("a", 10.0)
        self.assertEqual(s.counts["b"], 0)
        self.assertAlmostEqual(s.average_reward["b"], 0.0)

    def test_unknown_arm_is_refused(self):
        s = bandit.BanditSelector(["a"])
        with self.assertRaises(KeyError):
            s.update_reward("typo", 1.0)

    def test_non_numeric_reward_is_refused(self):
        s = bandit.BanditSelector(["a"])
        with self.assertRaises(TypeError):
            s.update_reward("a", "not-a-number")

    def test_negative_rewards_are_allowed(self):
        s = bandit.BanditSelector(["a"])
        s.update_reward("a", -5.0)
        self.assertAlmostEqual(s.average_reward["a"], -5.0)

    def test_update_returns_the_new_mean(self):
        s = bandit.BanditSelector(["a"])
        s.update_reward("a", 2.0)
        self.assertAlmostEqual(s.update_reward("a", 4.0), 3.0)


class TestDecay(unittest.TestCase):
    def test_epsilon_decays_with_steps(self):
        s = bandit.BanditSelector(["a", "b"], epsilon=1.0, decay=0.1)
        first = s.current_epsilon()
        for _ in range(10):
            s.update_reward("a", 1.0)
        self.assertLess(s.current_epsilon(), first)

    def test_zero_decay_holds_epsilon_constant(self):
        s = bandit.BanditSelector(["a"], epsilon=0.4, decay=0.0)
        for _ in range(20):
            s.update_reward("a", 1.0)
        self.assertAlmostEqual(s.current_epsilon(), 0.4)

    def test_epsilon_never_goes_negative(self):
        s = bandit.BanditSelector(["a"], epsilon=1.0, decay=1.0)
        for _ in range(5):
            s.update_reward("a", 1.0)
        self.assertGreaterEqual(s.current_epsilon(), 0.0)


class TestIntegrationSimulation(unittest.TestCase):
    """4) A multi-step simulation checks average behaviour."""

    def test_converges_on_the_genuinely_better_arm(self):
        rng = random.Random(1234)          # local stream; global random untouched
        true_means = {"weak": 0.2, "mid": 0.5, "strong": 0.9}
        s = bandit.BanditSelector(list(true_means), epsilon=0.15, decay=0.0)
        for _ in range(600):
            arm = s.select(rng=rng)
            s.update_reward(arm, 1.0 if rng.random() < true_means[arm] else 0.0)

        self.assertEqual(s.best_arm(), "strong")
        self.assertGreater(s.counts["strong"], s.counts["weak"],
                           "the better arm must be pulled more often")
        self.assertAlmostEqual(s.average_reward["strong"], 0.9, delta=0.15)
        self.assertEqual(sum(s.counts.values()), 600)

    def test_every_arm_is_still_sampled(self):
        rng = random.Random(7)
        s = bandit.BanditSelector(["a", "b", "c"], epsilon=0.2, decay=0.0)
        for _ in range(300):
            arm = s.select(rng=rng)
            s.update_reward(arm, 1.0 if arm == "a" else 0.0)
        for a in ("a", "b", "c"):
            self.assertGreater(s.counts[a], 0, f"{a} was never explored")

    def test_stats_snapshot_is_a_copy(self):
        s = _warmed(["a", "b"], rewards={"a": 1.0})
        snap = s.stats()
        snap["counts"]["a"] = 999
        self.assertNotEqual(s.counts["a"], 999)
        self.assertEqual(snap["steps"], 2)
        self.assertIn("best_arm", snap)


if __name__ == "__main__":
    unittest.main()
