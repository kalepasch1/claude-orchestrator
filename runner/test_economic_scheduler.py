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
    """A baseline context. Every test varies exactly one axis off this.

    `outcome_stats` and `family_outcomes` used to sit in this baseline and several tests
    varied them expecting the score to move. economic_scheduler reads NEITHER: cost comes
    off the task (`task["usd"]`), the success-rate weight comes off the task
    (`task["success_rate"]`), and the kind/family weight is a documented TODO pinned at 1.0
    ("Kind outcome weight (future: integrate with outcome_stats from ev_scheduler context)
    ... For now, neutral"). They are ev_scheduler's context keys, not this module's. Keeping
    them here made tests look like they varied a cost axis while varying nothing at all, so
    they are gone and the cost tests now set the field the module actually reads.
    """
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
        # USED TO ASSERT a +/-25% band (0.75x / 1.25x). That number was never the shipped
        # one. docs/ECONOMIC_SCHEDULER_AUDIT.md §4 records the decision: two suites
        # contradicted each other, 0.25 fixed two tests and broke six, and the band was left
        # at 20% behind ORCH_ECONOMIC_CONFIDENCE_BAND so the choice is a config change. A
        # test asserting 25% is asserting the losing side of a settled argument.
        out = es.predict_revenue(task(), ctx())
        self.assertLess(out["confidence_low"], out["point_estimate"])
        self.assertGreater(out["confidence_high"], out["point_estimate"])
        self.assertAlmostEqual(out["confidence_low"], out["point_estimate"] * 0.80, places=2)
        self.assertAlmostEqual(out["confidence_high"], out["point_estimate"] * 1.20, places=2)

    def test_the_confidence_band_width_is_configurable(self):
        # The band is read per call, not at import, which is what makes it a live config
        # knob rather than a redeploy. Pinning that here is the half of the audit's
        # recommendation a test can actually hold.
        with mock.patch.dict(os.environ, {"ORCH_ECONOMIC_CONFIDENCE_BAND": "0.25"}, clear=False):
            wide = es.predict_revenue(task(), ctx())
        self.assertAlmostEqual(wide["confidence_low"], wide["point_estimate"] * 0.75, places=2)
        self.assertAlmostEqual(wide["confidence_high"], wide["point_estimate"] * 1.25, places=2)

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
        # USED TO ASSERT only isinstance(..., float), which any number satisfies — including
        # a wrong one. The module's contract is specific: "missing revenue data returns 0
        # score, task stays queued but unprioritized", so the answer is 0.0, not merely a float.
        for bad_ctx in ({}, {"surface_returns": None}, {"surface_returns": {"build": "oops"}}):
            with self.subTest(ctx=bad_ctx):
                out = es.predict_revenue(task(), bad_ctx)
                self.assertEqual(out["point_estimate"], 0.0)
                self.assertEqual(out["confidence_low"], 0.0)


class TestCostBenefit(unittest.TestCase):
    # EVERY TEST IN THIS CLASS used to set cost via
    # ctx(outcome_stats={"apparently": {..., "avg_usd": N}}) and expect cost_benefit to
    # price the task from it. cost_benefit reads `float(task.get("usd") or 0)` and never
    # looks at ctx at all for cost, so those tests were varying an input the function does
    # not have: the "expensive" and "cheap" cases were byte-identical calls. They now set
    # the field the module actually prices from.

    def test_roi_is_revenue_over_cost(self):
        out = es.cost_benefit(task(usd=2.0), ctx())
        self.assertEqual(out["predicted_revenue"], 100.0)
        self.assertEqual(out["estimated_cost"], 2.0)
        self.assertAlmostEqual(out["roi"], 50.0)

    def test_worthwhile_requires_clearing_the_roi_threshold(self):
        # Cost set so revenue is exactly AT the threshold — must NOT qualify,
        # because the contract says strictly greater.
        cost = 100.0 / es.ROI_THRESHOLD
        self.assertFalse(es.cost_benefit(task(usd=cost), ctx())["worthwhile"])
        self.assertTrue(es.cost_benefit(task(usd=cost * 0.9), ctx())["worthwhile"])

    def test_expensive_work_is_not_worthwhile(self):
        out = es.cost_benefit(task(usd=1000.0), ctx())
        self.assertFalse(out["worthwhile"])
        self.assertLess(out["roi"], es.ROI_THRESHOLD)

    def test_free_work_is_priced_at_the_floor_rather_than_dividing_by_zero(self):
        # USED TO ASSERT roi == float("inf") for a zero-cost task. The module deliberately
        # does the opposite — "# Avoid division by zero" clamps a non-positive cost to $1
        # BEFORE dividing — so an infinite ROI is unreachable by construction, and a
        # scheduler sorting on inf would park every free task above every real one forever.
        # Asserting the clamp is asserting the decision the code documents.
        out = es.cost_benefit(task(usd=0.0), ctx())
        self.assertEqual(out["estimated_cost"], 1.0)
        self.assertEqual(out["roi"], 100.0)
        self.assertTrue(out["worthwhile"])
        for junk in (None, "", -5.0):
            with self.subTest(usd=junk):
                self.assertEqual(es.cost_benefit(task(usd=junk), ctx())["estimated_cost"], 1.0)

    def test_free_work_with_no_revenue_is_zero_roi_not_infinite(self):
        out = es.cost_benefit(task(kind="unknown", usd=0.0), ctx())
        self.assertEqual(out["roi"], 0.0)
        self.assertFalse(out["worthwhile"])

    def test_fail_soft_on_junk(self):
        out = es.cost_benefit(None, ctx())
        self.assertEqual(out["predicted_revenue"], 0.0)
        self.assertFalse(out["worthwhile"])


class TestScore(unittest.TestCase):
    def test_never_divides_by_zero(self):
        # USED TO pass a zero avg_usd through ctx["outcome_stats"], which score ignores —
        # so it was scoring an ordinary $0-field task and would have passed even if the
        # clamp were deleted. The zero now goes on the task, where the clamp reads it.
        self.assertGreater(es.score(task(usd=0.0), ctx()), 0.0)

    def test_rises_with_predicted_revenue(self):
        low = es.score(task(kind="bugfix"), ctx())
        high = es.score(task(kind="build"), ctx())
        self.assertGreater(high, low)

    def test_falls_as_cost_rises(self):
        # USED TO vary cost through ctx["outcome_stats"]["apparently"]["avg_usd"], which
        # score does not read: both calls were identical, so `assertLess` compared a number
        # with itself and the "cost lowers the score" property was never tested at all.
        cheap = es.score(task(usd=1.0), ctx())
        dear = es.score(task(usd=50.0), ctx())
        self.assertLess(dear, cheap)
        self.assertAlmostEqual(dear, cheap / 50.0)

    def test_a_low_success_rate_is_weighted_down(self):
        # USED TO ASSERT that ctx["family_outcomes"] dragged a never-merging kind's score
        # down. There is no family weighting: score's kind term is a documented TODO pinned
        # at 1.0 ("For now, neutral (1.0)"), so that test varied a key nothing reads.
        # SUBSTITUTED for the weighting that does exist and does the same job — the
        # per-task success rate, score's `s *= (1.0 + success_rate)` term.
        unreliable = es.score(task(success_rate=0.1), ctx())
        reliable = es.score(task(success_rate=0.9), ctx())
        self.assertLess(unreliable, reliable)
        self.assertAlmostEqual(unreliable, reliable * (1.1 / 1.9))

    def test_the_success_weight_has_a_floor_so_a_task_is_never_zeroed_out(self):
        # USED TO ASSERT a floor on the (nonexistent) family weight, via a ctx key nothing
        # reads — so `assertGreater(score, 0)` held for reasons unrelated to any floor.
        # SUBSTITUTED for the real floor: the success term is (1 + rate), never below 1.0,
        # so it can only ever lift a task above its bare ROI, never erase it.
        bare_roi = 100.0 / 4.0
        for rate in (0.0, 0.01, 0.5, 1.0):
            with self.subTest(success_rate=rate):
                s = es.score(task(usd=4.0, success_rate=rate), ctx())
                self.assertGreaterEqual(s, bare_roi)
                self.assertGreater(s, 0.0)

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
    """apply_routing is the only function here that writes, and it is gated on ENABLED.

    EVERY TEST BELOW used `es.TOP_REVENUE_TASKS`, a constant that does not exist — master
    calls it REVENUE_CRITICAL_LANE_SIZE (audit §4 logs the same rename). Two failed on the
    AttributeError outright; the rest failed or passed for a second, quieter reason: none
    of them enabled the module. apply_routing short-circuits to {"routed": 0} while
    ORCH_ECONOMIC_SCHEDULER_ENABLED is off, which is the default, so "an empty queue routes
    nothing" was green without a single line of routing logic ever running. Each test now
    patches ENABLED, which is what makes it a test of routing rather than of the kill switch.
    """

    def setUp(self):
        enabled = mock.patch.object(es, "ENABLED", True)
        enabled.start()
        self.addCleanup(enabled.stop)

    def test_routes_only_the_top_n(self):
        scored = [(float(100 - i), {"id": f"t{i}"}) for i in range(es.REVENUE_CRITICAL_LANE_SIZE + 15)]
        with mock.patch.object(es.db, "update") as upd:
            out = es.apply_routing(scored)
        self.assertEqual(out["routed"], es.REVENUE_CRITICAL_LANE_SIZE)
        self.assertEqual(upd.call_count, es.REVENUE_CRITICAL_LANE_SIZE)
        # The highest scores are the ones that get the lane, not the first N seen.
        routed_ids = [call.args[1]["id"] for call in upd.call_args_list]
        self.assertEqual(routed_ids, [f"t{i}" for i in range(es.REVENUE_CRITICAL_LANE_SIZE)])

    def test_the_kill_switch_stops_every_write(self):
        # The half of the old `test_an_empty_queue_routes_nothing` that was accidentally
        # being tested — now asserted deliberately, with a non-empty queue so it means
        # something.
        with mock.patch.object(es, "ENABLED", False), \
             mock.patch.object(es.db, "update") as upd:
            out = es.apply_routing([(10.0, {"id": "t1"})])
        self.assertEqual(out["routed"], 0)
        upd.assert_not_called()

    def test_annotates_the_revenue_critical_lane(self):
        with mock.patch.object(es.db, "update") as upd:
            es.apply_routing([(10.0, {"id": "t1"})])
        table, where, values = upd.call_args.args
        self.assertEqual(table, "tasks")
        self.assertEqual(where, {"id": "t1"})
        self.assertEqual(values["lane"], "revenue-critical")
        self.assertEqual(values["economic_score"], 10.0)

    def test_an_empty_queue_routes_nothing(self):
        with mock.patch.object(es.db, "update") as upd:
            out = es.apply_routing([])
        self.assertEqual(out["routed"], 0)
        upd.assert_not_called()

    def test_skips_rows_with_no_id_instead_of_writing_garbage(self):
        with mock.patch.object(es.db, "update") as upd:
            out = es.apply_routing([(10.0, {}), (9.0, None), (8.0, {"id": "ok"})])
        self.assertEqual(out["routed"], 1)
        self.assertEqual(upd.call_count, 1)
        self.assertEqual(upd.call_args.args[1], {"id": "ok"})

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
        self.assertEqual(calls["n"], 3, "the failing row must not consume the later ones")


class TestBulkAndConfig(unittest.TestCase):
    def test_bulk_prediction_covers_every_task(self):
        tasks = [task(id="a"), task(id="b", kind="bugfix"), task(id="c", kind="unknown")]
        out = es.predict_revenue_bulk(tasks, ctx())
        self.assertEqual(out, {"a": 100.0, "b": 40.0, "c": 0.0},
                         "the bulk map must carry each task's own point estimate")

    def test_bulk_prediction_fail_soft_on_junk(self):
        # USED TO ASSERT `assertIsNotNone(...)`, which a Mock, a string or a stray truthy
        # object would all satisfy — it could not tell "returned an empty map" from
        # "returned something". The contract is an empty dict: no ids in, no ids out.
        for bad in (None, [], [None], [None, 7, "x"]):
            with self.subTest(tasks=bad):
                self.assertEqual(es.predict_revenue_bulk(bad, ctx()), {})

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
        # USED TO scan `dir(es)` for names starting with "ORCH_". No module ATTRIBUTE is
        # spelled that way — the ORCH_ names are env-var strings passed to os.environ.get,
        # so the list was always empty and the loop body never executed once. Scan the
        # source for the env keys the module actually reads instead.
        import re

        source = open(es.__file__).read()
        keys = sorted(set(re.findall(r"os\.environ\.get\(\s*[\"']([A-Za-z0-9_]+)[\"']", source)))
        self.assertTrue(keys, "the scan found no env reads at all — the regex has rotted")
        self.assertIn("ORCH_ECONOMIC_SCHEDULER_ENABLED", keys,
                      "the kill switch must stay a readable env knob")
        for name in keys:
            with self.subTest(env=name):
                self.assertTrue(name.startswith("ORCH_"),
                                f"{name} is fleet config and must carry the ORCH_ prefix")
                self.assertNotRegex(name, r"PASSWORD|TOKEN|SECRET|KEY")

    def test_thresholds_are_sane(self):
        # USED TO read es.TOP_REVENUE_TASKS, which has never existed on this module; the
        # lane-size constant is REVENUE_CRITICAL_LANE_SIZE (audit §4).
        self.assertGreater(es.ROI_THRESHOLD, 1.0, "an ROI threshold at or below 1 pursues losing work")
        self.assertGreater(es.REVENUE_CRITICAL_LANE_SIZE, 0,
                           "a zero-size fast lane routes nothing, silently")


class TestPlanHorizonTerminates(unittest.TestCase):
    """The revenue sweep must finish in a bounded number of steps.

    Before the plan horizon, predict_revenue_bulk walked whatever iterable it was handed to
    exhaustion. Handed one that never exhausts — a generator over a queue that refills, the
    shape ev_scheduler.load_ctx() feeds it from a full-scan pager — it never returned, and it
    never returned quietly: the caller wraps it in `except Exception: pass`, so a hang there
    looks exactly like a scheduler that has stopped caring about revenue.

    These tests are the reproduction. They pass an unbounded source and assert the call comes
    back at all, which is the property the fix adds.
    """

    def test_an_endless_task_stream_still_terminates(self):
        def forever():
            i = 0
            while True:
                i += 1
                yield task(id=f"t{i}")

        out = es.predict_revenue_bulk(forever(), ctx(), horizon=25)
        self.assertEqual(len(out), 25, "the walk must stop at the horizon, not at exhaustion")

    def test_a_repeating_stream_terminates_on_steps_not_distinct_ids(self):
        # The `seen` set alone is not a bound: an endless stream of the SAME id yields no new
        # results forever. Steps are what must be counted.
        def same_task_forever():
            while True:
                yield task(id="t1")

        out = es.predict_revenue_bulk(same_task_forever(), ctx(), horizon=10)
        self.assertEqual(len(out), 1, "a repeated task is scored once")

    def test_duplicate_tasks_are_scored_once(self):
        calls = {"n": 0}
        real = es.predict_revenue

        def counting(t, c):
            calls["n"] += 1
            return real(t, c)

        tasks = [task(id="a"), task(id="a"), task(id="b"), task(id="a")]
        with mock.patch.object(es, "predict_revenue", side_effect=counting):
            out = es.predict_revenue_bulk(tasks, ctx())
        self.assertEqual(sorted(out), ["a", "b"])
        self.assertEqual(calls["n"], 2, "duplicates must not be re-scored")

    def test_the_horizon_is_configurable_and_defaults_positive(self):
        self.assertGreater(es.PLAN_HORIZON, 0, "a non-positive default horizon disables scoring")
        import importlib

        with mock.patch.dict(os.environ, {"ORCH_ECONOMIC_PLAN_HORIZON": "7"}, clear=True):
            self.assertEqual(importlib.reload(es).PLAN_HORIZON, 7)
        importlib.reload(es)  # restore ambient module state for other tests

    def test_a_zero_horizon_means_no_work_not_unbounded_work(self):
        self.assertEqual(es.predict_revenue_bulk([task()], ctx(), horizon=0), {})
        self.assertEqual(es.predict_revenue_bulk([task()], ctx(), horizon=-1), {})

    def test_a_junk_horizon_falls_back_to_the_default(self):
        out = es.predict_revenue_bulk([task(id="a")], ctx(), horizon="not-a-number")
        self.assertEqual(sorted(out), ["a"])

    def test_the_plan_is_still_valid_within_the_bound(self):
        # Bounding the walk must not change what the scored tasks are worth.
        tasks = [task(id="a"), task(id="b", kind="bugfix")]
        bounded = es.predict_revenue_bulk(tasks, ctx(), horizon=100)
        self.assertEqual(bounded["a"], es.predict_revenue(task(id="a"), ctx())["point_estimate"])
        self.assertEqual(bounded["b"],
                         es.predict_revenue(task(id="b", kind="bugfix"), ctx())["point_estimate"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
