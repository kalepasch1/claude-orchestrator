#!/usr/bin/env python3
"""Production scheduling + SLOs for the compliance subsystem.

Round 8 found these modules had an API surface but no clock. The load-bearing
case is the evidence outbox: `evidence_bus.flush()` is the durable buffer that
keeps a DB outage from discarding evidence, and it had one ad-hoc caller and
no schedule, so a spooled backlog drained only by accident.

Three things are pinned here:

* registration — the jobs exist in `periodic.JOBS` and in `runner._SCHEDULE`,
  because a job registered in only one of those two places never runs (that is
  how quarantine_gc sat dead in the JOBS dict);
* lock behavior — jobs go through the existing per-job flock rather than
  reimplementing it, and overlapping invocations skip instead of double-running;
* safe failure — every job returns a dict and never raises into the scheduler,
  and none of them mutate protected task state.
"""
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import compliance_periodic as cp
import evidence_bus


COMPLIANCE_JOBS = ("complianceoutbox", "compliancescorecard",
                   "complianceanomaly", "compliancehealth")

_RUNNER_PY = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "runner.py")


def _runner_literal(name):
    """Read a module-level literal out of runner.py without importing it.

    `import runner` resolves to the runner/ package, not runner.py, and
    executing runner.py for a registration check would start the world. The
    schedule and the paused-safe set are plain literals, so parse them.
    """
    import ast
    with open(_RUNNER_PY, encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=_RUNNER_PY)
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == name:
                return ast.literal_eval(node.value)
    raise AssertionError(f"{name} not found as a module-level literal in runner.py")


class _OutboxCase(unittest.TestCase):
    """Point evidence_bus at a temp outbox so no real spool is touched."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.outbox = os.path.join(self._tmp.name, "evidence-outbox.jsonl")
        self._orig = evidence_bus._OUTBOX
        evidence_bus._OUTBOX = self.outbox
        self.addCleanup(lambda: setattr(evidence_bus, "_OUTBOX", self._orig))

    def _spool(self, rows):
        with open(self.outbox, "w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row) + "\n")

    def _lines(self):
        if not os.path.exists(self.outbox):
            return []
        with open(self.outbox, encoding="utf-8") as fh:
            return [ln for ln in fh.read().splitlines() if ln.strip()]


class TestJobRegistration(unittest.TestCase):
    """A job in only one registry never runs. Assert both."""

    def test_every_job_is_in_periodic_jobs(self):
        import periodic
        for job in COMPLIANCE_JOBS:
            self.assertIn(job, periodic.JOBS, f"{job} missing from periodic.JOBS")

    def test_every_job_is_scheduled_in_runner(self):
        scheduled = {entry[1] for entry in _runner_literal("_SCHEDULE")}
        for job in COMPLIANCE_JOBS:
            self.assertIn(job, scheduled, f"{job} missing from runner._SCHEDULE")

    def test_registered_jobs_are_callable_with_no_arguments(self):
        import periodic
        for job in COMPLIANCE_JOBS:
            self.assertTrue(callable(periodic.JOBS[job]))
            self.assertEqual(
                periodic.JOBS[job].__code__.co_argcount, 0,
                f"{job} must match the zero-arg periodic job contract")

    def test_schedule_intervals_match_documented_defaults(self):
        actual = {entry[1]: entry[3] for entry in _runner_literal("_SCHEDULE")
                  if entry[1] in COMPLIANCE_JOBS and entry[2] == "interval"}
        self.assertEqual(actual, cp.DEFAULT_INTERVALS,
                         "documented intervals must match what is scheduled")

    def test_schedule_keys_are_unique(self):
        """Duplicate keys silently shadow each other in _sched_last."""
        keys = [entry[0] for entry in _runner_literal("_SCHEDULE")
                if entry[1] in COMPLIANCE_JOBS]
        self.assertEqual(len(keys), len(set(keys)))

    def test_jobs_run_while_paused(self):
        """Observation must not stop when the fleet pauses."""
        safe = _runner_literal("_SAFE_WHEN_PAUSED")
        for job in COMPLIANCE_JOBS:
            self.assertIn(job, safe)


class TestLockBehavior(unittest.TestCase):
    """Jobs inherit periodic's flock; they must not reimplement it."""

    def test_job_runs_through_the_shared_lock_helper(self):
        import periodic
        with patch.object(periodic, "_invoke_job", return_value={"ok": True}) as invoked:
            outcome = periodic._run_job_locked("compliancehealth")
        invoked.assert_called_once_with("compliancehealth")
        self.assertEqual(outcome, {"ok": True})

    def test_contended_lock_skips_instead_of_double_running(self):
        """A held lock must skip the job, not run it a second time.

        Contention is simulated rather than taken for real: registering this
        process as the live lock holder can make the wedge reaper SIGTERM the
        test runner itself once the skip counter crosses ORCH_PERIODIC_WEDGE_SKIPS.
        """
        import periodic
        if periodic.fcntl is None:
            self.skipTest("flock unavailable on this platform")

        with patch.object(periodic.fcntl, "flock", side_effect=BlockingIOError()), \
             patch.object(periodic, "_reap_stale_holder", return_value=False), \
             patch.object(periodic, "_invoke_job") as invoked:
            outcome = periodic._run_job_locked("complianceoutbox")

        invoked.assert_not_called()
        self.assertIsInstance(outcome, periodic._Skipped)

    def test_lock_is_released_so_the_next_tick_can_run(self):
        """Back-to-back invocations must both run once the lock is free."""
        import periodic
        with patch.object(periodic, "_invoke_job", return_value={"ok": True}) as invoked:
            periodic._run_job_locked("compliancehealth")
            periodic._run_job_locked("compliancehealth")
        self.assertEqual(invoked.call_count, 2)

    def test_module_does_not_define_its_own_lock(self):
        source = open(cp.__file__, encoding="utf-8").read()
        self.assertNotIn("flock", source,
                         "compliance_periodic must reuse periodic's lock, not add one")


class TestOutboxFlushJob(_OutboxCase):

    def test_delivers_and_empties_the_outbox(self):
        self._spool([{"idempotency_key": f"k{i}", "app": "a"} for i in range(3)])
        with patch.object(evidence_bus.db, "insert", return_value=None):
            result = cp.run_outbox_flush()
        self.assertEqual(result["delivered"], 3)
        self.assertEqual(result["pending"], 0)
        self.assertEqual(self._lines(), [])

    def test_undelivered_rows_are_retained(self):
        self._spool([{"idempotency_key": "k1"}])
        with patch.object(evidence_bus.db, "insert", side_effect=RuntimeError("db down")):
            result = cp.run_outbox_flush()
        self.assertEqual(result["delivered"], 0)
        self.assertEqual(result["pending"], 1, "a failed delivery must not lose the row")

    def test_rows_beyond_the_flush_limit_survive(self):
        """The regression: the old flush rewrote the file from a truncated read."""
        self._spool([{"idempotency_key": f"k{i}"} for i in range(10)])
        with patch.object(evidence_bus.db, "insert", return_value=None), \
             patch.object(cp, "OUTBOX_FLUSH_LIMIT", 4):
            result = cp.run_outbox_flush()
        self.assertEqual(result["delivered"], 4)
        self.assertEqual(len(self._lines()), 6,
                         "un-attempted rows must be carried forward, not destroyed")

    def test_malformed_line_does_not_raise_or_vanish(self):
        with open(self.outbox, "w", encoding="utf-8") as fh:
            fh.write('{"idempotency_key": "good"}\n')
            fh.write("{ this is not json\n")
        with patch.object(evidence_bus.db, "insert", return_value=None):
            result = cp.run_outbox_flush()
        self.assertEqual(result["delivered"], 1)
        self.assertEqual(result["corrupt"], 1)
        self.assertIn("corrupt_rows", result["breached"])
        self.assertEqual(len(self._lines()), 1, "the corrupt line is kept, not dropped")

    def test_deep_backlog_breaches_slo_and_alerts(self):
        self._spool([{"idempotency_key": f"k{i}"} for i in range(6)])
        with patch.object(evidence_bus.db, "insert", side_effect=RuntimeError("down")), \
             patch.object(cp, "OUTBOX_BACKLOG_MAX", 2), \
             patch.object(cp, "_alert") as alert:
            result = cp.run_outbox_flush()
        self.assertIn("backlog_depth", result["breached"])
        alert.assert_called_once()

    def test_healthy_backlog_does_not_alert(self):
        self._spool([{"idempotency_key": "k1"}])
        with patch.object(evidence_bus.db, "insert", return_value=None), \
             patch.object(cp, "_alert") as alert:
            cp.run_outbox_flush()
        alert.assert_not_called()

    def test_missing_outbox_file_is_a_clean_noop(self):
        result = cp.run_outbox_flush()
        self.assertEqual(result["delivered"], 0)
        self.assertIsNone(result["error"])
        self.assertEqual(result["breached"], [])


class TestSafeFailureHandling(_OutboxCase):
    """No job may raise into the scheduler."""

    def test_flush_exception_is_reported_not_raised(self):
        with patch.object(evidence_bus, "flush", side_effect=RuntimeError("boom")):
            result = cp.run_outbox_flush()
        self.assertIn("boom", result["error"])

    def test_scorecard_handles_no_telemetry(self):
        with patch.object(cp, "_fleet_telemetry", return_value={}):
            result = cp.run_scorecard_refresh()
        self.assertEqual(result["apps"], 0)
        self.assertIsNotNone(result["error"])

    def test_scorecard_engine_failure_is_contained(self):
        import cade_scorecard
        with patch.object(cp, "_fleet_telemetry", return_value={"app": {"throughput": 1.0}}), \
             patch.object(cade_scorecard, "fleet_scorecard", side_effect=ValueError("bad")):
            result = cp.run_scorecard_refresh()
        self.assertIn("bad", result["error"])

    def test_telemetry_survives_an_unreachable_db(self):
        import db
        with patch.object(db, "select", side_effect=RuntimeError("no db")):
            self.assertEqual(cp._fleet_telemetry(), {})

    def test_anomaly_sweep_survives_an_unreachable_db(self):
        import db
        with patch.object(db, "select", side_effect=RuntimeError("no db")):
            result = cp.run_anomaly_check()
        self.assertEqual(result["checked"], 0)
        self.assertEqual(result["anomalies"], [])

    def test_alert_channel_failure_never_propagates(self):
        import notify
        with patch.object(notify, "send", side_effect=RuntimeError("slack down")):
            cp._alert("headline", "detail")  # must not raise

    def test_metric_emit_failure_never_propagates(self):
        import events
        with patch.object(events, "emit", side_effect=RuntimeError("disk full")):
            cp._emit("compliance:test", value=1)  # must not raise

    def test_every_job_returns_a_dict(self):
        import db
        with patch.object(db, "select", return_value=[]), \
             patch.object(evidence_bus.db, "insert", return_value=None):
            for job in (cp.run_outbox_flush, cp.run_scorecard_refresh,
                        cp.run_anomaly_check, cp.run_health):
                self.assertIsInstance(job(), dict, f"{job.__name__} must return a dict")


class TestNoProtectedStateMutation(_OutboxCase):
    """These jobs observe and deliver. They must never touch task state."""

    def test_jobs_never_update_tasks(self):
        import db
        with patch.object(db, "select", return_value=[]), \
             patch.object(db, "update") as update, \
             patch.object(evidence_bus.db, "insert", return_value=None):
            cp.run_outbox_flush()
            cp.run_scorecard_refresh()
            cp.run_anomaly_check()
            cp.run_health()
        update.assert_not_called()

    def test_only_evidence_and_metric_tables_are_written(self):
        import db
        written = []
        with patch.object(db, "select", return_value=[]), \
             patch.object(db, "insert", side_effect=lambda t, r: written.append(t)), \
             patch.object(evidence_bus.db, "insert", side_effect=lambda t, r: written.append(t)):
            cp.run_outbox_flush()
            cp.run_anomaly_check()
        self.assertNotIn("tasks", written)


class TestHealthEndpoint(_OutboxCase):

    def test_reports_every_required_dimension(self):
        with patch.object(evidence_bus, "events", return_value=[]):
            snapshot = cp.health()
        for key in ("outbox", "consumer_lag", "freshness"):
            self.assertIn(key, snapshot["checks"])
        self.assertIn(snapshot["status"], ("ok", "degraded", "unknown"))

    def test_backlog_age_is_surfaced(self):
        self._spool([{"idempotency_key": "k", "created_at": "2020-01-01T00:00:00+00:00"}])
        with patch.object(evidence_bus, "events", return_value=[]):
            snapshot = cp.health()
        self.assertIsNotNone(snapshot["checks"]["outbox"]["oldest_age_s"])
        self.assertIn("outbox_age", snapshot["breached"])
        self.assertEqual(snapshot["status"], "degraded")

    def test_consumer_lag_breach_is_detected(self):
        self._spool([{"idempotency_key": f"k{i}"} for i in range(5)])
        with patch.object(cp, "CONSUMER_LAG_MAX", 2), \
             patch.object(evidence_bus, "events", return_value=[]):
            snapshot = cp.health()
        self.assertIn("consumer_lag", snapshot["breached"])

    def test_stale_evidence_is_detected(self):
        with patch.object(evidence_bus, "events",
                          return_value=[{"created_at": "2020-01-01T00:00:00+00:00"}]):
            snapshot = cp.health()
        self.assertIn("stale_evidence", snapshot["breached"])

    def test_clean_subsystem_reports_ok(self):
        with patch.object(evidence_bus, "events", return_value=[]):
            snapshot = cp.health()
        self.assertEqual(snapshot["status"], "ok")
        self.assertEqual(snapshot["breached"], [])

    def test_health_never_writes(self):
        import db
        with patch.object(db, "insert") as insert, patch.object(db, "update") as update, \
             patch.object(evidence_bus, "events", return_value=[]):
            cp.health()
        insert.assert_not_called()
        update.assert_not_called()

    def test_unreadable_probe_is_unknown_not_ok(self):
        with patch.object(evidence_bus, "backlog", side_effect=RuntimeError("io")), \
             patch.object(evidence_bus, "events", return_value=[]):
            snapshot = cp.health()
        self.assertEqual(snapshot["status"], "unknown")


class TestReadinessRoute(_OutboxCase):

    def test_liveness_stays_ok_while_degraded(self):
        from compliance_api_gateway import gateway
        with patch.object(cp, "health", return_value={"status": "degraded", "breached": ["x"]}):
            status, _body = gateway.dispatch("GET", "/compliance/v1/health")
        self.assertEqual(status, 200, "liveness must not fail on a backlog")

    def test_readiness_returns_503_when_degraded(self):
        from compliance_api_gateway import gateway
        with patch.object(cp, "health",
                          return_value={"status": "degraded", "breached": ["outbox_backlog"]}):
            status, body = gateway.dispatch("GET", "/compliance/v1/readiness")
        self.assertEqual(status, 503)
        self.assertEqual(body["status"], "degraded")

    def test_readiness_returns_200_when_ok(self):
        from compliance_api_gateway import gateway
        with patch.object(cp, "health", return_value={"status": "ok", "breached": []}):
            status, body = gateway.dispatch("GET", "/compliance/v1/readiness")
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "ok")

    def test_readiness_never_500s_on_probe_failure(self):
        from compliance_api_gateway import gateway
        with patch.object(cp, "health", side_effect=RuntimeError("probe exploded")):
            status, body = gateway.dispatch("GET", "/compliance/v1/readiness")
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "unknown")


if __name__ == "__main__":
    unittest.main()
