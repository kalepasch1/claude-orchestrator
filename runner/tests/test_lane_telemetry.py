#!/usr/bin/env python3
"""
test_lane_telemetry.py — the alert that would have caught 2026-08-02 in minutes.

The incident was not that the mem-gate closed. The gate was RIGHT: RAM was starved, so
it held claims. The incident was that a correctly-closed gate is indistinguishable from
a quiet fleet unless someone is measuring HOW LONG it has been closed. These tests pin
that duration behaviour, the lane-count alert, and — most importantly — the fail-soft
contract, because telemetry that can raise is telemetry that can take down the runner
it was added to protect.
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import lane_telemetry as lt  # noqa: E402


class Lane:
    def __init__(self, age_s, pid=0):
        self.age_s = age_s
        self.pid = pid


class AgeHistogramTests(unittest.TestCase):
    """A bare lane count cannot tell 8 working lanes from 8 dead ones. The shape can."""

    def test_lanes_land_in_their_buckets(self):
        hist = lt.age_histogram([Lane(60), Lane(10 * 60), Lane(20 * 60), Lane(2 * 3600)])
        self.assertEqual(hist["<5m"], 1)
        self.assertEqual(hist["<15m"], 1)
        self.assertEqual(hist["<30m"], 1)
        self.assertEqual(hist[">=60m"], 1)

    def test_the_incident_shape_is_top_heavy(self):
        """64 lanes all older than an hour — the signature that went unseen."""
        hist = lt.age_histogram([Lane(3600 + i) for i in range(64)])
        self.assertEqual(hist[">=60m"], 64)
        self.assertEqual(hist["<5m"], 0)

    def test_dicts_work_as_well_as_objects(self):
        self.assertEqual(lt.age_histogram([{"age_s": 30}])["<5m"], 1)

    def test_no_lanes_is_all_zeroes_not_an_error(self):
        self.assertEqual(set(lt.age_histogram([]).values()), {0})

    def test_garbage_ages_do_not_raise(self):
        hist = lt.age_histogram([Lane("nonsense"), Lane(None), Lane(-5)])
        self.assertEqual(sum(hist.values()), 3)


class ReapRateTests(unittest.TestCase):
    def test_counts_only_the_trailing_window(self):
        now = 10_000.0
        stamps = [now - 60, now - 600, now - 7200]      # two inside the hour, one outside
        self.assertEqual(lt.reaps_per_hour(stamps, now=now), 2.0)

    def test_a_short_window_is_scaled_to_an_hourly_rate(self):
        now = 10_000.0
        self.assertEqual(lt.reaps_per_hour([now - 10, now - 20], now=now, window_s=600), 12.0)

    def test_unparseable_stamps_are_skipped_not_fatal(self):
        now = 10_000.0
        self.assertEqual(lt.reaps_per_hour(["x", None, now - 5], now=now), 1.0)

    def test_no_reaps_is_zero(self):
        self.assertEqual(lt.reaps_per_hour([], now=1.0), 0.0)


class GateClockTests(unittest.TestCase):
    """Duration is the whole point: 90s closed is the gate working, 15m is an outage."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.clock = lt._GateClock(path=os.path.join(self.tmp.name, "gate.json"))

    def test_an_open_gate_reports_zero(self):
        self.assertEqual(self.clock.observe(False, now=100.0), 0.0)

    def test_closed_duration_accumulates_across_ticks(self):
        self.assertEqual(self.clock.observe(True, now=1000.0), 0.0)
        self.assertEqual(self.clock.observe(True, now=1300.0), 300.0)
        self.assertEqual(self.clock.observe(True, now=1900.0), 900.0)

    def test_reopening_resets_the_clock(self):
        self.clock.observe(True, now=1000.0)
        self.assertEqual(self.clock.observe(False, now=1200.0), 0.0)
        self.assertEqual(self.clock.observe(True, now=1500.0), 0.0)

    def test_closed_since_survives_a_restart(self):
        """A restart that reset the clock would mean this alert could never fire."""
        self.clock.observe(True, now=1000.0)
        reborn = lt._GateClock(path=self.clock.path)
        self.assertEqual(reborn.observe(True, now=1600.0), 600.0)

    def test_an_unreadable_state_file_starts_fresh_instead_of_raising(self):
        with open(self.clock.path, "w") as fh:
            fh.write("{not json")
        self.assertEqual(lt._GateClock(path=self.clock.path).observe(True, now=50.0), 0.0)


class LaneCountAlertTests(unittest.TestCase):
    """'lanes>throttle+5' — the directive's literal wording."""

    def test_within_slack_is_silent(self):
        self.assertEqual(lt.evaluate_alerts(9, throttle=8, gate_closed_s=0), [])

    def test_exactly_at_the_slack_boundary_is_still_silent(self):
        self.assertEqual(lt.evaluate_alerts(13, throttle=8, gate_closed_s=0), [])

    def test_one_over_the_boundary_pages(self):
        alerts = lt.evaluate_alerts(14, throttle=8, gate_closed_s=0)
        self.assertEqual([a["kind"] for a in alerts], ["lane_count_over_throttle"])

    def test_the_incident_lane_count_pages(self):
        alerts = lt.evaluate_alerts(66, throttle=8, gate_closed_s=0)
        self.assertTrue(any(a["kind"] == "lane_count_over_throttle" for a in alerts))

    def test_an_unknown_throttle_does_not_page_on_nonsense(self):
        """throttle=0 means 'not reported'. Paging off that is noise, not signal."""
        self.assertEqual(lt.evaluate_alerts(50, throttle=0, gate_closed_s=0), [])

    def test_the_slack_is_fleet_tunable(self):
        os.environ["ORCH_LANE_ALERT_SLACK"] = "1"
        self.addCleanup(os.environ.pop, "ORCH_LANE_ALERT_SLACK", None)
        self.assertEqual(lt.lane_alert_slack(), 1)
        self.assertTrue(lt.evaluate_alerts(10, throttle=8, gate_closed_s=0))

    def test_a_garbage_slack_falls_back_to_five_rather_than_disabling_the_alert(self):
        os.environ["ORCH_LANE_ALERT_SLACK"] = "not-a-number"
        self.addCleanup(os.environ.pop, "ORCH_LANE_ALERT_SLACK", None)
        self.assertEqual(lt.lane_alert_slack(), 5)


class MemGateAlertTests(unittest.TestCase):
    """'mem-gate closed >15 min' — the half of the incident nobody was told about."""

    def test_a_briefly_closed_gate_is_the_gate_working_not_an_alert(self):
        self.assertEqual(lt.evaluate_alerts(4, throttle=8, gate_closed_s=90), [])

    def test_fifteen_minutes_exactly_is_still_patience(self):
        self.assertEqual(lt.evaluate_alerts(4, throttle=8, gate_closed_s=15 * 60), [])

    def test_past_fifteen_minutes_pages_critical(self):
        alerts = lt.evaluate_alerts(4, throttle=8, gate_closed_s=15 * 60 + 1)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["kind"], "mem_gate_closed_too_long")
        self.assertEqual(alerts[0]["severity"], "critical")

    def test_the_ram_reading_is_carried_into_the_alert_text(self):
        alerts = lt.evaluate_alerts(4, throttle=8, gate_closed_s=3600,
                                    free_gb=2.5, floor_gb=4.0)
        self.assertIn("free=2.5GB", alerts[0]["detail"])
        self.assertIn("floor=4.0GB", alerts[0]["detail"])

    def test_a_missing_ram_reading_still_pages(self):
        """Unknown RAM is not a reason to stay silent about a 40-minute hold."""
        self.assertTrue(lt.evaluate_alerts(4, throttle=8, gate_closed_s=2400))

    def test_the_patience_window_is_fleet_tunable(self):
        os.environ["ORCH_MEMGATE_ALERT_S"] = "60"
        self.addCleanup(os.environ.pop, "ORCH_MEMGATE_ALERT_S", None)
        self.assertEqual(lt.memgate_alert_seconds(), 60)
        self.assertTrue(lt.evaluate_alerts(4, throttle=8, gate_closed_s=61))

    def test_both_conditions_page_independently(self):
        alerts = lt.evaluate_alerts(66, throttle=8, gate_closed_s=3600)
        self.assertEqual({a["kind"] for a in alerts},
                         {"lane_count_over_throttle", "mem_gate_closed_too_long"})


class FailSoftTests(unittest.TestCase):
    """A crash in the observer must never take down the runner it observes."""

    def test_garbage_inputs_return_no_alerts_instead_of_raising(self):
        self.assertEqual(lt.evaluate_alerts("x", throttle="y", gate_closed_s="z"), [])

    def test_none_inputs_return_no_alerts_instead_of_raising(self):
        self.assertEqual(lt.evaluate_alerts(None, throttle=None, gate_closed_s=None), [])

    def test_emit_survives_both_sinks_being_unavailable(self):
        """DB down AND notify down still must not raise — it logs and returns 0.

        The sinks are stubbed rather than merely assumed-absent: if this ran against a
        reachable database it would write a fake alert into the real runner_alerts table.
        """
        import types

        broken_db = types.ModuleType("db")
        broken_db.insert = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db down"))
        broken_notify = types.ModuleType("notify")
        broken_notify.send = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no pipe"))

        saved = {name: sys.modules.get(name) for name in ("db", "notify")}
        sys.modules["db"], sys.modules["notify"] = broken_db, broken_notify
        try:
            self.assertEqual(lt.emit([{"kind": "k", "detail": "d"}], host="h"), 0)
        finally:
            for name, module in saved.items():
                if module is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = module

    def test_emit_records_to_the_db_sink_when_it_is_available(self):
        """The happy path must actually write, or the alert is decorative."""
        import types

        written = []
        fake_db = types.ModuleType("db")
        fake_db.insert = lambda table, row: written.append((table, row))
        fake_notify = types.ModuleType("notify")
        fake_notify.send = lambda msg: None

        saved = {name: sys.modules.get(name) for name in ("db", "notify")}
        sys.modules["db"], sys.modules["notify"] = fake_db, fake_notify
        try:
            sent = lt.emit([{"kind": "mem_gate_closed_too_long", "detail": "40m"}], host="mac1")
        finally:
            for name, module in saved.items():
                if module is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = module

        self.assertEqual(sent, 1)
        self.assertEqual(written[0][0], "runner_alerts")
        self.assertEqual(written[0][1]["kind"], "mem_gate_closed_too_long")
        self.assertFalse(written[0][1]["resolved"])
        self.assertIn("host=mac1", written[0][1]["detail"])

    def test_emit_of_nothing_is_a_no_op(self):
        self.assertEqual(lt.emit([]), 0)
        self.assertEqual(lt.emit(None), 0)


class SnapshotShapeTests(unittest.TestCase):
    """The dashboard is a separate process; the payload must stay JSON-safe."""

    def setUp(self):
        lt.reset_gate_clock()
        self.addCleanup(lt.reset_gate_clock)

    def test_snapshot_carries_every_field_the_directive_names(self):
        payload = lt.snapshot(lanes=[Lane(60), Lane(7200)], reap_times=[], now=5000.0)
        for key in ("lane_count", "lane_age_histogram", "reaps_per_hour",
                    "mem_gate", "throttle", "alerts"):
            self.assertIn(key, payload)
        self.assertEqual(payload["lane_count"], 2)
        for key in ("closed", "closed_s", "free_gb", "floor_gb"):
            self.assertIn(key, payload["mem_gate"])

    def test_the_payload_is_json_serialisable(self):
        import json
        json.dumps(lt.snapshot(lanes=[Lane(1)], now=1.0), default=str)

    def test_tick_does_not_emit_when_asked_not_to(self):
        payload = lt.tick(lanes=[], now=1.0, emit_alerts=False)
        self.assertNotIn("alerts_emitted", payload)


class ContractReuseTests(unittest.TestCase):
    """Two components that disagree about 'zombie' is the bug lane_medic.sh calls out."""

    def test_thresholds_are_not_redefined_here(self):
        source = open(lt.__file__).read()
        code = "\n".join(
            line for line in source.splitlines() if not line.strip().startswith("#"))
        self.assertNotIn("ORCH_LANE_ZOMBIE_AFTER_S", code)
        self.assertNotIn("ORCH_DAEMON_STUCK_INTERVAL_FACTOR", code)

    def test_this_module_observes_and_never_reaps(self):
        """Killing belongs to lane_guard. An observer that acts can cause the incident."""
        source = open(lt.__file__).read()
        code = "\n".join(
            line for line in source.splitlines() if not line.strip().startswith("#"))
        for weapon in ("os.kill", "killpg", "SIGKILL", "SIGTERM"):
            self.assertNotIn(weapon, code)


if __name__ == "__main__":
    unittest.main()
