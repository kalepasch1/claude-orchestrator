"""economic_scheduler — the revenue fast-lane router, under test.

`runner/economic_scheduler.py` decides which queued work is revenue-critical and
routes it to a fast lane. It shipped WITHOUT this file, which is the worst place
in the fleet to have no test: the module is a pure scoring function whose output
reorders the whole queue, and a silent regression would not fail anything — it
would just quietly stop prioritising the work that makes money.

Everything here is pure. `db` is stubbed for the one function that writes
(`apply_routing`), so no test touches a real database.

The properties that actually matter, and are asserted below:
  * DETERMINISM — the docstring promises same task+ctx → same score. A scheduler
    that reorders the queue differently on each pass is not a scheduler.
  * FAIL-SOFT — the CLAUDE.md convention: bad input returns a sensible default,
    never raises. A scheduler that throws on one malformed row stops the fleet.
  * MONOTONICITY — each documented boost must actually raise the number. A
    multiplier that silently does nothing is the `assertEcpCounterparty` shape:
    the name promises a computation that no longer happens.
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

RUNNER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RUNNER_DIR not in sys.path:
    sys.path.insert(0, RUNNER_DIR)
RUNNER_PKG = os.path.join(RUNNER_DIR, "runner")
if RUNNER_PKG not in sys.path:
    sys.path.insert(0, RUNNER_PKG)

import economic_scheduler as es  # noqa: E402


def ctx(**over):
    """A baseline context. Every test varies exactly one axis off this."""
    base = {
        "surface_returns": {"build": 100.0, "bugfix": 40.0},
        "high_growth_projects": set(),
        "app_signals": {},
        "outcome_stats": {"apparently": {"success_rate": 0.8, "avg_usd": 2.0}},
        "family_outcomes": {},
    }
    base.update(over)
    return base


def task(**over):
    base = {"id": "t1", "project": "apparently", "kind": "build", "prompt": "add a widget"}
    base.update(over)
    return base


class TestPredictRevenue(unittest.TestCase):
    def test_uses_the_kinds_historical_return_as_the_base(self):
        out = es.predict_revenue(task(), ctx())
        self.assertEqual(out["point_estimate"], 100.0)

    def test_unknown_kind_earns_nothing_rather_than_guessing(self):
        out = es.predict_revenue(task(kind="never-seen"), ctx())
        self.assertEqual(out["point_estimate"], 0.0)

    def test_high_growth_project_doubles_the_estimate(self):
        plain = es.predict_revenue(task(), ctx())["point_estimate"]
        boosted = es.predict_revenue(
            task(), ctx(high_growth_projects={"apparently"})
        )["point_estimate"]
        self.assertAlmostEqual(boosted, plain * 2.0)

    def test_a_revenue_keyword_in_the_prompt_boosts_by_half(self):
        plain = es.predict_revenue(task(), ctx())["point_estimate"]
        boosted = es.predict_revenue(
            task(prompt="fix the stripe billing flow"), ctx()
        )["point_estimate"]
        self.assertAlmostEqual(boosted, plain * 1.5)

    def test_every_declared_revenue_keyword_actually_fires(self):
        # A keyword list nothing reads is the classic dead constant.
        plain = es.predict_revenue(task(), ctx())["point_estimate"]
        for keyword in es.REVENUE_KEYWORDS:
            with self.subTest(keyword=keyword):
                out = es.predict_revenue(task(prompt=f"work on {keyword} things"), ctx())
                self.assertGreater(out["point_estimate"], plain)

    def test_an_error_spike_boosts_bugfix_work_only(self):
        spiking = ctx(app_signals={"apparently": {"error_rate": 0.9}})
        fix = es.predict_revenue(task(kind="bugfix"), spiking)["point_estimate"]
        calm = es.predict_revenue(task(kind="bugfix"), ctx())["point_estimate"]
        self.assertAlmostEqual(fix, calm * 1.5)

        # A build during the same spike is NOT boosted — the spike is a signal
        # about broken things, not about features.
        build_spike = es.predict_revenue(task(kind="build"), spiking)["point_estimate"]
        build_calm = es.predict_revenue(task(kind="build"), ctx())["point_estimate"]
        self.assertAlmostEqual(build_spike, build_calm)

    def test_an_error_rate_below_the_threshold_does_not_boost(self):
        mild = ctx(app_signals={"apparently": {"error_rate": 0.1}})
        self.assertAlmostEqual(
            es.predict_revenue(task(kind="bugfix"), mild)["point_estimate"],
            es.predict_revenue(task(kind="bugfix"), ctx())["point_estimate"],
        )

    def test_boosts_compose_rather_than_overriding_each_other(self):
        both = es.predict_revenue(
            task(prompt="new pricing page"), ctx(high_growth_projects={"apparently"})
        )["point_estimate"]
        self.assertAlmostEqual(both, 100.0 * 2.0 * 1.5)

    def test_the_confidence_band_brackets_the_point_estimate(self):
        out = es.predict_revenue(task(), ctx())
        self.assertLess(out["confidence_low"], out["point_estimate"])
        self.assertGreater(out["confidence_high"], out["point_estimate"])
        self.assertAlmostEqual(out["confidence_low"], out["point_estimate"] * 0.75, places=2)
        self.assertAlmostEqual(out["confidence_high"], out["point_estimate"] * 1.25, places=2)

    def test_the_band_never_goes_negative(self):
        out = es.predict_revenue(task(kind="unknown"), ctx())
        self.assertGreaterEqual(out["confidence_low"], 0.0)

    def test_is_deterministic(self):
        t, c = task(prompt="billing"), ctx(high_growth_projects={"apparently"})
        first = es.predict_revenue(t, c)
        for _ in range(5):
            self.assertEqual(es.predict_revenue(t, c), first)

    def test_fail_soft_on_junk_input(self):
        for bad_task in (None, {}, {"project": None, "kind": None, "prompt": None}):
            with self.subTest(task=bad_task):
                out = es.predict_revenue(bad_task, ctx())
                self.assertEqual(out["point_estimate"], 0.0)

    def test_fail_soft_on_a_malformed_context(self):
        for bad_ctx in ({}, {"surface_returns": None}, {"surface_returns": {"build": "oops"}}):
            with self.subTest(ctx=bad_ctx):
                out = es.predict_revenue(task(), bad_ctx)
                self.assertIsInstance(out["point_estimate"], float)


class TestCostBenefit(unittest.TestCase):
    def test_roi_is_revenue_over_cost(self):
        out = es.cost_benefit(task(), ctx())
        self.assertEqual(out["predicted_revenue"], 100.0)
        self.assertEqual(out["estimated_cost"], 2.0)
        self.assertAlmostEqual(out["roi"], 50.0)

    def test_worthwhile_requires_clearing_the_roi_threshold(self):
        # Cost set so revenue is exactly AT the threshold — must NOT qualify,
        # because the contract says strictly greater.
        cost = 100.0 / es.ROI_THRESHOLD
        at_threshold = ctx(outcome_stats={"apparently": {"success_rate": 0.8, "avg_usd": cost}})
        self.assertFalse(es.cost_benefit(task(), at_threshold)["worthwhile"])

        below = ctx(outcome_stats={"apparently": {"success_rate": 0.8, "avg_usd": cost * 0.9}})
        self.assertTrue(es.cost_benefit(task(), below)["worthwhile"])

    def test_expensive_work_is_not_worthwhile(self):
        pricey = ctx(outcome_stats={"apparently": {"success_rate": 0.8, "avg_usd": 1000.0}})
        out = es.cost_benefit(task(), pricey)
        self.assertFalse(out["worthwhile"])
        self.assertLess(out["roi"], es.ROI_THRESHOLD)

    def test_free_work_with_revenue_is_infinite_roi_not_a_crash(self):
        free = ctx(outcome_stats={"apparently": {"success_rate": 0.8, "avg_usd": 0.0}})
        out = es.cost_benefit(task(), free)
        self.assertEqual(out["roi"], float("inf"))
        self.assertTrue(out["worthwhile"])

    def test_free_work_with_no_revenue_is_zero_roi_not_infinite(self):
        free = ctx(outcome_stats={"apparently": {"success_rate": 0.8, "avg_usd": 0.0}})
        out = es.cost_benefit(task(kind="unknown"), free)
        self.assertEqual(out["roi"], 0.0)
        self.assertFalse(out["worthwhile"])

    def test_fail_soft_on_junk(self):
        out = es.cost_benefit(None, ctx())
        self.assertEqual(out["predicted_revenue"], 0.0)
        self.assertFalse(out["worthwhile"])


class TestScore(unittest.TestCase):
    def test_never_divides_by_zero(self):
        free = ctx(outcome_stats={"apparently": {"success_rate": 0.8, "avg_usd": 0.0}})
        self.assertGreater(es.score(task(), free), 0.0)

    def test_rises_with_predicted_revenue(self):
        low = es.score(task(kind="bugfix"), ctx())
        high = es.score(task(kind="build"), ctx())
        self.assertGreater(high, low)

    def test_falls_as_cost_rises(self):
        cheap = es.score(task(), ctx())
        dear = es.score(
            task(), ctx(outcome_stats={"apparently": {"success_rate": 0.8, "avg_usd": 50.0}})
        )
        self.assertLess(dear, cheap)

    def test_a_family_that_never_merges_is_weighted_down(self):
        bad_family = ctx(
            family_outcomes={"build": {"total": 10, "merged_green": 1, "retries": 20, "rejected": 5}}
        )
        self.assertLess(es.score(task(), bad_family), es.score(task(), ctx()))

    def test_the_kind_weight_has_a_floor_so_a_family_is_never_zeroed_out(self):
        worst = ctx(
            family_outcomes={"build": {"total": 10, "merged_green": 0, "retries": 99, "rejected": 10}}
        )
        self.assertGreater(es.score(task(), worst), 0.0)

    def test_is_never_negative(self):
        for t in (task(kind="unknown"), task(prompt=""), task(project="nope")):
            with self.subTest(task=t):
                self.assertGreaterEqual(es.score(t, ctx()), 0.0)

    def test_is_deterministic(self):
        t, c = task(prompt="payment"), ctx()
        first = es.score(t, c)
        for _ in range(5):
            self.assertEqual(es.score(t, c), first)

    def test_fail_soft_on_junk(self):
        self.assertEqual(es.score(None, ctx()), 0.0)
        self.assertEqual(es.score({}, {}), 0.0)


class TestApplyRouting(unittest.TestCase):
    def test_routes_only_the_top_n(self):
        scored = [(float(100 - i), {"id": f"t{i}"}) for i in range(es.TOP_REVENUE_TASKS + 15)]
        with mock.patch.object(es.db, "update") as upd:
            out = es.apply_routing(scored)
        self.assertEqual(out["routed"], es.TOP_REVENUE_TASKS)
        self.assertEqual(upd.call_count, es.TOP_REVENUE_TASKS)

    def test_annotates_the_revenue_critical_lane(self):
        with mock.patch.object(es.db, "update") as upd:
            es.apply_routing([(10.0, {"id": "t1"})])
        _table, _where, values = upd.call_args[0]
        self.assertEqual(values["lane"], "revenue-critical")

    def test_an_empty_queue_routes_nothing(self):
        out = es.apply_routing([])
        self.assertEqual(out["routed"], 0)

    def test_skips_rows_with_no_id_instead_of_writing_garbage(self):
        with mock.patch.object(es.db, "update") as upd:
            out = es.apply_routing([(10.0, {}), (9.0, None), (8.0, {"id": "ok"})])
        self.assertEqual(out["routed"], 1)
        self.assertEqual(upd.call_count, 1)

    def test_one_failing_write_does_not_abort_the_rest(self):
        # Fail-soft: a single bad row must not stop the fleet being prioritised.
        calls = {"n": 0}

        def flaky(*_a, **_k):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("db blip")

        with mock.patch.object(es.db, "update", side_effect=flaky):
            out = es.apply_routing([(3.0, {"id": "a"}), (2.0, {"id": "b"}), (1.0, {"id": "c"})])
        self.assertEqual(out["routed"], 2)


class TestBulkAndConfig(unittest.TestCase):
    def test_bulk_prediction_covers_every_task(self):
        tasks = [task(id="a"), task(id="b", kind="bugfix"), task(id="c", kind="unknown")]
        out = es.predict_revenue_bulk(tasks, ctx())
        self.assertEqual(len(out), len(tasks))

    def test_bulk_prediction_fail_soft_on_junk(self):
        for bad in (None, [], [None]):
            with self.subTest(tasks=bad):
                self.assertIsNotNone(es.predict_revenue_bulk(bad, ctx()))

    def test_the_scheduler_is_off_by_default(self):
        # A job that reorders the whole queue must not switch itself on. ENABLED
        # is read at import, so re-import under a cleared env to observe the
        # real default rather than whatever this shell happens to export.
        import importlib

        with mock.patch.dict(os.environ, {}, clear=True):
            reloaded = importlib.reload(es)
            self.assertFalse(reloaded.ENABLED, "the economic scheduler must default to OFF")

        for truthy in ("true", "1", "yes", "TRUE"):
            with mock.patch.dict(os.environ, {"ORCH_ECONOMIC_SCHEDULER_ENABLED": truthy}, clear=True):
                self.assertTrue(importlib.reload(es).ENABLED, f"{truthy} should enable it")

        for falsy in ("false", "0", "no", ""):
            with mock.patch.dict(os.environ, {"ORCH_ECONOMIC_SCHEDULER_ENABLED": falsy}, clear=True):
                self.assertFalse(importlib.reload(es).ENABLED, f"{falsy} should leave it off")

        importlib.reload(es)  # restore the ambient module state for other tests

    def test_config_is_orch_prefixed_and_secret_free(self):
        names = [n for n in dir(es) if n.startswith("ORCH_")]
        for name in names:
            self.assertNotRegex(name, r"PASSWORD|TOKEN|SECRET|KEY")

    def test_thresholds_are_sane(self):
        self.assertGreater(es.ROI_THRESHOLD, 1.0, "an ROI threshold at or below 1 pursues losing work")
        self.assertGreater(es.TOP_REVENUE_TASKS, 0)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
