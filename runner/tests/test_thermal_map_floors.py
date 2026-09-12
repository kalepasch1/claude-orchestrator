"""The queue's real scoring function had the same two multiply-by-zeros, and it is the
one that decides what gets claimed.

ev_scheduler.score() and thermal_map.expected_value() are near-identical twins — the same
`log10(1 + revenue) * success / (avg_usd + 0.5)` opening, the same multiplier stack. Both
carried the same pair of absorbing zeros. Fixing ev_scheduler.score() on 2026-09-01
accomplished nothing, because _scored_queue() — which feeds BOTH park_zero_ev and
claim_task's ordering — calls thermal_score(), which calls THIS function.

Measured on the live queue after that first fix:

    ev_scheduler.score()     0 of 296 tasks below ZERO_EV
    thermal_map.score()    185 of 296 below, minimum exactly 0.0000

and 18 tasks were still being stamped "near-zero expected value" per run — including
several the fixed twin scored at 0.42 and 1.4.

The floors now live here, once, and ev_scheduler imports them. Two independent copies of
the same constant in two near-identical functions is precisely how the first fix landed
on the twin nobody calls.
"""
import math

import pytest

import ev_scheduler
import thermal_map as tm


NONE = {"revenue_by_project": {}, "surface_returns": {}, "outcome_stats": {},
        "approved_slugs": set()}


def _ctx(**over):
    c = {k: (dict(v) if isinstance(v, dict) else set(v) if isinstance(v, set) else v)
         for k, v in NONE.items()}
    c.update(over)
    return c


def test_the_floors_are_defined_once_and_shared():
    """Not two copies. The drift between two copies is the whole bug above."""
    assert ev_scheduler.NO_REVENUE_BASE is tm.NO_REVENUE_BASE
    assert ev_scheduler.SUCCESS_RATE_FLOOR is tm.SUCCESS_RATE_FLOOR


def test_with_no_revenue_anywhere_value_is_not_zero():
    v = tm.expected_value({"project": "tomorrow", "kind": "build"}, _ctx())
    assert v > 0
    assert v > ev_scheduler.ZERO_EV


def test_a_project_with_no_recent_successes_is_not_erased():
    """apparently-law and tomorrow both read 0.000 in the recent outcomes window."""
    ctx = _ctx(outcome_stats={"tomorrow": {"success_rate": 0.0, "avg_usd": 0.0}})
    assert tm.expected_value({"project": "tomorrow"}, ctx) > 0


def test_revenue_weighting_is_unchanged_where_revenue_exists():
    """Regression pin. A fleet that HAS revenue data must be ranked by it, exactly as
    before."""
    ctx = _ctx(revenue_by_project={"paid": 1000.0, "free": 0.0})
    expected = math.log10(1001) * 0.7 / 0.5
    assert tm.expected_value({"project": "paid"}, ctx) == pytest.approx(expected)


def test_a_zero_revenue_project_still_ranks_below_a_paying_one():
    ctx = _ctx(revenue_by_project={"paid": 1000.0, "free": 0.0})
    assert (tm.expected_value({"project": "free"}, ctx)
            < tm.expected_value({"project": "paid"}, ctx))


def test_the_multipliers_discriminate_again():
    """Zero times anything is zero. These four used to be indistinguishable."""
    ctx = _ctx(approved_slugs={"approved-one"})
    plain = tm.expected_value({"project": "p", "kind": "build", "prompt": "tidy"}, ctx)
    revenue = tm.expected_value(
        {"project": "p", "kind": "build", "prompt": "improve pricing conversion"}, ctx)
    approved = tm.expected_value({"project": "p", "kind": "build", "slug": "approved-one"}, ctx)
    flaky = tm.expected_value({"project": "p", "kind": "build", "transient_retries": 3}, ctx)
    assert revenue > plain and approved > plain and flaky < plain
    assert len({round(x, 6) for x in (plain, revenue, approved, flaky)}) == 4


@pytest.mark.parametrize("const", ["NO_REVENUE_BASE", "SUCCESS_RATE_FLOOR"])
def test_each_floor_can_be_set_to_zero_to_restore_the_old_arithmetic(const):
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(tm, const, 0.0)
        ctx = _ctx(outcome_stats={"p": {"success_rate": 0.0, "avg_usd": 0.0}})
        assert tm.expected_value({"project": "p"}, ctx) == 0.0


def test_parking_reads_value_not_value_per_minute():
    """PARKS ON VALUE, ORDERS ON VALUE-PER-MINUTE.

    thermal_map.score is expected_value / estimated minutes — right for deciding what to
    claim first, wrong for "is this worth anything". A task worth an ordinary 1.4 that is
    estimated at 480 minutes rates 0.0029, under ZERO_EV, and used to be stamped
    "near-zero expected value" — which is false of it. It is near-zero value PER MINUTE,
    because it is big, and parking on that systematically deprioritises the largest work.
    """
    ctx = _ctx()
    # A shape the live queue actually contains: a build, described in words
    # estimate_minutes reads as large, with dependencies and prior remediation.
    big = {"project": "p", "kind": "build", "slug": "big",
           "prompt": "architecture migration rewrite of the monorepo",
           "deps": ["a", "b", "c", "d"], "remediation_count": 3}
    assert tm.estimate_minutes(big, ctx) > 60, "fixture is not actually a big task"
    assert tm.score(big, ctx) < ev_scheduler.ZERO_EV, "fixture does not reproduce the shape"
    assert tm.expected_value(big, ctx) > ev_scheduler.ZERO_EV, (
        "a big task with ordinary value must not read as near-zero VALUE"
    )


def test_park_zero_ev_uses_the_context_it_is_given():
    """The ordering and the parking decision must see the same revenue snapshot.

    Without this, park_zero_ev calls load_ctx() itself and can disagree with the ranking
    that was computed a moment earlier from a different read.
    """
    import inspect
    src = inspect.getsource(ev_scheduler.park_zero_ev)
    assert "thermal_map.expected_value(t, ctx)" in src, (
        "park_zero_ev no longer parks on value — it is back to parking on value/minute "
        "and will stamp 'near-zero expected value' on big tasks that are worth plenty"
    )
    run_src = inspect.getsource(ev_scheduler.run)
    assert "park_zero_ev(scored, ctx=ctx)" in run_src, (
        "run() no longer hands park_zero_ev the ctx it ranked with"
    )
