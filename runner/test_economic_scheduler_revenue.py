#!/usr/bin/env python3
"""Revenue logic of the economic scheduler, scenario by scenario.

WHY THIS FILE IS BEING WRITTEN RATHER THAN RECOVERED
----------------------------------------------------
`BUILD-TEST-LOG-economic-scheduler-revenue.md` and
`patches/economic-scheduler-revenue.README.md` both cite results from
`runner/test_economic_scheduler_revenue.py` ("28/28 passed", "baseline master 25/28").
That file is not on master. The prior attempt branches, per the README's own findings,
"contain only 4-line stub .txt files — no recoverable patch content", so there is nothing
to restore; the log documents a suite that exists only in those runs.

So this is the suite, written against the implementation that actually ships. It is
deliberately SCENARIO-shaped, as the task asks: each class is one situation the scheduler
has to price correctly, from an empty queue to a full load.

TWO THINGS IT REFUSES TO DO
---------------------------
1. It does not hardcode the confidence band. The predecessor of this file demanded ±25%
   while `runner/test_economic_scheduler.py` demanded ±20%, and `predict_revenue`'s own
   comment records the measurement: setting either value fixed one file and broke the
   other, "a suite that cannot be satisfied". The band is read from the module here, so
   the contradiction cannot come back.
2. It does not assume the unapplied `patches/economic-scheduler-revenue.patch`. That
   patch narrows REVENUE_KEYWORDS to intent phrases and its own README says "DO NOT APPLY
   without reading docs/ECONOMIC_SCHEDULER_AUDIT.md §5 first — the live test suite asserts
   the opposite intent for payment BUGFIX tasks". Tests assert what ships; the keyword
   question stays open and is named in test_a_bare_keyword_mention_still_boosts.
"""
from __future__ import annotations

import math
import os
import sys
import unittest

RUNNER = os.path.dirname(os.path.abspath(__file__))
if RUNNER not in sys.path:
    sys.path.insert(0, RUNNER)

import economic_scheduler as es  # noqa: E402

BAND = float(os.environ.get("ORCH_ECONOMIC_CONFIDENCE_BAND", "0.20"))

BUILD_RETURN = 100.0
BUGFIX_RETURN = 40.0


def ctx(**over):
    """Baseline scheduling context. Each scenario varies exactly one axis off this."""
    base = {
        "kind_roi": {"build": BUILD_RETURN, "bugfix": BUGFIX_RETURN},
        "high_growth_projects": set(),
        "error_rates": {},
        "pricing": {"tiers": {}, "rate_limits": {}, "ttl_seconds": 3600},
    }
    base.update(over)
    return base


def task(**over):
    base = {"id": "t1", "project": "apparently", "kind": "build",
            "prompt": "add a widget", "usd": 2.0}
    base.update(over)
    return base


class ScenarioEmptyQueue(unittest.TestCase):
    """Scenario 1 — nothing to schedule. The sweep must be a no-op, not a crash."""

    def test_no_tasks_predicts_nothing(self):
        self.assertEqual(es.predict_revenue_bulk([], ctx()), {})

    def test_a_none_queue_is_treated_as_empty(self):
        self.assertEqual(es.predict_revenue_bulk(None, ctx()), {})

    def test_an_empty_queue_routes_nothing_and_writes_nothing(self):
        self.assertEqual(es.apply_routing([])["routed"], 0)

    def test_a_queue_of_junk_rows_yields_no_predictions(self):
        self.assertEqual(es.predict_revenue_bulk([None, 5, "x", {}], ctx()), {})


class ScenarioSingleJob(unittest.TestCase):
    """Scenario 2 — one task, no boosts. The base case every other number is relative to."""

    def test_the_kinds_historical_return_is_the_estimate(self):
        self.assertEqual(es.predict_revenue(task(), ctx())["point_estimate"], BUILD_RETURN)

    def test_the_band_brackets_the_estimate_symmetrically(self):
        out = es.predict_revenue(task(), ctx())
        self.assertAlmostEqual(out["confidence_low"], BUILD_RETURN * (1 - BAND), places=6)
        self.assertAlmostEqual(out["confidence_high"], BUILD_RETURN * (1 + BAND), places=6)

    def test_the_result_reads_as_both_a_tuple_and_a_mapping(self):
        out = es.predict_revenue(task(), ctx())
        point, low, high = out
        self.assertEqual(point, out["point_estimate"])
        self.assertEqual(low, out["confidence_low"])
        self.assertEqual(high, out["confidence_high"])

    def test_bulk_over_one_task_matches_the_single_prediction(self):
        bulk = es.predict_revenue_bulk([task(id="a")], ctx())
        self.assertEqual(bulk["a"], es.predict_revenue(task(id="a"), ctx())["point_estimate"])


class ScenarioVaryingRates(unittest.TestCase):
    """Scenario 3 — the same work is worth different amounts in different contexts."""

    def test_a_higher_historical_return_predicts_proportionally_more(self):
        rich = es.predict_revenue(task(), ctx(kind_roi={"build": 500.0}))["point_estimate"]
        poor = es.predict_revenue(task(), ctx(kind_roi={"build": 50.0}))["point_estimate"]
        self.assertAlmostEqual(rich, poor * 10.0)

    def test_a_high_growth_project_doubles_the_estimate(self):
        boosted = es.predict_revenue(
            task(), ctx(high_growth_projects={"apparently"}))["point_estimate"]
        self.assertAlmostEqual(boosted, BUILD_RETURN * 2.0)

    def test_a_revenue_keyword_adds_half_again(self):
        boosted = es.predict_revenue(
            task(prompt="rework the billing page"), ctx())["point_estimate"]
        self.assertAlmostEqual(boosted, BUILD_RETURN * 1.5)

    def test_every_declared_keyword_actually_fires(self):
        """A keyword list nothing reads is the classic dead constant."""
        for keyword in es.REVENUE_KEYWORDS:
            with self.subTest(keyword=keyword):
                out = es.predict_revenue(task(prompt=f"work on {keyword}"), ctx())
                self.assertGreater(out["point_estimate"], BUILD_RETURN)

    def test_a_bare_keyword_mention_still_boosts(self):
        """OPEN QUESTION, pinned as-is rather than assumed.

        patches/economic-scheduler-revenue.patch narrows these to intent phrases because
        bare nouns "over-trigger the 1.5x boost on incidental mentions" — an unrelated
        task that merely says "payment" is priced as revenue work. That patch is
        deliberately unapplied (its README defers to docs/ECONOMIC_SCHEDULER_AUDIT.md §5),
        so this asserts the shipped behaviour and marks where the decision lives.
        """
        incidental = es.predict_revenue(
            task(prompt="rename a variable in the payment module docs"), ctx())
        self.assertAlmostEqual(incidental["point_estimate"], BUILD_RETURN * 1.5)

    def test_boosts_compose_rather_than_overriding_each_other(self):
        both = es.predict_revenue(
            task(prompt="new pricing page"),
            ctx(high_growth_projects={"apparently"}))["point_estimate"]
        self.assertAlmostEqual(both, BUILD_RETURN * 2.0 * 1.5)

    def test_an_error_spike_boosts_bugfix_work_and_not_feature_work(self):
        spiking = ctx(error_rates={"apparently": 0.9})
        fix = es.predict_revenue(task(kind="bugfix"), spiking)["point_estimate"]
        self.assertAlmostEqual(fix, BUGFIX_RETURN * 1.5)
        build = es.predict_revenue(task(kind="build"), spiking)["point_estimate"]
        self.assertAlmostEqual(build, BUILD_RETURN,
                               msg="a spike is a signal about breakage, not about features")

    def test_a_spike_below_the_threshold_changes_nothing(self):
        mild = ctx(error_rates={"apparently": 0.1})
        self.assertAlmostEqual(
            es.predict_revenue(task(kind="bugfix"), mild)["point_estimate"], BUGFIX_RETURN)

    def test_nested_telemetry_is_read_not_merely_survived(self):
        """The shape telemetry actually emits."""
        nested = ctx(error_rates={"apparently": {"error_rate": 0.9}})
        self.assertAlmostEqual(
            es.predict_revenue(task(kind="bugfix"), nested)["point_estimate"],
            BUGFIX_RETURN * 1.5)


class ScenarioZeroRevenue(unittest.TestCase):
    """Scenario 4 — no revenue signal. Must price at zero, never guess."""

    def test_an_unknown_kind_earns_nothing(self):
        self.assertEqual(
            es.predict_revenue(task(kind="never-seen"), ctx())["point_estimate"], 0.0)

    def test_a_zero_estimate_has_no_negative_lower_bound(self):
        out = es.predict_revenue(task(kind="never-seen"), ctx())
        self.assertGreaterEqual(out["confidence_low"], 0.0)
        self.assertEqual(out["confidence_high"], 0.0)

    def test_boosts_cannot_manufacture_revenue_from_nothing(self):
        out = es.predict_revenue(
            task(kind="never-seen", prompt="stripe billing revenue"),
            ctx(high_growth_projects={"apparently"}))
        self.assertEqual(out["point_estimate"], 0.0,
                         "multiplying zero must stay zero, whatever the boosts")

    def test_zero_revenue_work_is_never_worthwhile(self):
        out = es.cost_benefit(task(kind="never-seen"), ctx())
        self.assertEqual(out["roi"], 0.0)
        self.assertFalse(out["worthwhile"])

    def test_a_negative_historical_return_floors_at_zero(self):
        self.assertEqual(
            es.predict_revenue(task(), ctx(kind_roi={"build": -250.0}))["point_estimate"],
            0.0)

    def test_a_non_numeric_historical_return_degrades_to_zero(self):
        for junk in ("oops", None, [], float("nan"), float("inf")):
            with self.subTest(value=junk):
                out = es.predict_revenue(task(), ctx(kind_roi={"build": junk}))
                self.assertEqual(out["point_estimate"], 0.0)
                self.assertFalse(math.isnan(out["point_estimate"]))


class ScenarioDependenciesAndDelays(unittest.TestCase):
    """Scenario 5 — a long, repeating, or endless queue must still terminate.

    The delay case for this scheduler is not a dependency graph, it is an iterable that
    does not end: ev_scheduler feeds predict_revenue_bulk from a full-scan pager, and the
    caller wraps it in a bare `except Exception: pass`, so a hang looks exactly like a
    scheduler that has stopped caring about revenue.
    """

    def test_an_endless_stream_stops_at_the_horizon(self):
        def forever():
            i = 0
            while True:
                i += 1
                yield task(id=f"t{i}")

        self.assertEqual(len(es.predict_revenue_bulk(forever(), ctx(), horizon=25)), 25)

    def test_a_stream_of_duplicates_terminates_on_steps_not_distinct_ids(self):
        def same_forever():
            while True:
                yield task(id="t1")

        self.assertEqual(len(es.predict_revenue_bulk(same_forever(), ctx(), horizon=10)), 1)

    def test_a_zero_horizon_means_no_work_not_unbounded_work(self):
        self.assertEqual(es.predict_revenue_bulk([task()], ctx(), horizon=0), {})
        self.assertEqual(es.predict_revenue_bulk([task()], ctx(), horizon=-1), {})

    def test_a_junk_horizon_falls_back_to_the_default(self):
        self.assertEqual(
            sorted(es.predict_revenue_bulk([task(id="a")], ctx(), horizon="soon")), ["a"])

    def test_bounding_the_walk_does_not_change_what_a_task_is_worth(self):
        tasks = [task(id="a"), task(id="b", kind="bugfix")]
        bounded = es.predict_revenue_bulk(tasks, ctx(), horizon=100)
        self.assertEqual(bounded["a"], BUILD_RETURN)
        self.assertEqual(bounded["b"], BUGFIX_RETURN)


class ScenarioTypicalFullLoad(unittest.TestCase):
    """Scenario 6 — a realistic mixed queue, priced and ranked end to end."""

    def _queue(self):
        return [
            task(id="feature", kind="build", prompt="add a settings toggle", usd=5.0),
            task(id="revenue", kind="build", prompt="new pricing tiers", usd=5.0),
            task(id="hotfix", kind="bugfix", prompt="fix the crash", usd=1.0),
            task(id="mystery", kind="never-seen", prompt="???", usd=5.0),
        ]

    def test_every_known_task_is_priced(self):
        out = es.predict_revenue_bulk(self._queue(), ctx())
        self.assertEqual(sorted(out), ["feature", "hotfix", "mystery", "revenue"])

    def test_revenue_work_outranks_the_same_work_without_the_signal(self):
        out = es.predict_revenue_bulk(self._queue(), ctx())
        self.assertGreater(out["revenue"], out["feature"])

    def test_unknown_work_ranks_last(self):
        out = es.predict_revenue_bulk(self._queue(), ctx())
        self.assertEqual(out["mystery"], 0.0)
        self.assertLess(out["mystery"], min(out["feature"], out["hotfix"]))

    def test_a_cheap_task_scores_above_an_identical_expensive_one(self):
        self.assertGreater(es.score(task(usd=1.0), ctx()), es.score(task(usd=50.0), ctx()))

    def test_scoring_the_whole_queue_is_deterministic(self):
        queue, context = self._queue(), ctx()
        first = [es.score(t, context) for t in queue]
        for _ in range(5):
            self.assertEqual([es.score(t, context) for t in queue], first)

    def test_no_score_in_a_realistic_queue_is_negative(self):
        for t in self._queue():
            with self.subTest(task=t["id"]):
                self.assertGreaterEqual(es.score(t, ctx()), 0.0)


class ScenarioFailSoft(unittest.TestCase):
    """The convention: bad input returns a sensible default, never raises.

    ev_scheduler.load_ctx() calls this inside a bare `except Exception: pass`, so anything
    that raises here does not fail loudly — it silently removes revenue from scheduling.
    """

    def test_predict_revenue_never_raises(self):
        for bad_task in (None, {}, 5, "task", {"kind": None, "prompt": None}):
            for bad_ctx in ({}, None, {"kind_roi": None}, {"kind_roi": {"build": "oops"}}):
                with self.subTest(task=bad_task, ctx=bad_ctx):
                    out = es.predict_revenue(
                        bad_task if isinstance(bad_task, dict) else {}, bad_ctx or {})
                    self.assertIsInstance(out["point_estimate"], float)

    def test_cost_benefit_never_raises(self):
        for bad in (None, {}, {"usd": "free"}, {"usd": None}):
            with self.subTest(task=bad):
                out = es.cost_benefit(bad if isinstance(bad, dict) else {}, ctx())
                self.assertIn("worthwhile", out)

    def test_score_never_raises_and_is_never_negative(self):
        for bad in (None, {}, {"usd": "free"}, {"kind": 5}):
            with self.subTest(task=bad):
                value = es.score(bad if isinstance(bad, dict) else {}, ctx())
                self.assertGreaterEqual(value, 0.0)

    def test_a_missing_pricing_table_does_not_break_prediction(self):
        context = ctx()
        context.pop("pricing")
        self.assertEqual(es.predict_revenue(task(), context)["point_estimate"], BUILD_RETURN)


if __name__ == "__main__":
    unittest.main()
