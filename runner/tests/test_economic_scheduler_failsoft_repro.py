#!/usr/bin/env python3
"""Isolated reproduction of the 'economic-scheduler-revenue' failure. ROOT CAUSE BELOW.

WHAT THE ORIGINAL TASK CLAIMED
------------------------------
The parent task was recorded as failing with `error_max_turns` and was filed as an
"infinite planning loop or missing dependency" in the economic scheduler.

WHAT IS ACTUALLY THERE
----------------------
There is no infinite loop. `runner/economic_scheduler.py` imports only stdlib plus `db`
and `revenue_attribution`; nothing in it loops over anything but a finite `scored` list,
and `python3 -m compileall -q runner` is clean, so there is also no missing dependency —
the repo is stdlib Python with no build step (see BUILD-TEST-LOG-economic-scheduler-revenue.md).
`max_turns` was the AGENT exhausting its turn budget, not the module failing to terminate.
It exhausted that budget because `runner/test_economic_scheduler.py` is 15/37 red and, per
docs/ECONOMIC_SCHEDULER_AUDIT.md §4, most of those failures encode an unresolved product
argument (the +/-20% vs +/-25% confidence band) that no agent can settle by patching. Each
attempt re-derived the same dead end and burned its turns.

THREE of those fifteen are NOT the band argument. They are the module's own documented
fail-soft contract being violated by input shapes that occur in production:

  1. `app_signals` / `error_rates` keyed to a NESTED DICT — `{"apparently": {"error_rate": 0.9}}`
     is the shape the telemetry side actually produces. `predict_revenue` does
     `float(...get(project, 0))` on it and raises TypeError.
  2. `surface_returns` / `kind_roi` carrying a NON-NUMERIC value — `{"build": "oops"}`.
     Same call, ValueError.
  3. Either of the above inside `cost_benefit`/`score`, which delegate to `predict_revenue`.

WHY THIS WAS INVISIBLE, i.e. the "missing dependency" the task sensed
--------------------------------------------------------------------
`ev_scheduler.load_ctx()` calls into the economic signals inside a bare
`except Exception: pass`. So the raise never surfaced as an error anywhere: it silently
dropped economic_signals out of the scheduling context, and the queue went on being
ordered as though revenue prediction did not exist. The dependency was not missing from
the import graph; it was being swallowed at runtime.

The module's docstring and its own restored guard both state the contract explicitly —
"Every read is fail-soft", "missing revenue data returns 0 score". Raising is a bug on
its own merits, independent of the band decision, which is why the audit (§6.3)
recommends fixing exactly these three as their own change.

STATUS OF THIS FILE
-------------------
FIXED. These tests were committed on the diagnose branch as `@unittest.expectedFailure`
to pin the defect; the accompanying change to `economic_scheduler._as_float` makes every
one of them pass, so the decorators are gone and they are now live regression guards.
A nested telemetry dict is READ rather than merely survived, so a real error-rate spike
still boosts bugfix work; a non-numeric historical return degrades to 0.0 as the module
docstring has always promised.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import economic_scheduler as es


def ctx(**over):
    """Baseline context matching runner/test_economic_scheduler.py's helper."""
    base = {
        "surface_returns": {"build": 100.0, "bugfix": 40.0},
        "high_growth_projects": set(),
        "app_signals": {},
    }
    base.update(over)
    return base


def task(**over):
    base = {"id": "t1", "project": "apparently", "kind": "build", "prompt": "add a widget"}
    base.update(over)
    return base


class NestedSignalReproTest(unittest.TestCase):
    """Defect 1: a nested telemetry dict raises instead of degrading to 'no signal'."""

    def test_the_raw_shape_is_what_blows_up(self):
        """Demonstrates the mechanism directly: this is the exact expression in the module."""
        with self.assertRaises(TypeError):
            float({"error_rate": 0.9})

    def test_a_nested_error_rate_dict_must_not_raise(self):
        out = es.predict_revenue(task(kind="bugfix"),
                                 ctx(app_signals={"apparently": {"error_rate": 0.1}}))
        self.assertIsInstance(out["point_estimate"], float)

    def test_a_nested_spike_still_boosts_bugfix_work(self):
        """The nested shape must be READ, not just survived: 0.9 > 0.3 is a spike."""
        spiking = es.predict_revenue(task(kind="bugfix"),
                                     ctx(app_signals={"apparently": {"error_rate": 0.9}}))
        calm = es.predict_revenue(task(kind="bugfix"), ctx())
        self.assertGreater(spiking["point_estimate"], calm["point_estimate"])


class NonNumericSignalReproTest(unittest.TestCase):
    """Defect 2: a non-numeric historical return raises instead of scoring 0."""

    def test_a_garbage_kind_return_must_not_raise(self):
        out = es.predict_revenue(task(), ctx(surface_returns={"build": "oops"}))
        self.assertIsInstance(out["point_estimate"], float)

    def test_a_garbage_kind_return_scores_zero_not_a_guess(self):
        out = es.predict_revenue(task(), ctx(surface_returns={"build": "oops"}))
        self.assertEqual(out["point_estimate"], 0.0)


class DownstreamCallersReproTest(unittest.TestCase):
    """Defect 3: everything that delegates to predict_revenue inherits the raise."""

    def test_cost_benefit_survives_a_malformed_context(self):
        out = es.cost_benefit(task(), ctx(surface_returns={"build": "oops"}))
        self.assertIsInstance(out["predicted_revenue"], float)

    def test_score_survives_a_malformed_context(self):
        self.assertIsInstance(
            es.score(task(kind="bugfix"),
                     ctx(app_signals={"apparently": {"error_rate": 0.9}})),
            float)


class ContractStillHoldsWhereItAlreadyWorkedTest(unittest.TestCase):
    """Guard rail: the fix must not disturb the shapes that already behave."""

    def test_well_formed_numeric_signals_are_unaffected(self):
        self.assertEqual(es.predict_revenue(task(), ctx())["point_estimate"], 100.0)

    def test_a_flat_numeric_error_rate_still_reads(self):
        spiking = es.predict_revenue(task(kind="bugfix"),
                                     ctx(app_signals={"apparently": 0.9}))
        calm = es.predict_revenue(task(kind="bugfix"), ctx())
        self.assertGreater(spiking["point_estimate"], calm["point_estimate"])

    def test_non_dict_task_still_returns_zero(self):
        self.assertEqual(es.predict_revenue(None, ctx())["point_estimate"], 0.0)

    def test_empty_and_none_contexts_are_tolerated(self):
        for bad in ({}, {"surface_returns": None}):
            with self.subTest(ctx=bad):
                self.assertIsInstance(
                    es.predict_revenue(task(), bad)["point_estimate"], float)


if __name__ == "__main__":
    unittest.main()
