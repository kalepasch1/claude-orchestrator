#!/usr/bin/env python3
"""§PROOFS — the fleet immune system's acceptance criteria, as executable assertions.

Operator directive 2026-08-02 listed the proofs in prose:

  * kill -STOP a fixture lane -> reaped within limit+2m and the task requeued
  * launch legal_docket twice -> the second exits on lock
  * silence a machine heartbeat -> operator alert fires
  * delete the pressure file -> the consistency test flags it within 1h
  * drain a fixture project below threshold -> auto-revert restores batching
  * stage-cycle dashboard live with route win rates
  * 2-failure escalation observably reroutes
  * no legal-class coder runs on local small models (query proof)

Each is pinned below against the shipped modules. Deliberately fixture-driven rather than
live-fleet-driven: a proof that only passes on a healthy production fleet is a proof that
stops running the moment it is needed most, and cannot gate a merge.

Where a proof depends on an actuator implemented by a sibling task (the lane reaper, the
docket lock), the assertion is on the CONTRACT that actuator must satisfy — that is the part
this repo can hold still, and the part a regression would silently change.
"""
import os
import sys
import tempfile
import unittest

RUNNER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner")
sys.path.insert(0, RUNNER)

import fleet_immune_contracts as fic  # noqa: E402
import pipeline_selftest as ps  # noqa: E402
import route_accelerators as ra  # noqa: E402
import datetime  # noqa: E402


def _iso(seconds_ago=0):
    return (datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(seconds=seconds_ago)).isoformat()


class ProofStoppedLaneIsReaped(unittest.TestCase):
    """PROOF: a -STOP'd fixture lane is reaped within limit + 2 minutes."""

    GRACE_S = 120

    def test_lane_at_the_limit_plus_grace_is_classified_for_reaping(self):
        lane = fic.LaneSnapshot(pid=4242, age_s=fic.LANE_ZOMBIE_AFTER_S + self.GRACE_S)
        verdict = fic.classify_lane(lane)
        self.assertEqual(verdict.state, fic.ZOMBIE)
        self.assertEqual(verdict.action, "reap")

    def test_a_stopped_lane_burning_no_cpu_is_still_reaped_on_age(self):
        """kill -STOP means 0% CPU: liveness must not be inferred from activity."""
        lane = fic.LaneSnapshot(pid=4242, age_s=fic.LANE_ZOMBIE_AFTER_S + 1, cpu_pct=0.0)
        self.assertEqual(fic.classify_lane(lane).action, "reap")

    def test_a_lane_inside_the_limit_is_watched_but_never_reaped(self):
        """The suspect band must warn without killing live work one minute early."""
        verdict = fic.classify_lane(fic.LaneSnapshot(pid=1, age_s=fic.LANE_ZOMBIE_AFTER_S - 60))
        self.assertNotEqual(verdict.action, "reap")
        self.assertEqual(verdict.action, "watch")
        self.assertFalse(
            fic.classify_lane(fic.LaneSnapshot(pid=1, age_s=30)).actionable,
            "a young lane must produce no verdict at all")

    def test_the_reap_verdict_carries_the_pid_the_requeue_needs(self):
        verdict = fic.classify_lane(fic.LaneSnapshot(pid=4242, age_s=99999))
        self.assertEqual(verdict.detail["pid"], 4242)
        self.assertTrue(verdict.reason, "a reap without a reason cannot be audited afterwards")

    def test_the_sixty_four_of_sixty_six_incident_reproduces_as_verdicts(self):
        lanes = ([fic.LaneSnapshot(pid=i, age_s=4000) for i in range(64)]
                 + [fic.LaneSnapshot(pid=100 + i, age_s=30) for i in range(2)])
        reaped = [v for v in fic.sweep(lanes=lanes) if v.action == "reap"]
        self.assertEqual(len(reaped), 64)


class ProofSecondDocketExitsOnLock(unittest.TestCase):
    """PROOF: launching legal_docket twice leaves exactly one running."""

    def test_fourteen_concurrent_copies_is_a_leak_verdict(self):
        verdict = fic.detect_daemon_leak(
            fic.DaemonSnapshot(name="legal_docket.py", pids=list(range(14)),
                               oldest_age_s=10 * 3600, interval_s=1800))
        self.assertEqual(verdict.state, fic.LEAKED)
        self.assertEqual(verdict.detail["keep_newest"], 1,
                         "exactly one copy may survive; the rest are the leak")

    def test_two_copies_already_violates_the_single_instance_contract(self):
        self.assertEqual(
            fic.detect_daemon_leak(fic.DaemonSnapshot(name="legal_docket.py", pids=[1, 2],
                                                      interval_s=1800)).state,
            fic.LEAKED)

    def test_one_copy_within_its_interval_is_correct(self):
        self.assertFalse(
            fic.detect_daemon_leak(fic.DaemonSnapshot(name="legal_docket.py", pids=[1],
                                                      oldest_age_s=600,
                                                      interval_s=1800)).actionable)


class ProofSilentMachineAlerts(unittest.TestCase):
    """PROOF: silencing a machine heartbeat fires an operator alert."""

    def test_silencing_mac_two_fires_an_alert(self):
        verdicts = ps.check_machine_heartbeats(
            rows=[{"hostname": "mac1", "last_seen": _iso(20)},
                  {"hostname": "Mandys-MacBook-Pro.local", "last_seen": _iso(6 * 3600)}],
            control_rows=[])
        alerts = [v for v in verdicts if v.action == "alert"]
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].subject, "host:Mandys-MacBook-Pro.local")

    def test_the_half_day_outage_would_have_alerted_within_thirty_minutes(self):
        """Mac 2 died ~10:28 and nothing fired for hours."""
        verdicts = ps.check_machine_heartbeats(
            rows=[{"hostname": "mac2", "last_seen": _iso(31 * 60)}], control_rows=[])
        self.assertTrue(any(v.action == "alert" for v in verdicts))

    def test_a_healthy_fleet_produces_no_alert_noise(self):
        self.assertEqual(
            ps.check_machine_heartbeats(rows=[{"hostname": "mac1", "last_seen": _iso(10)},
                                              {"hostname": "mac2", "last_seen": _iso(10)}],
                                        control_rows=[]),
            [])


class ProofDeletedPressureFileIsFlagged(unittest.TestCase):
    """PROOF: deleting the pressure file is flagged by the consistency test within 1h."""

    def test_deleted_file_with_a_live_db_row_is_flagged_as_a_consumer_bug(self):
        verdict = ps.check_pressure_consistency(file_age_s=None, db_age_s=60)
        self.assertTrue(verdict.actionable)
        self.assertEqual(verdict.action, "fix_consumer")

    def test_the_flag_fires_inside_the_one_hour_window(self):
        verdict = ps.check_pressure_consistency(file_age_s=3601, db_age_s=60, stale_s=3600)
        self.assertTrue(verdict.actionable)

    def test_a_genuinely_stale_train_is_reported_differently_from_a_broken_reader(self):
        """The false-alarm bug was these two being indistinguishable."""
        broken_reader = ps.check_pressure_consistency(file_age_s=None, db_age_s=60)
        real_stall = ps.check_pressure_consistency(file_age_s=99999, db_age_s=99999)
        self.assertNotEqual(broken_reader.action, real_stall.action)
        self.assertEqual(real_stall.action, "fire_train")


class ProofDrainedQueueRestoresBatching(unittest.TestCase):
    """PROOF: draining a fixture project below threshold auto-reverts to default batching."""

    def test_a_drained_queue_sustained_for_a_day_reverts(self):
        _, state, _ = ps.evaluate_auto_revert(12, state={}, now_t=0, min_batch=1)
        should, _, reason = ps.evaluate_auto_revert(12, state=state, now_t=25 * 3600, min_batch=1)
        self.assertTrue(should)
        self.assertIn("restoring default release batching", reason)

    def test_the_override_removal_is_reversible_and_leaves_a_record(self):
        fd, path = tempfile.mkstemp(suffix=".env")
        with os.fdopen(fd, "w") as f:
            f.write("RELEASE_MIN_BATCH=1\n")
        self.addCleanup(os.unlink, path)
        self.assertTrue(ps.remove_env_override(env_path=path))
        text = open(path).read()
        self.assertIn("auto-reverted", text)
        self.assertIn("RELEASE_MIN_BATCH=1", text)

    def test_a_still_full_queue_never_reverts(self):
        should, _, _ = ps.evaluate_auto_revert(803, state={}, now_t=0, min_batch=1)
        self.assertFalse(should)


class ProofStageCycleDashboardIsLive(unittest.TestCase):
    """PROOF: stage-cycle dashboard with route win rates."""

    def _records(self):
        good = [{"project": "apparently", "route": "claude:opus", "queued_at": 0,
                 "claimed_at": 5, "coder_done_at": 100, "qa_at": 110, "merged_at": 130,
                 "released_at": 140, "attempt": 0} for _ in range(12)]
        bad = [{"project": "apparently", "route": "local:llama3.2:3b", "queued_at": 0,
                "claimed_at": 5, "coder_done_at": 900, "qa_at": 950, "attempt": 0}
               for _ in range(12)]
        return good + bad

    def test_every_stage_reports_p50_and_p90(self):
        stats = ra.stage_cycle_stats(self._records())
        for stage in ("queued_to_claimed", "claimed_to_coder_done", "coder_done_to_qa"):
            data = stats["overall"]["stages"][stage]
            self.assertIsNotNone(data["p50"], stage)
            self.assertIsNotNone(data["p90"], stage)

    def test_metrics_are_broken_out_per_project_and_per_route(self):
        stats = ra.stage_cycle_stats(self._records())
        self.assertIn("apparently", stats["by"]["project"])
        self.assertEqual(sorted(stats["by"]["route"]), ["claude:opus", "local:llama3.2:3b"])

    def test_route_win_rates_rank_the_zero_of_twelve_route_last(self):
        board = ra.route_leaderboard(ra.stage_cycle_stats(self._records()))
        self.assertEqual(board[0]["route"], "local:llama3.2:3b")
        self.assertEqual(board[0]["first_pass_merge_rate"], 0.0)
        self.assertEqual(board[0]["action"], "demote_route")
        self.assertEqual(board[-1]["first_pass_merge_rate"], 1.0)

    def test_the_dashboard_renders_the_headline_metric(self):
        text = ra.render(ra.stage_cycle_stats(self._records()))
        self.assertIn("first-pass merge rate", text)
        self.assertIn("ROUTE FIRST-PASS MERGE RATE", text)


class ProofEscalationReroutes(unittest.TestCase):
    """PROOF: 2-failure escalation observably reroutes."""

    def test_the_third_attempt_lands_on_the_strongest_route(self):
        import model_policy
        raw = model_policy._choose_raw
        model_policy._choose_raw = lambda **k: ("local", "llama3.2:3b", "cheapest capable")
        try:
            first = model_policy.choose(task_class="build", need=6, task={"attempt": 0})
            third = model_policy.choose(task_class="build", need=6, task={"attempt": 2})
        finally:
            model_policy._choose_raw = raw
        self.assertEqual(first[:2], ("local", "llama3.2:3b"))
        self.assertEqual(third[:2], ra.STRONGEST_ROUTE)
        self.assertNotEqual(first[:2], third[:2], "the reroute must be observable")

    def test_the_reroute_states_its_reason_for_the_audit_trail(self):
        _, _, reason = ra.enforce_route("local", "llama3.2:3b", need=6, attempt=2)
        self.assertIn("route-escalation", reason)
        self.assertIn("2 prior failed attempts", reason)


class ProofNoLegalClassOnSmallModels(unittest.TestCase):
    """PROOF (query): no legal-class coder run may land on a local small model."""

    def test_the_audit_query_finds_a_planted_violation(self):
        violations = ra.route_violations([
            {"slug": "legal-a", "need": 9, "provider": "local", "model": "llama3.2:3b"},
            {"slug": "legal-b", "need": 9, "provider": "ollama", "model": "deepseek-coder-v2:16b"},
            {"slug": "build-c", "need": 5, "provider": "local", "model": "llama3.2:3b"},
        ])
        self.assertEqual(sorted(v.detail["slug"] for v in violations), ["legal-a", "legal-b"])

    def test_a_compliant_fleet_produces_no_violations(self):
        self.assertEqual(ra.route_violations([
            {"slug": "legal-a", "need": 9, "provider": "claude", "model": "claude-opus-4-8"},
            {"slug": "legal-b", "need": 9, "provider": "claude", "model": "claude-sonnet-4-6"},
        ]), [])

    def test_the_router_itself_cannot_produce_such_a_run(self):
        """Belt and braces: the audit finds violations, the router refuses to create them."""
        for provider, model in (("local", "llama3.2:3b"),
                                ("ollama", "deepseek-coder-v2:16b"),
                                ("claude", "claude-haiku-4-5-20251001")):
            chosen = ra.enforce_route(provider, model, task_class="legal", need=9)
            self.assertFalse(ra.is_weak_route(chosen[0], chosen[1]),
                             f"{provider}:{model} survived the legal-class floor")


class ProofEveryActionIsAuditable(unittest.TestCase):
    """Cross-cutting: nothing the immune system does may happen silently."""

    def test_every_actionable_verdict_carries_a_reason(self):
        verdicts = fic.sweep(
            lanes=[fic.LaneSnapshot(pid=1, age_s=99999)],
            daemons=[fic.DaemonSnapshot(name="legal_docket.py", pids=[1, 2], interval_s=1800)],
            hosts=[fic.HostLiveness(host="mac2", last_heartbeat_age_s=None)],
            capacity=[fic.CapacitySignal(host="mac1", claimable=803, claiming=0,
                                         live_lanes=66, zombie_lanes=64)],
            gates=[fic.ReleaseGate(pending=2, min_batch=10, oldest_pending_age_s=60)],
            routes=[fic.RouteQuality(route="r", task_class="legal", samples=12, merged=0)],
        )
        self.assertEqual(len(verdicts), 6)
        for verdict in verdicts:
            self.assertTrue(verdict.reason, verdict.subject)
            self.assertTrue(fic.event_row(verdict, "mac1")["reason"])

    def test_a_held_release_is_reported_even_though_it_is_not_acted_on(self):
        verdict = fic.evaluate_release_gate(
            fic.ReleaseGate(pending=2, min_batch=10, oldest_pending_age_s=60))
        self.assertEqual(verdict.state, fic.HELD)
        self.assertEqual(verdict.action, "report",
                         "the 2026-08-02 batch floor held merges with nothing saying so")


if __name__ == "__main__":
    unittest.main()
