#!/usr/bin/env python3
"""Tests for runner/remediation_bots.py.

Each test names the property from the spec it defends. These are not
smoke tests: every one of them corresponds to something the previous
self-healer lacked when it caused the 17-day release outage.
"""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import remediation_bots as rb


class FakeStore:
    """In-memory Store. Survives a simulated restart because the LOG rows are
    what the counters are derived from, not any in-process state."""

    def __init__(self, tables=None, log=None):
        self.tables = tables or {}
        self.log = log if log is not None else []
        self.alarms = []
        self.writes = []
        self.fail_log_read = False

    # -- log --
    def append_log(self, row):
        row = dict(row)
        row.setdefault("ts", time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()))
        self.log.append(row)

    def recent_log(self, remediator, problem_key, subject, since_epoch):
        if self.fail_log_read:
            raise RuntimeError("log unavailable")
        rows = [r for r in self.log
                if r.get("remediator") == remediator
                and r.get("problem_key") == problem_key
                and r.get("subject") == subject]
        return list(reversed(rows))  # most recent first

    # -- alarms --
    def raise_alarm(self, gate, kind, detail):
        self.alarms.append({"gate": gate, "kind": kind, "detail": detail})

    # -- generic --
    def select(self, table, params):
        return list(self.tables.get(table, []))

    def update(self, table, match, patch):
        self.writes.append((table, dict(match), dict(patch)))
        for row in self.tables.get(table, []):
            if all(str(row.get(k)) == str(v) for k, v in match.items()):
                row.update(patch)
        return True


def outcomes(rows):
    return [r["outcome"] for r in rows]


class AlwaysFinds(rb.Remediator):
    """A remediator with one finding that its action never actually clears."""
    name = "alwaysfinds"
    problem_key = "never_clears"

    def detect(self):
        return [{"subject": "s1", "evidence": {"bad": True}}]

    def act(self, finding):
        return "pretended to fix it"

    def measure(self, subject):
        return {"bad": True}   # still broken

    def cleared(self, before, after):
        return not after.get("bad")


class AlwaysWorks(AlwaysFinds):
    name = "alwaysworks"
    problem_key = "clears_fine"

    def measure(self, subject):
        return {}


# ── property 1: bounded attempts ─────────────────────────────────────────────

class TestBoundedAttempts(unittest.TestCase):
    def test_attempt_cap_stops_at_three_and_escalates(self):
        store = FakeStore()
        seen = []
        for _ in range(6):
            bot = AlwaysWorks(store, mode=rb.MODE_ON)
            seen.append(outcomes(bot.run_cycle()))
        acted = sum(o.count(rb.OUTCOME_ACTED) for o in seen)
        escalated = sum(o.count(rb.OUTCOME_ESCALATED) for o in seen)
        self.assertEqual(acted, rb.MAX_ATTEMPTS_24H)
        self.assertGreaterEqual(escalated, 1, "attempt 4 must open an operator card")

    def test_attempt_cap_survives_a_process_restart(self):
        """The counter is derived from remediation_log, so a fresh object with
        the same log must NOT get a fresh budget."""
        log = []
        for _ in range(rb.MAX_ATTEMPTS_24H):
            AlwaysWorks(FakeStore(log=log), mode=rb.MODE_ON).run_cycle()

        # Simulated restart: brand-new store object, same durable log.
        restarted = FakeStore(log=log)
        rows = AlwaysWorks(restarted, mode=rb.MODE_ON).run_cycle()
        self.assertIn(rb.OUTCOME_ESCALATED, outcomes(rows))
        self.assertNotIn(rb.OUTCOME_ACTED, outcomes(rows))

    def test_escalation_raises_an_operator_alarm(self):
        log = []
        for _ in range(rb.MAX_ATTEMPTS_24H + 1):
            store = FakeStore(log=log)
            AlwaysWorks(store, mode=rb.MODE_ON).run_cycle()
        self.assertTrue(store.alarms, "attempt-cap escalation must alarm")

    def test_unknown_history_is_treated_as_exhausted(self):
        """If we cannot read the log we cannot prove we are under the cap, so
        we must not act."""
        store = FakeStore()
        store.fail_log_read = True
        rows = AlwaysWorks(store, mode=rb.MODE_ON).run_cycle()
        self.assertNotIn(rb.OUTCOME_ACTED, outcomes(rows))
        self.assertEqual(store.writes, [])


# ── property 2: circuit breaker ──────────────────────────────────────────────

class TestCircuitBreaker(unittest.TestCase):
    def test_breaker_trips_after_consecutive_failures(self):
        store = FakeStore()
        results = []
        for _ in range(rb.BREAKER_THRESHOLD + 2):
            results.append(outcomes(AlwaysFinds(store, mode=rb.MODE_ON).run_cycle()))
        flat = [o for r in results for o in r]
        self.assertIn(rb.OUTCOME_FAILED, flat)
        self.assertIn(rb.OUTCOME_TRIPPED, flat)

    def test_breaker_stays_tripped(self):
        store = FakeStore()
        for _ in range(rb.BREAKER_THRESHOLD):
            AlwaysFinds(store, mode=rb.MODE_ON).run_cycle()
        for _ in range(4):
            rows = AlwaysFinds(store, mode=rb.MODE_ON).run_cycle()
            self.assertIn(rb.OUTCOME_TRIPPED, outcomes(rows))
            self.assertNotIn(rb.OUTCOME_ACTED, outcomes(rows))

    def test_trip_is_recorded_as_an_alarm(self):
        store = FakeStore()
        for _ in range(rb.BREAKER_THRESHOLD + 1):
            AlwaysFinds(store, mode=rb.MODE_ON).run_cycle()
        self.assertTrue(any("circuit breaker OPEN" in a["detail"] for a in store.alarms))

    def test_a_success_resets_the_failure_streak(self):
        store = FakeStore()
        store.append_log({"remediator": "alwaysworks", "problem_key": "clears_fine",
                          "subject": "s1", "outcome": rb.OUTCOME_FAILED})
        store.append_log({"remediator": "alwaysworks", "problem_key": "clears_fine",
                          "subject": "s1", "outcome": rb.OUTCOME_ACTED})
        store.append_log({"remediator": "alwaysworks", "problem_key": "clears_fine",
                          "subject": "s1", "outcome": rb.OUTCOME_FAILED})
        bot = AlwaysWorks(store, mode=rb.MODE_ON)
        self.assertFalse(bot.breaker_tripped("s1"))

    def test_skips_do_not_trip_the_breaker(self):
        store = FakeStore()
        for _ in range(10):
            store.append_log({"remediator": "alwaysworks", "problem_key": "clears_fine",
                              "subject": "s1", "outcome": rb.OUTCOME_SKIPPED})
        self.assertFalse(AlwaysWorks(store, mode=rb.MODE_ON).breaker_tripped("s1"))


# ── property 3: no self-blocking ─────────────────────────────────────────────

class TestNoSelfBlocking(unittest.TestCase):
    def test_a_gate_guard_that_queues_work_is_refused(self):
        """This is the _self_heal_qa deadlock, refused at construction."""

        class Deadlock(rb.Remediator):
            name = "deadlock"
            problem_key = "x"
            guards_gate = "release"
            creates_queue_work = True

        with self.assertRaises(rb.SelfBlockingRemediator):
            Deadlock(FakeStore(), mode=rb.MODE_ON)

    def test_held_release_never_queues_work(self):
        self.assertFalse(rb.HeldReleaseRemediator.creates_queue_work)
        self.assertEqual(rb.HeldReleaseRemediator.guards_gate, "release")

    def test_held_release_clears_the_lineage_without_creating_a_task(self):
        store = FakeStore(tables={"release_holds": [
            {"id": "h1", "project": "p", "held_since": "2020-01-01T00:00:00",
             "fix_lineage": "old", "cleared": False},
        ]})
        rows = rb.HeldReleaseRemediator(store, mode=rb.MODE_ON).run_cycle()
        self.assertIn(rb.OUTCOME_ACTED, outcomes(rows))
        touched = {t for t, _m, _p in store.writes}
        self.assertNotIn("tasks", touched, "held_release must never queue a fix task")
        self.assertEqual(touched, {"release_holds"})

    def test_every_shipped_remediator_passes_the_check(self):
        for cls in rb.REMEDIATORS:
            with self.subTest(cls.name):
                rb.assert_cannot_self_block(cls)

    def test_stranded_branch_may_queue_because_it_guards_no_gate(self):
        self.assertTrue(rb.StrandedBranchRemediator.creates_queue_work)
        self.assertIsNone(rb.StrandedBranchRemediator.guards_gate)


# ── property 4: visible by default ───────────────────────────────────────────

class TestVisibility(unittest.TestCase):
    def test_heartbeat_on_a_no_op_cycle(self):
        class Idle(rb.Remediator):
            name = "idle"
            problem_key = "nothing"

        store = FakeStore()
        rows = Idle(store, mode=rb.MODE_ON).run_cycle()
        self.assertEqual(outcomes(rows), [rb.OUTCOME_HEARTBEAT])
        self.assertEqual(len(store.log), 1, "an idle cycle must still be visible")

    def test_heartbeat_even_when_the_remediator_is_off(self):
        store = FakeStore()
        rows = AlwaysWorks(store, mode=rb.MODE_OFF).run_cycle()
        self.assertEqual(outcomes(rows), [rb.OUTCOME_HEARTBEAT])

    def test_a_detector_crash_is_logged_not_swallowed(self):
        class Broken(rb.Remediator):
            name = "broken"
            problem_key = "boom"

            def detect(self):
                raise RuntimeError("kaboom")

        store = FakeStore()
        rows = Broken(store, mode=rb.MODE_ON).run_cycle()
        self.assertIn(rb.OUTCOME_FAILED, outcomes(rows))
        self.assertIn(rb.OUTCOME_HEARTBEAT, outcomes(rows))

    def test_every_row_names_its_remediator_and_problem_key(self):
        store = FakeStore()
        AlwaysWorks(store, mode=rb.MODE_ON).run_cycle()
        for row in store.log:
            self.assertTrue(row["remediator"])
            self.assertTrue(row["problem_key"])
            self.assertIn(row["outcome"], (
                rb.OUTCOME_ACTED, rb.OUTCOME_OBSERVED, rb.OUTCOME_SKIPPED,
                rb.OUTCOME_TRIPPED, rb.OUTCOME_ESCALATED, rb.OUTCOME_HEARTBEAT,
                rb.OUTCOME_FAILED,
            ))


# ── property 5: evidence or it did not happen ────────────────────────────────

class TestEvidenceGate(unittest.TestCase):
    def test_dispatching_is_not_success(self):
        store = FakeStore()
        rows = AlwaysFinds(store, mode=rb.MODE_ON).run_cycle()
        self.assertIn(rb.OUTCOME_FAILED, outcomes(rows))
        self.assertNotIn(rb.OUTCOME_ACTED, outcomes(rows))

    def test_success_records_the_re_measured_evidence(self):
        store = FakeStore()
        AlwaysWorks(store, mode=rb.MODE_ON).run_cycle()
        acted = [r for r in store.log if r["outcome"] == rb.OUTCOME_ACTED]
        self.assertEqual(len(acted), 1)
        self.assertIsNotNone(acted[0]["evidence_before"])
        self.assertIn("re-measured", acted[0]["detail"])

    def test_a_failed_re_measurement_is_a_failure_not_a_success(self):
        class Unmeasurable(AlwaysWorks):
            name = "unmeasurable"
            problem_key = "cannot_measure"

            def measure(self, subject):
                raise RuntimeError("source unavailable")

        store = FakeStore()
        rows = Unmeasurable(store, mode=rb.MODE_ON).run_cycle()
        self.assertIn(rb.OUTCOME_FAILED, outcomes(rows))

    def test_evidence_gap_only_demotes_never_promotes(self):
        store = FakeStore(tables={"tasks": [
            {"id": "t1", "slug": "s", "state": "DONE", "note": "",
             "commit_sha": "", "artifact_url": ""},
        ]})
        rb.EvidenceGapRemediator(store, mode=rb.MODE_ON).run_cycle()
        states = {p.get("state") for _t, _m, p in store.writes}
        self.assertEqual(states, {"PHANTOM_UNVERIFIED"})
        self.assertNotIn("MERGED", states)
        self.assertNotIn("DONE", states)

    def test_evidence_gap_leaves_tasks_that_have_evidence_alone(self):
        store = FakeStore(tables={"tasks": [
            {"id": "t1", "state": "DONE", "commit_sha": "abc123", "note": ""},
        ]})
        rows = rb.EvidenceGapRemediator(store, mode=rb.MODE_ON).run_cycle()
        self.assertEqual(outcomes(rows), [rb.OUTCOME_HEARTBEAT])
        self.assertEqual(store.writes, [])


# ── rollout: everything ships off / observe-only ─────────────────────────────

class TestObserveOnlyRollout(unittest.TestCase):
    def test_every_remediator_defaults_to_off(self):
        saved = {k: v for k, v in os.environ.items() if k.startswith("ORCH_REMEDIATOR_")}
        for k in saved:
            os.environ.pop(k, None)
        try:
            for cls in rb.REMEDIATORS:
                self.assertEqual(rb.mode_for(cls.name), rb.MODE_OFF)
        finally:
            os.environ.update(saved)

    def test_an_unrecognised_mode_string_is_off(self):
        os.environ["ORCH_REMEDIATOR_STALE_HOST"] = "maybe"
        try:
            self.assertEqual(rb.mode_for("stale_host"), rb.MODE_OFF)
        finally:
            os.environ.pop("ORCH_REMEDIATOR_STALE_HOST", None)

    def test_observe_mode_writes_nothing_to_tasks_or_controls(self):
        store = FakeStore(tables={"tasks": [
            {"id": "t1", "state": "DONE", "note": "", "commit_sha": ""},
        ]})
        bot = rb.build(rb.EvidenceGapRemediator, store=store, mode=rb.MODE_OBSERVE)
        rows = bot.run_cycle()
        self.assertIn(rb.OUTCOME_OBSERVED, outcomes(rows))
        self.assertEqual(store.writes, [], "observe mode must not write to tasks")
        self.assertEqual(store.tables["tasks"][0]["state"], "DONE")

    def test_observe_mode_still_logs_what_it_would_have_done(self):
        store = FakeStore(tables={"tasks": [
            {"id": "t1", "state": "DONE", "note": "", "commit_sha": ""},
        ]})
        rb.build(rb.EvidenceGapRemediator, store=store, mode=rb.MODE_OBSERVE).run_cycle()
        observed = [r for r in store.log if r["outcome"] == rb.OUTCOME_OBSERVED]
        self.assertEqual(len(observed), 1)
        self.assertTrue(observed[0]["action"])
        self.assertEqual(observed[0]["mode"], rb.MODE_OBSERVE)

    def test_a_subject_is_handled_at_most_once_per_cycle(self):
        """Two findings for one subject must not burn two of its three attempts."""

        class Duplicating(AlwaysWorks):
            name = "duplicating"
            problem_key = "dupes"

            def detect(self):
                return [{"subject": "s1", "evidence": {}},
                        {"subject": "s1", "evidence": {}}]

        store = FakeStore()
        rows = Duplicating(store, mode=rb.MODE_ON).run_cycle()
        self.assertEqual(outcomes(rows).count(rb.OUTCOME_ACTED), 1)

    def test_observe_mode_blocked_writes_are_recorded_for_inspection(self):
        store = FakeStore(tables={"tasks": [
            {"id": "t1", "state": "DONE", "note": "", "commit_sha": ""},
        ]})
        observe_store = rb.ObserveStore(store)
        observe_store.update("tasks", {"id": "t1"}, {"state": "X"})
        self.assertEqual(len(observe_store.blocked_writes), 1)
        self.assertEqual(store.writes, [])

    def test_off_mode_does_not_even_detect(self):
        class Loud(rb.Remediator):
            name = "loud"
            problem_key = "p"
            detected = 0

            def detect(self):
                Loud.detected += 1
                return [{"subject": "s"}]

        Loud(FakeStore(), mode=rb.MODE_OFF).run_cycle()
        self.assertEqual(Loud.detected, 0)


# ── bulk-sweep guard ─────────────────────────────────────────────────────────

class TestStrandedBranchIsNotABulkSweep(unittest.TestCase):
    def test_caps_requeues_per_run(self):
        old = [{"branch": f"agent/b{i}", "task_id": f"t{i}", "merged": False,
                "created_at": "2020-01-01T00:00:00"} for i in range(200)]
        store = FakeStore(tables={"agent_branches": old})
        bot = rb.StrandedBranchRemediator(store, mode=rb.MODE_OBSERVE)
        self.assertLessEqual(len(bot.detect()), rb.MAX_REQUEUE_PER_RUN)

    def test_fresh_branches_are_not_touched(self):
        now = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
        store = FakeStore(tables={"agent_branches": [
            {"branch": "agent/new", "task_id": "t1", "merged": False, "created_at": now},
        ]})
        self.assertEqual(rb.StrandedBranchRemediator(store, mode=rb.MODE_ON).detect(), [])

    def test_an_unparseable_timestamp_reads_as_brand_new(self):
        """A parse bug must never make a remediator act on everything at once."""
        self.assertEqual(rb._hours_since("not a date", time.time()), 0.0)
        self.assertEqual(rb._hours_since(None, time.time()), 0.0)


class TestStaleHost(unittest.TestCase):
    def test_success_requires_the_host_to_stop_claiming(self):
        store = FakeStore(tables={
            "hosts": [{"host": "h1", "commits_behind": 999, "claiming": True}],
            "controls": [{"host": "h1", "paused": False}],
        })
        rows = rb.StaleHostRemediator(store, mode=rb.MODE_ON).run_cycle()
        # The pause was written, but the host is still claiming, so NOT a success.
        self.assertIn(rb.OUTCOME_FAILED, outcomes(rows))
        self.assertIn("controls", {t for t, _m, _p in store.writes})

    def test_a_host_that_stops_claiming_is_a_success(self):
        hosts = [{"host": "h1", "commits_behind": 999, "claiming": True}]
        store = FakeStore(tables={"hosts": hosts, "controls": [{"host": "h1"}]})
        original_update = store.update

        def update(table, match, patch):
            result = original_update(table, match, patch)
            if table == "controls":
                hosts[0]["claiming"] = False
            return result

        store.update = update
        rows = rb.StaleHostRemediator(store, mode=rb.MODE_ON).run_cycle()
        self.assertIn(rb.OUTCOME_ACTED, outcomes(rows))


if __name__ == "__main__":
    unittest.main()
