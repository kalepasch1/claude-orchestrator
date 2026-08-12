#!/usr/bin/env python3
"""Unit tests for prompt_evolution_bandit.

Covers the three required entry points (select_action / update / accept), the
lazy arm registration that lets a newly-evolved template join a running
experiment, and the fail-soft contract: bad input returns a default, never raises.
"""
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import prompt_evolution_bandit as peb  # noqa: E402


class FixedRng:
    """Deterministic stand-in for `random` so explore/exploit is not a coin flip."""

    def __init__(self, value, choice_index=0):
        self.value = value
        self.choice_index = choice_index

    def random(self):
        return self.value

    def choice(self, seq):
        return list(seq)[self.choice_index]


class SelectActionTests(unittest.TestCase):
    def test_empty_bandit_returns_empty_string(self):
        b = peb.Bandit()
        self.assertEqual(b.select_action(), "")

    def test_untried_arms_come_first(self):
        b = peb.Bandit(["a", "b", "c"])
        # Every arm is untried, so selection is deterministic regardless of rng.
        self.assertEqual(b.select_action(rng=FixedRng(0.0)), "a")
        b.update("a", 1.0)
        self.assertEqual(b.select_action(), "b")
        b.update("b", 1.0)
        self.assertEqual(b.select_action(), "c")

    def test_exploit_picks_best_arm(self):
        b = peb.Bandit(["a", "b"], epsilon=0.5, decay=0.0)
        b.update("a", 0.1)
        b.update("b", 0.9)
        # rng.random() == 0.99 > epsilon -> exploit
        self.assertEqual(b.select_action(rng=FixedRng(0.99)), "b")

    def test_explore_uses_rng_choice(self):
        b = peb.Bandit(["a", "b"], epsilon=0.5, decay=0.0)
        b.update("a", 0.9)
        b.update("b", 0.1)
        # rng.random() == 0.0 < epsilon -> explore, choice_index 1 -> "b"
        self.assertEqual(b.select_action(rng=FixedRng(0.0, choice_index=1)), "b")

    def test_arm_ids_argument_registers_lazily(self):
        b = peb.Bandit()
        self.assertEqual(b.select_action(["v1", "v2"]), "v1")
        self.assertEqual(b.arm_ids, ("v1", "v2"))

    def test_new_variant_joins_without_losing_stats(self):
        b = peb.Bandit(["baseline"])
        for _ in range(5):
            b.update("baseline", 1.0)
        b.select_action(["baseline", "evolved"])
        self.assertEqual(b.arm_ids, ("baseline", "evolved"))
        self.assertEqual(b.stats()["counts"]["baseline"], 5)
        self.assertAlmostEqual(b.stats()["average_reward"]["baseline"], 1.0)

    def test_selection_is_stable_under_real_rng(self):
        b = peb.Bandit(["a", "b"], epsilon=0.0, decay=0.0)
        b.update("a", 0.0)
        b.update("b", 1.0)
        rng = random.Random(7)
        picks = {b.select_action(rng=rng) for _ in range(50)}
        self.assertEqual(picks, {"b"})


class UpdateTests(unittest.TestCase):
    def test_update_returns_running_mean(self):
        b = peb.Bandit(["a"])
        self.assertAlmostEqual(b.update("a", 1.0), 1.0)
        self.assertAlmostEqual(b.update("a", 0.0), 0.5)
        self.assertAlmostEqual(b.update("a", 0.5), 0.5)

    def test_update_registers_unknown_arm(self):
        b = peb.Bandit()
        b.update("brand-new", 1.0)
        self.assertIn("brand-new", b.arm_ids)
        self.assertEqual(b.stats()["counts"]["brand-new"], 1)

    def test_update_with_bad_reward_is_fail_soft(self):
        b = peb.Bandit(["a"])
        self.assertEqual(b.update("a", "not-a-number"), 0.0)
        self.assertEqual(b.stats()["counts"]["a"], 0)

    def test_update_with_bad_arm_id_is_fail_soft(self):
        b = peb.Bandit(["a"])
        self.assertEqual(b.update(None, 1.0), 0.0)
        self.assertEqual(b.arm_ids, ("a",))

    def test_counts_track_pulls(self):
        b = peb.Bandit(["a", "b"])
        for _ in range(3):
            b.update("a", 1.0)
        b.update("b", 1.0)
        self.assertEqual(b.stats()["counts"], {"a": 3, "b": 1})


class AcceptTests(unittest.TestCase):
    def test_rejects_before_min_pulls(self):
        b = peb.Bandit(["a", "b"], min_pulls=5, margin=0.0)
        b.update("b", 0.0)
        for _ in range(4):
            b.update("a", 1.0)
        self.assertFalse(b.accept("a"))

    def test_accepts_with_pulls_and_margin(self):
        b = peb.Bandit(["a", "b"], min_pulls=5, margin=0.05)
        for _ in range(5):
            b.update("a", 1.0)
            b.update("b", 0.0)
        self.assertTrue(b.accept("a"))
        self.assertFalse(b.accept("b"))

    def test_rejects_when_margin_not_met(self):
        b = peb.Bandit(["a", "b"], min_pulls=3, margin=0.2)
        for _ in range(3):
            b.update("a", 1.0)
            b.update("b", 0.9)
        self.assertFalse(b.accept("a"))

    def test_sole_arm_is_never_accepted(self):
        b = peb.Bandit(["only"], min_pulls=1, margin=0.0)
        for _ in range(10):
            b.update("only", 1.0)
        self.assertFalse(b.accept("only"))

    def test_unknown_arm_rejected(self):
        b = peb.Bandit(["a", "b"], min_pulls=1, margin=0.0)
        b.update("a", 1.0)
        b.update("b", 0.0)
        self.assertFalse(b.accept("nope"))

    def test_accept_on_empty_bandit_is_false(self):
        self.assertFalse(peb.Bandit().accept("anything"))


class StatsAndStubTests(unittest.TestCase):
    def test_stats_on_empty_bandit(self):
        s = peb.Bandit().stats()
        self.assertEqual(s["steps"], 0)
        self.assertEqual(s["counts"], {})

    def test_stats_reports_gates(self):
        b = peb.Bandit(["a", "b"], min_pulls=9, margin=0.25)
        b.update("a", 1.0)
        s = b.stats()
        self.assertEqual(s["min_pulls"], 9)
        self.assertAlmostEqual(s["margin"], 0.25)
        self.assertEqual(s["best_arm"], "a")

    def test_reset_clears_state(self):
        b = peb.Bandit(["a"])
        b.update("a", 1.0)
        b.reset()
        self.assertEqual(b.arm_ids, ())
        self.assertEqual(b.stats()["steps"], 0)

    def test_load_performance_stub_is_empty_mapping(self):
        self.assertEqual(peb.load_performance(), {})

    def test_warm_start_stub_folds_nothing_and_does_not_raise(self):
        peb.reset()
        self.assertEqual(peb.warm_start(), 0)


class ModuleSingletonTests(unittest.TestCase):
    def setUp(self):
        peb.reset()

    def tearDown(self):
        peb.reset()

    def test_module_functions_delegate_to_singleton(self):
        self.assertEqual(peb.select_action(["x", "y"]), "x")
        peb.update("x", 1.0)
        self.assertEqual(peb.stats()["counts"]["x"], 1)
        self.assertFalse(peb.accept("x"))

    def test_module_select_action_on_empty_is_empty_string(self):
        self.assertEqual(peb.select_action(), "")


if __name__ == "__main__":
    unittest.main()
