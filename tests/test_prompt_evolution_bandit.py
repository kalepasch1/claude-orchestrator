"""Prompt-template arm selection: strategy is swappable, ucb1 stays the default.

`select_template` hard-coded UCB1 inline, so there was no way to try a
posterior-sampling policy against the same history and no way to test the
scoring apart from the DB aggregation. `select_arm` extracts the policy and
adds thompson / epsilon_greedy behind an ORCH_ env var. The default is
unchanged, which is what the first test pins.
"""
import os
import random
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from runner import prompt_evolver as pe


def _hist(**kwargs):
    """{'base': (reward, trials), ...} -> the aggregated shape select_arm takes."""
    return {tid: {"total_reward": r, "n_trials": n} for tid, (r, n) in kwargs.items()}


# --- default preserved ----------------------------------------------------

def test_default_strategy_is_ucb1():
    assert pe.BANDIT_STRATEGY == os.environ.get("ORCH_PROMPT_BANDIT_STRATEGY", "ucb1")


def test_ucb1_prefers_an_untried_arm():
    """The regret bound depends on every arm being reachable."""
    hist = _hist(base=(9.0, 10), chain_of_thought=(0.0, 0), edit_first=(1.0, 10))
    assert pe.select_arm(hist, strategy="ucb1") == "chain_of_thought"


def test_ucb1_prefers_the_higher_acceptance_rate_once_all_arms_are_tried():
    hist = _hist(base=(9.0, 10), chain_of_thought=(2.0, 10), edit_first=(1.0, 10))
    assert pe.select_arm(hist, strategy="ucb1") == "base"


# --- thompson sampling ----------------------------------------------------

def test_thompson_concentrates_on_the_best_arm():
    """With a decisive history the posterior draw should almost always win."""
    hist = _hist(base=(95.0, 100), chain_of_thought=(5.0, 100), edit_first=(2.0, 100))
    rng = random.Random(1234)
    picks = [pe.select_arm(hist, strategy="thompson", rng=rng) for _ in range(200)]
    assert picks.count("base") > 190


def test_thompson_still_explores_a_thin_arm():
    """An arm with almost no history keeps a wide posterior, so it gets tried."""
    hist = _hist(base=(6.0, 10), chain_of_thought=(0.0, 1), edit_first=(0.0, 1))
    rng = random.Random(7)
    picks = {pe.select_arm(hist, strategy="thompson", rng=rng) for _ in range(200)}
    assert len(picks) > 1


def test_thompson_is_deterministic_for_a_seeded_rng():
    hist = _hist(base=(5.0, 10), chain_of_thought=(4.0, 10), edit_first=(3.0, 10))
    a = [pe.select_arm(hist, strategy="thompson", rng=random.Random(99)) for _ in range(20)]
    b = [pe.select_arm(hist, strategy="thompson", rng=random.Random(99)) for _ in range(20)]
    assert a == b


# --- epsilon greedy -------------------------------------------------------

def test_epsilon_greedy_exploits_when_the_draw_is_above_epsilon():
    hist = _hist(base=(2.0, 10), chain_of_thought=(8.0, 10), edit_first=(1.0, 10))

    class NoExplore:
        def random(self):
            return 0.99

        def choice(self, seq):  # pragma: no cover - must not be reached
            raise AssertionError("should not explore")

    assert pe.select_arm(hist, strategy="epsilon_greedy", rng=NoExplore()) == "chain_of_thought"


def test_epsilon_greedy_explores_when_the_draw_is_below_epsilon():
    hist = _hist(base=(2.0, 10), chain_of_thought=(8.0, 10), edit_first=(1.0, 10))

    class AlwaysExplore:
        def random(self):
            return 0.0

        def choice(self, seq):
            return seq[-1]

    assert pe.select_arm(hist, strategy="epsilon_greedy", rng=AlwaysExplore()) == "edit_first"


# --- fail-soft ------------------------------------------------------------

def test_empty_history_returns_base():
    assert pe.select_arm({}) == "base"
    assert pe.select_arm(None) == "base"


def test_unknown_strategy_falls_back_to_ucb1():
    hist = _hist(base=(9.0, 10), chain_of_thought=(1.0, 10), edit_first=(1.0, 10))
    assert pe.select_arm(hist, strategy="not-a-strategy") == "base"


def test_null_reward_and_trial_columns_do_not_raise():
    hist = {"base": {"total_reward": None, "n_trials": None},
            "edit_first": {"total_reward": 3.0, "n_trials": 3}}
    assert pe.select_arm(hist, strategy="ucb1") == "base"     # untried -> +inf
    assert pe.select_arm(hist, strategy="thompson", rng=random.Random(3)) in hist
    assert pe.select_arm(hist, strategy="epsilon_greedy",
                         rng=random.Random(3)) in hist


def test_acceptance_rate_is_zero_for_an_untried_arm():
    assert pe._acceptance({"total_reward": 0.0, "n_trials": 0}) == 0.0
    assert pe._acceptance({"total_reward": 5.0, "n_trials": 10}) == 0.5


# --- wiring ---------------------------------------------------------------

def test_select_template_passes_the_strategy_through(monkeypatch):
    seen = {}

    monkeypatch.setattr(
        pe.db, "select",
        lambda *a, **k: [{"template_id": "edit_first", "total_reward": 4.0, "n_trials": 4},
                         {"template_id": "base", "total_reward": 1.0, "n_trials": 4},
                         {"template_id": "chain_of_thought", "total_reward": 1.0, "n_trials": 4}],
    )

    def fake_select_arm(aggregated, strategy=None, rng=None):
        seen["strategy"] = strategy
        seen["aggregated"] = aggregated
        return "edit_first"

    monkeypatch.setattr(pe, "select_arm", fake_select_arm)
    pe.invalidate()

    prompt, template_id = pe.select_template("bugfix", "do the thing", strategy="thompson")

    assert seen["strategy"] == "thompson"
    assert seen["aggregated"]["edit_first"]["n_trials"] == 4
    assert template_id == "edit_first"
    assert prompt.startswith("[template:edit_first]\n")
    pe.invalidate()
