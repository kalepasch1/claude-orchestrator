#!/usr/bin/env python3
"""Tests for self_review.py monthly subsystem audit."""
import sys, os, types, unittest, json, math
import unittest.mock
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_db_data = {}
_approvals = []

_db_mod = types.ModuleType("db")
def _fake_select(table, params=None):
    return list(_db_data.get(table, []))
def _fake_insert(table, row, **kw):
    if table == "approvals":
        _approvals.append(row)
    _db_data.setdefault(table, []).append(row)
_db_mod.select = _fake_select
_db_mod.insert = _fake_insert
_db_mod.update = lambda *a, **k: None
sys.modules["db"] = _db_mod

# Stub model deps
for mod_name in ["model_policy", "model_gateway", "claude_cli", "queue_counters", "prompt_assembler"]:
    m = types.ModuleType(mod_name)
    if mod_name == "queue_counters":
        m.exact_counts = lambda **kw: {"queued": 0, "running": 0}
    if mod_name == "prompt_assembler":
        m.stats = lambda **kw: {"count": 0, "avg_tokens": 0}
    sys.modules[mod_name] = m

import self_review


# ─────────────────────────────────────────────────────────────────────────────
# REWRITTEN 2026-08-24. Everything between this banner and TestStatsFunction used
# to exercise an API self_review.py has never had: _parse_schedule_table(),
# _score_job(), monthly_audit(), _PROTECTED_JOBS, and a report shaped
# {total_jobs, bottom_decile, all_scores}. `git log -S` finds no commit where any
# of those existed. 23 of the 25 tests raised AttributeError on import of the
# name; the suite had never once passed.
#
# The real surface is _load_schedule() / _fetch_kpi_contributions() /
# _fetch_incident_counts() / audit_subsystem_jobs() -> list of records /
# run_monthly_audit() -> writes subsystem_audits rows, with _INFRASTRUCTURE_JOBS
# as the protection set. These cover that.
# ─────────────────────────────────────────────────────────────────────────────

def _schedule(n=20):
    """A synthetic _SCHEDULE: (key, job, schedule_type, args) tuples."""
    return [(f"job-{i}", f"job_{i}.py", "interval", {"seconds": 60}) for i in range(n)]


class TestScheduleLoading(unittest.TestCase):
    def test_load_schedule_fails_soft_when_runner_has_no_schedule(self):
        stub = types.ModuleType("runner")           # no _SCHEDULE attribute
        with unittest.mock.patch.dict(sys.modules, {"runner": stub}):
            self.assertEqual(self_review._load_schedule(), [])

    def test_load_schedule_returns_a_copy_not_the_live_list(self):
        stub = types.ModuleType("runner")
        stub._SCHEDULE = _schedule(3)
        with unittest.mock.patch.dict(sys.modules, {"runner": stub}):
            loaded = self_review._load_schedule()
        loaded.append(("intruder", "x.py", "interval", {}))
        self.assertEqual(len(stub._SCHEDULE), 3, "mutating the result must not edit runner._SCHEDULE")


class TestContributionAndIncidentReads(unittest.TestCase):
    def setUp(self):
        _db_data.clear()

    def test_kpi_counts_only_outcomes_that_passed(self):
        _db_data["outcomes"] = [
            {"source": "a.py", "tests_passed": True},
            {"source": "a.py", "tests_passed": True},
            {"source": "a.py", "tests_passed": False},
            {"source": "b.py", "tests_passed": True},
        ]
        self.assertEqual(self_review._fetch_kpi_contributions(), {"a.py": 2.0, "b.py": 1.0})

    def test_incidents_count_every_row_regardless_of_severity(self):
        _db_data["incidents"] = [
            {"source": "a.py", "severity": "low"},
            {"source": "a.py", "severity": "critical"},
        ]
        self.assertEqual(self_review._fetch_incident_counts(), {"a.py": 2})

    def test_missing_tables_score_nothing_rather_than_raising(self):
        # Fail-soft is the documented contract: a table that does not exist yet must
        # mean "no evidence", not an exception out of a scheduled job.
        def _boom(*a, **k):
            raise RuntimeError("relation does not exist")
        with unittest.mock.patch.object(self_review.db, "select", _boom):
            self.assertEqual(self_review._fetch_kpi_contributions(), {})
            self.assertEqual(self_review._fetch_incident_counts(), {})


class TestAuditSubsystemJobs(unittest.TestCase):
    def setUp(self):
        _db_data.clear()
        del _approvals[:]

    def _run(self, schedule):
        stub = types.ModuleType("runner")
        stub._SCHEDULE = schedule
        with unittest.mock.patch.dict(sys.modules, {"runner": stub}):
            return self_review.audit_subsystem_jobs()

    def test_empty_schedule_produces_no_records(self):
        self.assertEqual(self._run([]), [])

    def test_every_scheduled_job_gets_exactly_one_record(self):
        records = self._run(_schedule(20))
        self.assertEqual(len(records), 20)
        self.assertEqual(len({r["key"] for r in records}), 20)

    def test_value_is_kpi_minus_weighted_incidents(self):
        _db_data["outcomes"] = [{"source": "job_1.py", "tests_passed": True}] * 5
        _db_data["incidents"] = [{"source": "job_1.py", "severity": "low"}] * 2
        record = next(r for r in self._run(_schedule(20)) if r["job"] == "job_1.py")
        self.assertEqual(record["kpi_contribution"], 5.0)
        self.assertEqual(record["incident_count"], 2)
        self.assertEqual(record["value"],
                         5.0 - 2 * self_review.INCIDENT_PENALTY_WEIGHT)

    def test_rank_one_is_the_most_valuable_job(self):
        _db_data["outcomes"] = [{"source": "job_7.py", "tests_passed": True}] * 9
        records = self._run(_schedule(20))
        self.assertEqual(records[0]["job"], "job_7.py")
        self.assertEqual(records[0]["rank"], 1)
        self.assertEqual([r["rank"] for r in records], list(range(1, 21)))

    def test_bottom_decile_is_flagged_for_disable_review(self):
        records = self._run(_schedule(20))
        flagged = [r for r in records if r["disable_recommendation"]]
        self.assertEqual(len(flagged), max(1, 20 // 10))
        self.assertTrue(all(r["rank"] > 20 - len(flagged) for r in flagged))

    def test_a_short_schedule_recommends_disabling_nothing(self):
        # Under ten jobs there is no meaningful decile; recommending a disable from a
        # sample that small is noise with consequences.
        records = self._run(_schedule(9))
        self.assertEqual([r for r in records if r["disable_recommendation"]], [])

    def test_infrastructure_is_never_recommended_for_disable(self):
        infra = sorted(self_review._INFRASTRUCTURE_JOBS)[:3]
        schedule = _schedule(20) + [(f"infra-{i}", job, "interval", {})
                                    for i, job in enumerate(infra)]
        # Give every non-infrastructure job value so the infra jobs sink to the bottom.
        _db_data["outcomes"] = [{"source": f"job_{i}.py", "tests_passed": True}
                                for i in range(20)]
        records = self._run(schedule)
        for rec in records:
            if rec["job"] in self_review._INFRASTRUCTURE_JOBS:
                self.assertTrue(rec["is_infrastructure"], rec["job"])
                self.assertFalse(rec["disable_recommendation"],
                                 f"{rec['job']} is infrastructure and must never be proposed for disable")


class TestRunMonthlyAudit(unittest.TestCase):
    def setUp(self):
        _db_data.clear()
        del _approvals[:]

    def _run(self, schedule):
        stub = types.ModuleType("runner")
        stub._SCHEDULE = schedule
        with unittest.mock.patch.dict(sys.modules, {"runner": stub}):
            return self_review.run_monthly_audit()

    def test_persists_one_row_per_job(self):
        records = self._run(_schedule(20))
        rows = _db_data.get("subsystem_audits", [])
        self.assertEqual(len(rows), len(records))
        self.assertEqual({r["job"] for r in rows}, {r["job"] for r in records})

    def test_persisted_row_carries_the_decision_fields(self):
        self._run(_schedule(20))
        row = _db_data["subsystem_audits"][0]
        for field in ("key", "job", "schedule_type", "kpi_contribution",
                      "incident_count", "value", "rank", "is_infrastructure",
                      "disable_recommendation"):
            self.assertIn(field, row)

    def test_writes_nothing_when_there_is_no_schedule(self):
        self.assertEqual(self._run([]), [])
        self.assertEqual(_db_data.get("subsystem_audits", []), [])

    def test_a_failing_write_does_not_abort_the_audit(self):
        # One bad row must not cost the other nineteen: this runs on a schedule and a
        # half-written audit that raised would look identical to one that never ran.
        calls = {"n": 0}
        real_insert = self_review.db.insert

        def flaky(table, row, **kw):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("transient write failure")
            return real_insert(table, row, **kw)

        with unittest.mock.patch.object(self_review.db, "insert", flaky):
            records = self._run(_schedule(20))
        self.assertEqual(len(records), 20)
        self.assertEqual(len(_db_data.get("subsystem_audits", [])), 19)


class TestStatsFunction(unittest.TestCase):
    def test_no_telemetry(self):
        summary, text = self_review.stats()
        self.assertIsNone(summary)

    def test_with_outcomes(self):
        global _db_data
        _db_data["outcomes"] = [
            {"model": "haiku", "tests_passed": True, "integrated": True,
             "usd": 0.01, "rate_limited": False, "attempts": 1}
        ]
        summary, text = self_review.stats()
        self.assertIsNotNone(summary)
        self.assertEqual(summary["tasks"], 1)


if __name__ == "__main__":
    unittest.main()
