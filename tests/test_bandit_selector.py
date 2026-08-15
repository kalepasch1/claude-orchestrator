"""Behavioural tests for runner.bandit.BanditSelector (slice 4).

Slice 3 landed the constructor and `runner/tests/test_bandit_selector.py`
covers construction/validation exhaustively. This file covers the three
*behavioural* acceptance scenarios and deliberately does not re-test
construction.

Adaptation note: the acceptance text sketched `BanditSelector(3, 0.1)` with
integer arm indices. The shipped constructor takes an explicit sequence of
string arm ids (an int is refused by design — see the slice-3 validation
tests), so scenario 1 asserts membership in the declared arm set, which is
the same property expressed against the real API.

Every test injects a seeded `random.Random` so results are deterministic and
the global random stream is never perturbed. Each test runs in well under
the 5-second per-test budget.
"""
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "runner"))

from bandit import BanditSelector  # noqa: E402

ARMS = ("arm-0", "arm-1", "arm-2")


class TestSelectionReturnsValidArms(unittest.TestCase):
    """Scenario 1: basic instantiation and selection.

    Validates that `select()` is total over the declared arm set: every call,
    in every phase (cold start, exploration, exploitation), returns one of the
    ids the caller declared and never None, an index, or an unknown id.
    """

    def test_select_always_returns_a_declared_arm(self):
        sel = BanditSelector(ARMS, 0.1)
        rng = random.Random(20260812)
        seen = set()
        for _ in range(200):
            arm = sel.select(rng=rng)
            self.assertIn(arm, ARMS)
            seen.add(arm)
            sel.update_reward(arm, rng.random())
        # With epsilon exploration and untried-arms-first, all three must have
        # been pulled at least once — a selector that locks onto one arm from
        # the cold start is the classic epsilon-greedy failure mode.
        self.assertEqual(seen, set(ARMS))

    def test_cold_start_pulls_every_untried_arm_before_exploiting(self):
        """Untried arms are taken first, in declared order."""
        sel = BanditSelector(ARMS, 0.1)
        rng = random.Random(7)
        first_pulls = []
        for _ in range(len(ARMS)):
            arm = sel.select(rng=rng)
            first_pulls.append(arm)
            sel.update_reward(arm, 0.0)
        self.assertEqual(first_pulls, list(ARMS))

    def test_select_does_not_mutate_state(self):
        """Selection is a read: only update_reward() advances counts/steps."""
        sel = BanditSelector(ARMS, 0.1)
        rng = random.Random(1)
        for arm in ARMS:
            sel.update_reward(arm, 0.5)
        before = sel.stats()
        for _ in range(50):
            sel.select(rng=rng)
        self.assertEqual(sel.stats(), before)


class TestDecayAndAveraging(unittest.TestCase):
    """Scenario 2: verify the stored values against their closed forms.

    Two formulas are load-bearing in this class and both are asserted against
    an independent recomputation rather than a hard-coded snapshot:

      * exploration decays exponentially:  eps_t = epsilon * (1 - decay)**steps
      * stored reward is the incremental arithmetic mean:  mean += (r - mean)/n
    """

    def test_epsilon_follows_the_exponential_decay_formula(self):
        epsilon, decay = 0.5, 0.05
        sel = BanditSelector(ARMS, epsilon, decay)
        self.assertAlmostEqual(sel.current_epsilon(), epsilon, places=12)
        for step in range(1, 31):
            sel.update_reward(ARMS[step % len(ARMS)], 1.0)
            expected = epsilon * ((1.0 - decay) ** step)
            self.assertAlmostEqual(sel.current_epsilon(), expected, places=12,
                                   msg=f"epsilon diverged at step {step}")
        # Decay is monotone and never leaves [0, 1].
        self.assertLess(sel.current_epsilon(), epsilon)
        self.assertGreaterEqual(sel.current_epsilon(), 0.0)

    def test_zero_decay_holds_epsilon_constant(self):
        """decay=0 must be a true no-op, not a near-1.0 multiplier."""
        sel = BanditSelector(ARMS, 0.3, decay=0.0)
        for _ in range(100):
            sel.update_reward("arm-0", 1.0)
        self.assertAlmostEqual(sel.current_epsilon(), 0.3, places=12)

    def test_stored_average_matches_incremental_mean(self):
        """A known reward sequence reproduces the plain arithmetic mean."""
        sel = BanditSelector(ARMS, 0.1)
        rewards = [0.9, 0.1, 0.5, 0.75, 0.25, 1.0, 0.0, 0.4]
        for i, r in enumerate(rewards, start=1):
            returned = sel.update_reward("arm-1", r)
            expected = sum(rewards[:i]) / i
            # update_reward returns the new mean and stores the same value.
            self.assertAlmostEqual(returned, expected, places=12)
            self.assertAlmostEqual(sel.average_reward["arm-1"], expected,
                                   places=12, msg=f"mean diverged at pull {i}")
        self.assertEqual(sel.counts["arm-1"], len(rewards))
        # Untouched arms stay at their initial value.
        self.assertEqual(sel.average_reward["arm-0"], 0.0)
        self.assertEqual(sel.counts["arm-0"], 0)

    def test_unknown_arm_is_refused(self):
        """A typo'd arm id must not silently register a new arm."""
        sel = BanditSelector(ARMS, 0.1)
        with self.assertRaises(KeyError):
            sel.update_reward("arm-99", 1.0)
        self.assertEqual(set(sel.counts), set(ARMS))


class TestConvergenceOnBestArm(unittest.TestCase):
    """Scenario 3: the selector concentrates on the genuinely better arm.

    One arm pays ~0.8, the others ~0.2. Over 1000+ pulls the high-reward arm
    must be chosen far more often than either low-reward arm. The bound is
    deliberately loose (>60%) — this asserts that learning happens, not that a
    particular seed produces a particular trajectory.
    """

    TRIALS = 1200
    GOOD, NOISE = "arm-1", 0.05

    def _run(self, seed, decay=0.01):
        rng = random.Random(seed)
        sel = BanditSelector(ARMS, epsilon=0.1, decay=decay)
        picks = {a: 0 for a in ARMS}
        for _ in range(self.TRIALS):
            arm = sel.select(rng=rng)
            picks[arm] += 1
            mean = 0.8 if arm == self.GOOD else 0.2
            sel.update_reward(arm, rng.gauss(mean, self.NOISE))
        return sel, picks

    def test_high_reward_arm_dominates_selection(self):
        sel, picks = self._run(seed=424242)
        share = picks[self.GOOD] / self.TRIALS
        self.assertGreater(share, 0.60,
                           f"best arm chosen only {share:.1%} of the time: {picks}")
        for arm in ARMS:
            if arm != self.GOOD:
                self.assertLess(picks[arm], picks[self.GOOD])
        self.assertEqual(sel.best_arm(), self.GOOD)
        self.assertAlmostEqual(sel.average_reward[self.GOOD], 0.8, delta=0.05)

    def test_convergence_is_not_seed_dependent(self):
        """The same property holds across independent seeds, not just one."""
        for seed in (1, 99, 2026, 31337):
            _, picks = self._run(seed=seed)
            share = picks[self.GOOD] / self.TRIALS
            self.assertGreater(share, 0.60,
                               f"seed {seed}: best arm share {share:.1%}")

    def test_pure_greedy_still_finds_the_best_arm(self):
        """epsilon=0 relies entirely on the untried-arms-first cold start."""
        rng = random.Random(5)
        sel = BanditSelector(ARMS, epsilon=0.0)
        picks = {a: 0 for a in ARMS}
        for _ in range(self.TRIALS):
            arm = sel.select(rng=rng)
            picks[arm] += 1
            sel.update_reward(arm, 0.8 if arm == self.GOOD else 0.2)
        self.assertEqual(sel.best_arm(), self.GOOD)
        self.assertGreater(picks[self.GOOD] / self.TRIALS, 0.60)


if __name__ == "__main__":
    unittest.main()
