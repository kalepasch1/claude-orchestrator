#!/usr/bin/env python3
"""Tests for runner/fleet_immune_contracts.py — the shared fleet-immune vocabulary.

Each test pins one of the seven 2026-08-02 incident findings to the contract that must make
it impossible to recur silently.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner"))

import fleet_immune_contracts as fic  # noqa: E402


class LaneTests(unittest.TestCase):
    def test_hour_old_lane_is_a_zombie_and_gets_reaped(self):
        v = fic.classify_lane(fic.LaneSnapshot(pid=101, age_s=3900))
        self.assertEqual(v.state, fic.ZOMBIE)
        self.assertEqual(v.action, "reap")
        self.assertTrue(v.reason)

    def test_suspect_band_watches_but_does_not_reap(self):
        v = fic.classify_lane(fic.LaneSnapshot(pid=102, age_s=2500))
        self.assertEqual(v.state, fic.SUSPECT)
        self.assertEqual(v.action, "watch")

    def test_young_lane_is_healthy_and_not_actionable(self):
        v = fic.classify_lane(fic.LaneSnapshot(pid=103, age_s=60))
        self.assertEqual(v.state, fic.HEALTHY)
        self.assertFalse(v.actionable)

    def test_garbage_lane_is_fail_soft(self):
        self.assertEqual(fic.classify_lane(None).state, fic.HEALTHY)
        self.assertEqual(fic.classify_lane(object()).state, fic.HEALTHY)


class DaemonTests(unittest.TestCase):
    def test_fourteen_copies_is_a_leak(self):
        """The legal_docket.py finding, verbatim."""
        v = fic.detect_daemon_leak(
            fic.DaemonSnapshot(name="legal_docket.py", pids=list(range(14)),
                               oldest_age_s=9 * 3600, interval_s=1800))
        self.assertEqual(v.state, fic.LEAKED)
        self.assertEqual(v.action, "reap_extra")
        self.assertEqual(v.detail["keep_newest"], 1)

    def test_single_copy_far_past_its_interval_is_stuck(self):
        v = fic.detect_daemon_leak(
            fic.DaemonSnapshot(name="legal_docket.py", pids=[7], oldest_age_s=5400, interval_s=1800))
        self.assertEqual(v.state, fic.STUCK)
        self.assertEqual(v.action, "reap")

    def test_single_healthy_copy_is_not_actionable(self):
        v = fic.detect_daemon_leak(
            fic.DaemonSnapshot(name="merge_train.py", pids=[9], oldest_age_s=30, interval_s=60))
        self.assertFalse(v.actionable)

    def test_unknown_interval_does_not_false_positive(self):
        v = fic.detect_daemon_leak(
            fic.DaemonSnapshot(name="x", pids=[1], oldest_age_s=99999, interval_s=0))
        self.assertEqual(v.state, fic.HEALTHY)

    def test_daemon_garbage_is_fail_soft(self):
        self.assertEqual(fic.detect_daemon_leak(None).state, fic.HEALTHY)


class HostTests(unittest.TestCase):
    def test_unknown_heartbeat_is_down_never_healthy(self):
        """Mac 2 was dark for hours because 'no data' read as 'fine'."""
        v = fic.classify_host(fic.HostLiveness(host="Mandys-MacBook-Pro.local",
                                               last_heartbeat_age_s=None))
        self.assertEqual(v.state, fic.DOWN)
        self.assertEqual(v.action, "alert")

    def test_stale_heartbeat_alerts(self):
        v = fic.classify_host(fic.HostLiveness(host="mac2", last_heartbeat_age_s=3600))
        self.assertEqual(v.state, fic.DOWN)

    def test_lagging_heartbeat_is_degraded(self):
        v = fic.classify_host(fic.HostLiveness(host="mac2", last_heartbeat_age_s=400))
        self.assertEqual(v.state, fic.DEGRADED)

    def test_runner_down_flag_alerts_even_with_fresh_heartbeat(self):
        v = fic.classify_host(fic.HostLiveness(host="mac2", last_heartbeat_age_s=5, runner_up=False))
        self.assertEqual(v.state, fic.DOWN)

    def test_fresh_host_is_healthy(self):
        self.assertFalse(fic.classify_host(fic.HostLiveness(host="mac1", last_heartbeat_age_s=10)).actionable)

    def test_unreadable_liveness_is_down(self):
        self.assertEqual(fic.classify_host(None).state, fic.DOWN)


class CapacityTests(unittest.TestCase):
    def test_starvation_is_attributed_to_zombie_lanes_not_the_queue(self):
        v = fic.classify_capacity(fic.CapacitySignal(host="mac1", claimable=803, claiming=0,
                                                     live_lanes=66, zombie_lanes=64))
        self.assertEqual(v.state, fic.STARVED)
        self.assertEqual(v.action, "reap_lanes")
        self.assertIn("zombies", v.reason)

    def test_starvation_from_real_ram_pressure_says_free_memory(self):
        v = fic.classify_capacity(fic.CapacitySignal(host="mac1", claimable=803, claiming=0,
                                                     free_ram_gb=1.0, ram_floor_gb=6.0))
        self.assertEqual(v.action, "free_memory")

    def test_unexplained_starvation_is_flagged_for_investigation(self):
        v = fic.classify_capacity(fic.CapacitySignal(host="mac1", claimable=10, claiming=0,
                                                     free_ram_gb=32.0, ram_floor_gb=6.0))
        self.assertEqual(v.state, fic.SUSPECT)
        self.assertEqual(v.action, "investigate")

    def test_claiming_normally_is_healthy(self):
        self.assertFalse(fic.classify_capacity(
            fic.CapacitySignal(host="mac1", claimable=100, claiming=8)).actionable)


class ReleaseGateTests(unittest.TestCase):
    def test_batch_at_or_above_floor_releases(self):
        v = fic.evaluate_release_gate(fic.ReleaseGate(pending=3, min_batch=1))
        self.assertEqual(v.action, "release")

    def test_small_batch_below_floor_is_held_but_never_silently(self):
        v = fic.evaluate_release_gate(fic.ReleaseGate(pending=2, min_batch=10,
                                                      oldest_pending_age_s=60, max_hold_s=3600))
        self.assertEqual(v.state, fic.HELD)
        self.assertTrue(v.reason)
        self.assertEqual(v.action, "report")

    def test_age_override_ships_a_batch_the_floor_would_strand(self):
        v = fic.evaluate_release_gate(fic.ReleaseGate(pending=2, min_batch=10,
                                                      oldest_pending_age_s=7200, max_hold_s=3600))
        self.assertEqual(v.state, fic.RELEASE_OK)
        self.assertEqual(v.action, "release")

    def test_nothing_pending_is_not_actionable(self):
        self.assertFalse(fic.evaluate_release_gate(fic.ReleaseGate(pending=0)).actionable)


class RouteTests(unittest.TestCase):
    def test_zero_of_twelve_merged_demotes_the_route(self):
        v = fic.classify_route(fic.RouteQuality(route="swarm:openai", task_class="legal",
                                                samples=12, merged=0))
        self.assertEqual(v.state, fic.DEMOTE)
        self.assertEqual(v.action, "demote_route")

    def test_insufficient_evidence_does_not_demote(self):
        v = fic.classify_route(fic.RouteQuality(route="x", task_class="legal", samples=2, merged=0))
        self.assertFalse(v.actionable)

    def test_good_route_survives(self):
        v = fic.classify_route(fic.RouteQuality(route="claude", task_class="legal",
                                                samples=20, merged=14))
        self.assertFalse(v.actionable)


class SweepTests(unittest.TestCase):
    def test_sweep_returns_only_actionable_verdicts(self):
        verdicts = fic.sweep(
            lanes=[fic.LaneSnapshot(pid=1, age_s=4000), fic.LaneSnapshot(pid=2, age_s=5)],
            hosts=[fic.HostLiveness(host="mac2", last_heartbeat_age_s=None)],
            routes=[fic.RouteQuality(route="r", task_class="legal", samples=12, merged=0)],
        )
        self.assertEqual(len(verdicts), 3)
        self.assertTrue(all(v.actionable and v.reason for v in verdicts))

    def test_sweep_skips_bad_elements_instead_of_raising(self):
        verdicts = fic.sweep(lanes=[None, fic.LaneSnapshot(pid=1, age_s=4000)])
        self.assertEqual(len(verdicts), 1)

    def test_sweep_with_no_input_is_empty(self):
        self.assertEqual(fic.sweep(), [])


class JournalTests(unittest.TestCase):
    def test_event_row_shape_matches_the_ddl_columns(self):
        v = fic.classify_lane(fic.LaneSnapshot(pid=5, age_s=4000))
        row = fic.event_row(v, "mac1")
        for column in ("host", "subject", "state", "action", "reason", "detail", "contract_ver"):
            self.assertIn(column, row)
            self.assertIn(column, fic.FLEET_IMMUNE_EVENT_DDL)

    def test_ddl_is_idempotent(self):
        self.assertIn("CREATE TABLE IF NOT EXISTS", fic.FLEET_IMMUNE_EVENT_DDL)
        self.assertEqual(fic.FLEET_IMMUNE_EVENT_DDL.count("CREATE INDEX IF NOT EXISTS"), 2)

    def test_event_row_is_fail_soft(self):
        self.assertEqual(fic.event_row(None, "mac1")["host"], "mac1")

    def test_db_is_the_authoritative_source(self):
        """Diagnosis (5): a file-only consumer goes blind when the writer moves to the DB."""
        self.assertEqual(fic.AUTHORITATIVE_SOURCE, fic.SOURCE_DB)
        self.assertEqual(fic.HostLiveness().source, fic.SOURCE_DB)


if __name__ == "__main__":
    unittest.main()
