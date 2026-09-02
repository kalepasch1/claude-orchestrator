"""With no revenue data, every EV score was exactly zero and the module was inert.

ev_scheduler.score starts from base = log10(1 + MRR of the task's project) and then
applies every discriminating factor as a MULTIPLIER: kind ROI from merge_revenue, a 1.5x
boost for revenue-shaped build tasks, 2x for an approved business-model slug, 0.3x for
flaky work, and outcome_weight() on top.

app_revenue on this fleet is an empty table. So mrr was 0 for every task, log10(1) = 0,
and every one of those multipliers multiplied zero. Two things followed:

  * park_zero_ev annotates anything scoring under ZERO_EV (0.01). Everything scored 0.0,
    so it parked its PARK_CAP of 20 tasks every run, forever, in arbitrary order. At
    01:14:47 UTC on 2026-09-02 it stamped 19 tasks in four seconds with "near-zero
    expected value — keep queued, run when capacity allows", among them the merge
    candidates the train was working that minute.

  * apply_ranking writes priority 1..50 from a total ordering of identical zeros, and
    claim_task sorts on priority ascending. The order the fleet claimed work in was a
    tie-break over noise.

The fix is a base of NO_REVENUE_BASE when NO project anywhere reports revenue. It does
not apply when revenue data exists — a fleet that has revenue should be ranked by it —
and the first test here is the pin for that.
"""
import pytest

import ev_scheduler as ev


NO_REVENUE = {"revenue_by_project": {}, "surface_returns": {}, "outcome_stats": {},
              "approved_slugs": set()}


def _ctx(**over):
    c = {k: (dict(v) if isinstance(v, dict) else set(v) if isinstance(v, set) else v)
         for k, v in NO_REVENUE.items()}
    c.update(over)
    return c


def test_revenue_weighting_is_unchanged_when_revenue_exists():
    """Regression pin. The fallback must not touch a fleet that has revenue data."""
    ctx = _ctx(revenue_by_project={"paid": 1000.0, "free": 0.0})
    import math
    expected = math.log10(1001) * 0.7 / 0.5
    assert ev.score({"project": "paid", "kind": "build"}, ctx) == pytest.approx(expected)


def test_a_project_with_no_revenue_still_ranks_below_one_that_has_it():
    """The fallback is for the degenerate case, not a way to outrank real revenue."""
    ctx = _ctx(revenue_by_project={"paid": 1000.0, "free": 0.0})
    assert ev.score({"project": "free"}, ctx) < ev.score({"project": "paid"}, ctx)


def test_with_no_revenue_anywhere_scores_are_not_zero():
    """The defect itself."""
    s = ev.score({"project": "tomorrow", "kind": "build"}, _ctx())
    assert s > 0, "every task scored exactly 0.0 with an empty app_revenue table"
    assert s > ev.ZERO_EV, (
        f"score {s} is still under ZERO_EV ({ev.ZERO_EV}), so park_zero_ev would keep "
        "stamping every task as near-zero expected value"
    )


def test_with_no_revenue_the_multipliers_actually_discriminate():
    """This is the point. Zero times anything is zero; the factors must now separate."""
    ctx = _ctx(approved_slugs={"approved-one"})
    plain = ev.score({"project": "p", "kind": "build", "prompt": "tidy the imports"}, ctx)
    revenue_shaped = ev.score(
        {"project": "p", "kind": "build", "prompt": "improve pricing conversion"}, ctx)
    approved = ev.score({"project": "p", "kind": "build", "slug": "approved-one"}, ctx)
    flaky = ev.score({"project": "p", "kind": "build", "transient_retries": 3}, ctx)

    assert revenue_shaped > plain, "the revenue-word boost is still inert"
    assert approved > plain, "the approved-slug boost is still inert"
    assert flaky < plain, "the flaky-work discount is still inert"
    assert len({round(plain, 6), round(revenue_shaped, 6),
                round(approved, 6), round(flaky, 6)}) == 4


def test_kind_roi_discriminates_with_no_revenue():
    """merge_revenue-derived kind returns were the most expensive signal to collect."""
    ctx = _ctx(surface_returns={"build": 50.0})
    build = ev.score({"project": "p", "kind": "build"}, ctx)
    other = ev.score({"project": "p", "kind": "chore"}, ctx)
    assert build > other


def test_success_rate_and_cost_discriminate_with_no_revenue():
    """A project that merges most of what it starts should outrank one that does not."""
    ctx = _ctx(outcome_stats={
        "good": {"success_rate": 0.9, "avg_usd": 0.1},
        "bad": {"success_rate": 0.1, "avg_usd": 2.0},
    })
    assert ev.score({"project": "good"}, ctx) > ev.score({"project": "bad"}, ctx)


def test_a_revenue_table_of_all_zeros_counts_as_no_revenue():
    """Rows can exist and be zero. That is the same degenerate case, not a signal."""
    ctx = _ctx(revenue_by_project={"a": 0.0, "b": 0, "c": None})
    assert ev.score({"project": "a"}, ctx) > ev.ZERO_EV


def test_the_base_is_tunable_and_can_be_restored_to_the_old_behaviour():
    """An operator who wants the old semantics back sets it to 0."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(ev, "NO_REVENUE_BASE", 0.0)
        assert ev.score({"project": "p"}, _ctx()) == 0.0


def test_a_project_with_zero_recent_successes_is_not_erased():
    """The second multiply-by-zero, and the one that closes a doom loop.

    success_rate read 0.000 for apparently-law and 0.000 for tomorrow on 2026-09-02 --
    the two projects whose merges this fleet exists to land. Zero makes score() return
    zero whatever else is true of the task, so every task in both sorts to the bottom
    and is parked; they then get capacity last, land nothing, and measure 0.000 again.
    """
    ctx = _ctx(outcome_stats={"tomorrow": {"success_rate": 0.0, "avg_usd": 0.0}})
    s = ev.score({"project": "tomorrow", "kind": "build"}, ctx)
    assert s > 0, "a project with no recent successes still scores exactly zero"
    assert s > ev.ZERO_EV


def test_the_floor_does_not_flatten_projects_that_do_succeed():
    """Low must still rank below high; the floor is a floor, not a leveller."""
    ctx = _ctx(outcome_stats={
        "dead": {"success_rate": 0.0, "avg_usd": 0.0},
        "alive": {"success_rate": 0.9, "avg_usd": 0.0},
    })
    assert ev.score({"project": "dead"}, ctx) < ev.score({"project": "alive"}, ctx)


def test_the_success_floor_is_tunable():
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(ev, "SUCCESS_RATE_FLOOR", 0.0)
        ctx = _ctx(outcome_stats={"tomorrow": {"success_rate": 0.0, "avg_usd": 0.0}})
        assert ev.score({"project": "tomorrow"}, ctx) == 0.0


def test_scoring_is_still_pure_and_deterministic():
    ctx = _ctx()
    task = {"project": "p", "kind": "build", "prompt": "growth work"}
    assert ev.score(task, ctx) == ev.score(task, ctx)
    assert ctx == _ctx(), "score() mutated the context it was given"
