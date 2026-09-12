#!/usr/bin/env python3
"""Development-fabric observability, SLOs and rollout.

The load-bearing property under test is ZERO FABRICATED POINTS: every metric reports
UNKNOWN rather than 0 when it has no basis. A zero improvements/day and a no-data
improvements/day mean opposite things, and rendering them the same is the mechanism by
which a stalled fleet looks calm.

The second property is that DELIVERY means DEPLOYED_AND_VERIFIED. DONE and MERGED are
task bookkeeping, and counting them as delivery is how "it merged" became "it shipped".

Proof: python3 -m pytest runner/tests/test_fabric_observability.py -q
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fabric_observability as fo  # noqa: E402

MIN = fo.SLO_MIN_SAMPLES


def _task(state="DEPLOYED_AND_VERIFIED", **over):
    row = {"state": state, "artifact_commit": "abc1234", "project": "beethoven",
           "host": "mac-studio", "cost_usd": 1.0}
    row.update(over)
    return row


def _many(n, **over):
    return [_task(**over) for _ in range(n)]


class TestZeroFabricatedPoints(unittest.TestCase):
    def test_no_data_is_unknown_not_zero(self):
        view = fo.evaluate()
        for name, metric in view["metrics"].items():
            self.assertIsNone(metric["value"], f"{name} invented a value from no data")
            self.assertIsNone(metric["ok"], f"{name} rendered a verdict from no data")

    def test_a_thin_sample_is_unknown(self):
        metric = fo.phantom_rate(_many(MIN - 1))
        self.assertTrue(metric.unknown)
        self.assertIn("UNKNOWN", metric["reason"])

    def test_unknown_never_alerts(self):
        self.assertEqual(fo.alerts(fo.evaluate()), [])

    def test_unknown_is_listed_separately_from_breached(self):
        view = fo.evaluate()
        self.assertEqual(view["breached"], [])
        self.assertEqual(sorted(view["unknown"]), sorted(fo.METRICS))

    def test_percentile_of_nothing_is_none_not_zero(self):
        self.assertIsNone(fo.percentile([], 95))
        self.assertIsNone(fo.percentile(None, 50))

    def test_cost_with_no_deliveries_is_undefined_not_zero_or_infinite(self):
        metric = fo.cost_per_verified_change(_many(10, state="MERGED"))
        self.assertIsNone(metric["value"])
        self.assertIn("undefined", metric["reason"])

    def test_a_metric_that_raises_degrades_to_unknown_not_a_dead_view(self):
        view = fo.evaluate(tasks=[{"state": "DEPLOYED_AND_VERIFIED"}], hosts="not-iterable")
        self.assertIn("host_generation_drift", view["metrics"])
        self.assertIsNone(view["metrics"]["host_generation_drift"]["ok"])
        self.assertIn("verified_per_day", view["metrics"])


class TestDeliveryMeansDeployedAndVerified(unittest.TestCase):
    def test_done_and_merged_are_not_delivery(self):
        for state in fo.NON_DELIVERY_STATES:
            self.assertFalse(fo._is_delivered({"state": state}), state)

    def test_deployed_and_verified_is_delivery(self):
        self.assertTrue(fo._is_delivered({"state": "DEPLOYED_AND_VERIFIED"}))

    def test_merged_work_does_not_count_toward_improvements_per_day(self):
        metric = fo.verified_per_day(_many(10, state="MERGED"), window_days=1)
        self.assertEqual(metric["value"], 0.0)
        self.assertIs(metric["ok"], False)

    def test_delivered_work_counts(self):
        self.assertEqual(fo.verified_per_day(_many(6), window_days=2)["value"], 3.0)

    def test_a_zero_or_negative_window_is_unknown_not_a_division_error(self):
        self.assertTrue(fo.verified_per_day(_many(6), window_days=0).unknown)
        self.assertTrue(fo.verified_per_day(_many(6), window_days=-1).unknown)


class TestLatency(unittest.TestCase):
    def _rows(self, seconds):
        return [_task(objective_to_verified_s=s) for s in seconds]

    def test_p50_and_p95(self):
        p50, p95 = fo.objective_to_verified(self._rows([10, 20, 30, 40, 1000]))
        self.assertEqual(p50["value"], 30)
        self.assertEqual(p95["value"], 1000)

    def test_duration_is_derived_from_timestamps_when_absent(self):
        rows = [_task(objective_at=0, verified_at=s) for s in (10, 20, 30, 40, 50)]
        p50, _ = fo.objective_to_verified(rows)
        self.assertEqual(p50["value"], 30)

    def test_undelivered_work_does_not_improve_the_number(self):
        rows = self._rows([10, 20, 30, 40, 1000]) + \
            [_task(state="MERGED", objective_to_verified_s=1)] * 10
        p50, _ = fo.objective_to_verified(rows)
        self.assertEqual(p50["value"], 30, "stuck work was allowed to flatter latency")

    def test_thin_sample_is_unknown(self):
        p50, p95 = fo.objective_to_verified(self._rows([10]))
        self.assertTrue(p50.unknown)
        self.assertTrue(p95.unknown)

    def test_p95_breach_is_flagged(self):
        rows = self._rows([fo.SLO_OBJECTIVE_TO_VERIFIED_P95_S * 3] * 6)
        _, p95 = fo.objective_to_verified(rows)
        self.assertIs(p95["ok"], False)


class TestFalseShippedAndPhantom(unittest.TestCase):
    def test_false_shipped_counts_claims_that_did_not_deliver(self):
        rows = ([_task(state="MERGED", claimed_shipped=True)] * 2 +
                [_task(claimed_shipped=True)] * 8)
        self.assertEqual(fo.false_shipped_rate(rows)["value"], 0.2)

    def test_false_shipped_ignores_work_that_never_claimed(self):
        rows = [_task(state="MERGED")] * 50 + [_task(claimed_shipped=True)] * 5
        self.assertEqual(fo.false_shipped_rate(rows)["value"], 0.0)

    def test_false_shipped_drills_down_by_host(self):
        rows = ([_task(state="MERGED", claimed_shipped=True, host="mac-mini")] +
                [_task(claimed_shipped=True)] * 9)
        self.assertEqual(fo.false_shipped_rate(rows)["drill"]["by_host"], {"mac-mini": 1})

    def test_phantom_is_a_closure_with_no_artifact(self):
        rows = [_task(state="DONE", artifact_commit=None)] * 2 + [_task(state="DONE")] * 8
        self.assertEqual(fo.phantom_rate(rows)["value"], 0.2)

    def test_phantom_accepts_either_artifact_field(self):
        rows = [_task(state="DONE", artifact_commit=None, artifact_sha="deadbee")] * 10
        self.assertEqual(fo.phantom_rate(rows)["value"], 0.0)

    def test_phantom_breach_is_flagged(self):
        rows = [_task(state="DONE", artifact_commit=None)] * 10
        self.assertIs(fo.phantom_rate(rows)["ok"], False)


class TestFleetAndSessionMetrics(unittest.TestCase):
    def test_generation_drift_is_a_spread_not_a_count(self):
        hosts = [{"host": "a", "generation": 7}, {"host": "b", "generation": 3}]
        self.assertEqual(fo.host_generation_drift(hosts)["value"], 4)

    def test_drift_names_the_hosts_that_are_behind(self):
        hosts = [{"host": "a", "generation": 7}, {"host": "b", "generation": 3}]
        self.assertEqual(fo.host_generation_drift(hosts)["drill"]["behind"], ["b"])

    def test_an_aligned_fleet_has_zero_drift_and_passes(self):
        hosts = [{"host": "a", "generation": 5}, {"host": "b", "generation": 5}]
        metric = fo.host_generation_drift(hosts)
        self.assertEqual(metric["value"], 0)
        self.assertIs(metric["ok"], True)

    def test_no_hosts_is_unknown(self):
        self.assertTrue(fo.host_generation_drift([]).unknown)

    def test_reconnect_loss_counts_sessions_with_sequence_gaps(self):
        sessions = ([{"session_id": "s1", "resumed": True, "event_gaps": 2}] +
                    [{"session_id": f"s{i}", "resumed": True, "event_gaps": 0}
                     for i in range(9)])
        metric = fo.session_reconnect_loss(sessions)
        self.assertEqual(metric["value"], 0.1)
        self.assertEqual(metric["drill"]["by_session"], ["s1"])

    def test_sessions_that_never_resumed_are_not_counted(self):
        self.assertTrue(fo.session_reconnect_loss(
            [{"session_id": "s", "resumed": False}] * 50).unknown)

    def test_recovery_rate_is_over_attempted_recoveries_only(self):
        rows = ([_task(recovery_attempted=True)] * 8 +
                [_task(state="BLOCKED", recovery_attempted=True)] * 2 +
                [_task()] * 100)
        self.assertEqual(fo.recovery_rate(rows)["value"], 0.8)

    def test_journey_needing_a_human_did_not_work(self):
        journeys = ([{"completed": True, "manual_intervention": True}] * 2 +
                    [{"completed": True}] * 8)
        self.assertEqual(fo.journey_reliability(journeys)["value"], 0.8)

    def test_cost_per_verified_change_divides_by_deliveries(self):
        rows = _many(4, cost_usd=10.0) + [_task(state="MERGED", cost_usd=10.0)] * 4
        self.assertEqual(fo.cost_per_verified_change(rows)["value"], 20.0)


class TestOperatorViewAndAlerts(unittest.TestCase):
    def _breaching(self):
        return _many(10, state="DONE", artifact_commit=None, claimed_shipped=True)

    def test_the_view_pins_every_metric(self):
        self.assertEqual(sorted(fo.evaluate()["metrics"]), sorted(fo.METRICS))

    def test_a_breach_is_alertable_with_its_drill_down(self):
        alerts = fo.alerts(fo.evaluate(tasks=self._breaching()))
        self.assertTrue(alerts)
        names = {a["metric"] for a in alerts}
        self.assertIn("phantom_rate", names)
        self.assertIn("drill", alerts[0])

    def test_alerts_carry_the_sample_size(self):
        for alert in fo.alerts(fo.evaluate(tasks=self._breaching())):
            self.assertGreaterEqual(alert["samples"], 1)

    def test_alerts_of_an_empty_view_are_empty(self):
        self.assertEqual(fo.alerts({}), [])
        self.assertEqual(fo.alerts(None), [])

    def test_lower_is_better_metrics_are_classified_correctly(self):
        self.assertIn("phantom_rate", fo.LOWER_IS_BETTER)
        self.assertNotIn("recovery_rate", fo.LOWER_IS_BETTER)


class TestRollout(unittest.TestCase):
    def setUp(self):
        self._saved = {k: os.environ.get(k) for k in
                       list(fo.STAGE_SWITCHES.values()) + [fo.KILL_SWITCH]}
        for key in self._saved:
            os.environ.pop(key, None)

    def tearDown(self):
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_everything_is_off_by_default(self):
        for stage in fo.ROLLOUT_STAGES:
            self.assertFalse(fo.stage_enabled(stage), stage)
        self.assertIsNone(fo.active_stage())

    def test_shadow_comes_first(self):
        self.assertEqual(fo.ROLLOUT_STAGES[0], "shadow")

    def test_a_stage_can_be_enabled_independently(self):
        os.environ[fo.STAGE_SWITCHES["shadow"]] = "1"
        self.assertTrue(fo.stage_enabled("shadow"))
        self.assertFalse(fo.stage_enabled("adapters"))
        self.assertEqual(fo.active_stage(), "shadow")

    def test_active_stage_is_the_furthest_one_enabled(self):
        os.environ[fo.STAGE_SWITCHES["shadow"]] = "1"
        os.environ[fo.STAGE_SWITCHES["canary"]] = "on"
        self.assertEqual(fo.active_stage(), "canary")

    def test_the_kill_switch_stops_every_stage(self):
        for switch in fo.STAGE_SWITCHES.values():
            os.environ[switch] = "1"
        os.environ[fo.KILL_SWITCH] = "1"
        self.assertIsNone(fo.active_stage())

    def test_an_unknown_stage_fails_closed(self):
        self.assertFalse(fo.stage_enabled("wat"))
        self.assertFalse(fo.stage_enabled(None))

    def test_the_plan_documents_how_to_reverse_it(self):
        plan = fo.rollout_plan()
        self.assertIn("rollback", plan)
        self.assertIn(fo.KILL_SWITCH, plan["rollback"])
        self.assertIn("shadow", plan["order"][0])

    def test_the_plan_states_the_zero_fabricated_points_invariant(self):
        self.assertIn("UNKNOWN", fo.rollout_plan()["invariant"])


class TestNumericHygiene(unittest.TestCase):
    def test_bool_is_never_a_measurement(self):
        self.assertIsNone(fo._num(True))
        self.assertIsNone(fo._num(False))

    def test_nan_and_inf_are_rejected(self):
        self.assertIsNone(fo._num(float("nan")))
        self.assertIsNone(fo._num(float("inf")))

    def test_junk_coerces_to_the_default(self):
        self.assertEqual(fo._num("abc", 7), 7)
        self.assertEqual(fo._num(None, 7), 7)

    def test_percentile_bounds(self):
        self.assertEqual(fo.percentile([1, 2, 3], 0), 1)
        self.assertEqual(fo.percentile([1, 2, 3], 100), 3)


if __name__ == "__main__":
    unittest.main()
