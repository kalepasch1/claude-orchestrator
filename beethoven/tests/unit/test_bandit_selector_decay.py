#!/usr/bin/env python3
"""Exponential-decay reward tracking in BanditSelector.

The acceptance case from the task brief is `test_acceptance_decay_sequence`:
BanditSelector(2, 0.1, alpha=0.2), arm 0 updated with [0.5, 0.7, 0.9], the
tracked average following new = alpha*reward + (1-alpha)*old with the first
observation seeding the average outright.
"""
from __future__ import annotations

import threading

import pytest

from beethoven.bandit_selector import ORCH_BANDIT_DEFAULT_ALPHA, BanditSelector


# -- acceptance ------------------------------------------------------------


def test_acceptance_decay_sequence():
    b = BanditSelector(2, 0.1, alpha=0.2)
    b.update(0, 0.5)
    assert b.average(0) == pytest.approx(0.5)
    b.update(0, 0.7)
    assert b.average(0) == pytest.approx(0.2 * 0.7 + 0.8 * 0.5)  # 0.54
    b.update(0, 0.9)
    assert b.average(0) == pytest.approx(0.2 * 0.9 + 0.8 * 0.54)  # 0.612


def test_acceptance_matches_closed_form():
    alpha = 0.2
    b = BanditSelector(2, 0.1, alpha=alpha)
    expected = None
    for reward in (0.5, 0.7, 0.9):
        b.update(0, reward)
        expected = reward if expected is None else alpha * reward + (1 - alpha) * expected
    assert b.average(0) == pytest.approx(expected)


# -- backward compatibility (the regression that failed the prior attempt) --


def test_default_is_simple_average_not_decay():
    """No alpha -> unchanged behaviour. A 0.1 default would silently
    re-point every existing caller's arm choice."""
    b = BanditSelector(2, 0.1)
    assert b.alpha is None
    for reward in (0.5, 0.7, 0.9):
        b.update(0, reward)
    assert b.average(0) == pytest.approx((0.5 + 0.7 + 0.9) / 3)


def test_seed_stays_third_positional():
    """alpha is declared AFTER seed, so positional callers keep binding."""
    a = BanditSelector(3, 0.0, 1234)
    b = BanditSelector(3, 0.0, 1234)
    assert a.alpha is None and b.alpha is None
    assert [a.select() for _ in range(5)] == [b.select() for _ in range(5)]


def test_recommended_alpha_constant_exposed():
    assert ORCH_BANDIT_DEFAULT_ALPHA == pytest.approx(0.1)
    b = BanditSelector(2, 0.1, alpha=ORCH_BANDIT_DEFAULT_ALPHA)
    assert b.alpha == pytest.approx(0.1)


def test_counts_and_sums_stay_raw_under_decay():
    """A later UCB1 slice needs true pull counts, not decayed ones."""
    b = BanditSelector(2, 0.1, alpha=0.3)
    for reward in (1.0, 0.0, 1.0):
        b.update(1, reward)
    assert b.counts[1] == 3
    assert b.sums[1] == pytest.approx(2.0)
    assert b.average(1) != pytest.approx(2.0 / 3)


# -- fail-soft alpha coercion ----------------------------------------------


@pytest.mark.parametrize("bad", ["nope", None, object(), [], {}])
def test_unusable_alpha_disables_decay(bad):
    b = BanditSelector(2, 0.1, alpha=bad)
    assert b.alpha is None


@pytest.mark.parametrize("bad", [0.0, -0.5, -1e9])
def test_non_positive_alpha_disables_decay(bad):
    """alpha <= 0 would freeze the average at its seed forever — the failure
    a caller is least able to notice. Disable rather than freeze."""
    b = BanditSelector(2, 0.1, alpha=bad)
    assert b.alpha is None
    for reward in (0.2, 0.4, 0.9):
        b.update(0, reward)
    assert b.average(0) == pytest.approx((0.2 + 0.4 + 0.9) / 3)


def test_nan_alpha_disables_decay():
    assert BanditSelector(2, 0.1, alpha=float("nan")).alpha is None


def test_alpha_above_one_is_clamped():
    b = BanditSelector(2, 0.1, alpha=7.5)
    assert b.alpha == pytest.approx(1.0)


def test_alpha_one_tracks_most_recent_reward_only():
    b = BanditSelector(2, 0.1, alpha=1.0)
    for reward in (0.1, 0.9, 0.3):
        b.update(0, reward)
    assert b.average(0) == pytest.approx(0.3)


def test_string_alpha_that_parses_is_accepted():
    assert BanditSelector(2, 0.1, alpha="0.25").alpha == pytest.approx(0.25)


# -- decay semantics -------------------------------------------------------


def test_first_pull_seeds_rather_than_decaying_against_zero():
    """Without seeding, a small alpha would report ~0.09 for a 0.9 reward."""
    b = BanditSelector(2, 0.1, alpha=0.1)
    b.update(0, 0.9)
    assert b.average(0) == pytest.approx(0.9)


def test_untried_arm_reports_zero():
    b = BanditSelector(3, 0.1, alpha=0.3)
    assert b.average(2) == 0.0
    assert b.averages()[2] == 0.0


def test_decay_favours_recent_rewards():
    """An arm that was good and turned bad must fall faster than a simple
    average would let it."""
    decayed = BanditSelector(1, 0.0, alpha=0.5)
    simple = BanditSelector(1, 0.0)
    for selector in (decayed, simple):
        for _ in range(10):
            selector.update(0, 1.0)
        for _ in range(3):
            selector.update(0, 0.0)
    assert decayed.average(0) < simple.average(0)


def test_decay_is_per_arm_and_independent():
    b = BanditSelector(3, 0.1, alpha=0.5)
    b.update(0, 1.0)
    b.update(1, 0.0)
    assert b.average(0) == pytest.approx(1.0)
    assert b.average(1) == pytest.approx(0.0)
    assert b.average(2) == pytest.approx(0.0)


def test_averages_matches_average_per_arm():
    b = BanditSelector(3, 0.1, alpha=0.4)
    for arm, rewards in ((0, (0.2, 0.8)), (1, (0.9,)), (2, ())):
        for reward in rewards:
            b.update(arm, reward)
    assert b.averages() == pytest.approx([b.average(i) for i in range(3)])


def test_negative_rewards_decay_correctly():
    b = BanditSelector(2, 0.1, alpha=0.5)
    b.update(0, -1.0)
    b.update(0, 1.0)
    assert b.average(0) == pytest.approx(0.0)


# -- integration with the rest of the contract -----------------------------


def test_best_arm_reads_decayed_value():
    b = BanditSelector(2, 0.0, alpha=0.6)
    for _ in range(5):
        b.update(0, 1.0)
        b.update(1, 0.0)
    assert b.best_arm() == 0
    # Arm 1 turns good, arm 0 turns bad: decay must flip the verdict fast.
    for _ in range(3):
        b.update(0, 0.0)
        b.update(1, 1.0)
    assert b.best_arm() == 1


def test_select_exploits_decayed_winner():
    b = BanditSelector(2, 0.0, seed=7, alpha=0.6)
    for _ in range(5):
        b.update(0, 0.0)
        b.update(1, 1.0)
    assert all(b.select() == 1 for _ in range(20))


def test_select_still_tries_every_arm_first():
    b = BanditSelector(4, 0.0, seed=3, alpha=0.5)
    seen = set()
    for _ in range(4):
        arm = b.select()
        seen.add(arm)
        b.update(arm, 0.0)
    assert seen == {0, 1, 2, 3}


def test_stats_reports_alpha_and_decayed_averages():
    b = BanditSelector(2, 0.1, alpha=0.25)
    b.update(0, 0.4)
    b.update(0, 0.8)
    stats = b.stats()
    assert stats["alpha"] == pytest.approx(0.25)
    assert stats["counts"][0] == 2
    assert stats["sums"][0] == pytest.approx(1.2)
    assert stats["averages"][0] == pytest.approx(0.25 * 0.8 + 0.75 * 0.4)


def test_stats_alpha_is_none_without_decay():
    assert BanditSelector(2, 0.1).stats()["alpha"] is None


def test_reset_clears_decayed_state():
    b = BanditSelector(2, 0.1, alpha=0.5)
    b.update(0, 1.0)
    b.reset()
    assert b.average(0) == 0.0
    assert b.counts == [0, 0]
    b.update(0, 0.25)
    assert b.average(0) == pytest.approx(0.25)  # seeds again, not decayed


# -- fail-soft update under decay ------------------------------------------


def test_bad_reward_leaves_decayed_average_untouched():
    b = BanditSelector(2, 0.1, alpha=0.5)
    b.update(0, 0.6)
    for bad in ("nope", None, float("nan"), object()):
        b.update(0, bad)
    assert b.average(0) == pytest.approx(0.6)
    assert b.counts[0] == 1


def test_out_of_range_arm_is_ignored_under_decay():
    b = BanditSelector(2, 0.1, alpha=0.5)
    b.update(9, 1.0)
    b.update(-1, 1.0)
    assert b.averages() == [0.0, 0.0]
    assert b.counts == [0, 0]


def test_single_arm_selector_with_decay_never_raises():
    b = BanditSelector(1, 0.5, alpha=0.5)
    for _ in range(10):
        b.update(b.select(), 0.5)
    assert b.select() == 0
    assert b.average(0) == pytest.approx(0.5)


def test_concurrent_updates_do_not_corrupt_decayed_state():
    b = BanditSelector(4, 0.1, alpha=0.3)

    def worker():
        for _ in range(200):
            b.update(1, 0.5)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert b.counts[1] == 800
    # Every reward was 0.5, so the decayed average must be exactly 0.5.
    assert b.average(1) == pytest.approx(0.5)
    assert 0.0 <= b.average(1) <= 1.0


def test_decayed_average_stays_within_reward_bounds():
    b = BanditSelector(2, 0.1, seed=11, alpha=0.35)
    import random as _random

    rng = _random.Random(99)
    for _ in range(500):
        b.update(0, rng.uniform(0.0, 1.0))
    assert 0.0 <= b.average(0) <= 1.0
    assert b.average(0) == b.average(0)  # not NaN
