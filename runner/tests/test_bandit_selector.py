#!/usr/bin/env python3
"""Initialization contract for bandit.BanditSelector (slice 5).

This slice ships structure only — no selection algorithm — so these tests pin the
constructor's behavior: what it accepts, what it normalizes, and what it refuses.
The refusals matter more than the acceptances. A selector built over an empty arm
set, or over a bare string that iterates into single characters, would construct
cleanly and then misbehave much later at selection time, where the cause is far
from the symptom. Failing at construction keeps the blame local.
"""
import os
import sys
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bandit  # noqa: E402


def test_importable():
    assert hasattr(bandit, "BanditSelector")


def test_minimal_construction_uses_documented_defaults():
    s = bandit.BanditSelector(["a", "b"])
    assert s.arm_ids == ("a", "b")
    assert s.epsilon == 0.1
    assert s.decay == 0.01


def test_full_parameter_set_is_stored_verbatim():
    s = bandit.BanditSelector(["a", "b", "c"], epsilon=0.25, decay=0.05)
    assert s.arm_ids == ("a", "b", "c")
    assert s.epsilon == 0.25
    assert s.decay == 0.05


def test_arm_order_is_preserved_and_duplicates_collapse():
    # Order is the caller's; duplicates would silently double an arm's weight.
    s = bandit.BanditSelector(["b", "a", "b", "c"])
    assert s.arm_ids == ("b", "a", "c")
    assert len(s) == 3


def test_accepts_any_iterable_of_strings():
    s = bandit.BanditSelector(("x", "y"))
    assert s.arm_ids == ("x", "y")
    s2 = bandit.BanditSelector(iter(["x", "y"]))
    assert s2.arm_ids == ("x", "y")


def test_bare_string_is_refused_not_split_into_characters():
    with pytest.raises(TypeError):
        bandit.BanditSelector("abc")


def test_empty_arm_set_is_refused():
    with pytest.raises(ValueError):
        bandit.BanditSelector([])


@pytest.mark.parametrize("bad", [[1, 2], ["ok", None], ["ok", ""]])
def test_non_string_or_empty_arm_ids_are_refused(bad):
    with pytest.raises(TypeError):
        bandit.BanditSelector(bad)


@pytest.mark.parametrize("eps", [-0.1, 1.5])
def test_out_of_range_epsilon_is_refused_not_clamped(eps):
    with pytest.raises(ValueError):
        bandit.BanditSelector(["a"], epsilon=eps)


@pytest.mark.parametrize("dec", [-0.01, 2.0])
def test_out_of_range_decay_is_refused_not_clamped(dec):
    with pytest.raises(ValueError):
        bandit.BanditSelector(["a"], decay=dec)


def test_boundary_values_are_allowed():
    s = bandit.BanditSelector(["a"], epsilon=0.0, decay=0.0)
    assert (s.epsilon, s.decay) == (0.0, 0.0)
    s = bandit.BanditSelector(["a"], epsilon=1.0, decay=1.0)
    assert (s.epsilon, s.decay) == (1.0, 1.0)


def test_repr_round_trips_the_configuration():
    s = bandit.BanditSelector(["a", "b"], epsilon=0.3, decay=0.02)
    r = repr(s)
    assert "BanditSelector" in r and "'a'" in r and "0.3" in r


def test_instances_do_not_share_state():
    a = bandit.BanditSelector(["a"], epsilon=0.2)
    b = bandit.BanditSelector(["b"], epsilon=0.4)
    assert a.arm_ids != b.arm_ids and a.epsilon != b.epsilon
