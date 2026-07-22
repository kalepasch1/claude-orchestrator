#!/usr/bin/env python3
"""Tests for self_review.py monthly subsystem audit."""
import sys, os, types, unittest, json, math
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


class TestParseScheduleTable(unittest.TestCase):
    def test_parses_jobs(self):
        jobs = self_review._parse_schedule_table()
        self.assertGreater(len(jobs), 50, "Should find 50+ jobs in runner.py schedule")

    def test_job_has_id_and_script(self):
        jobs = self_review._parse_schedule_table()
        for j in jobs[:5]:
            self.assertIn("id", j)
            self.assertIn("script", j)
            self.assertTrue(len(j["id"]) > 0)

    def test_known_jobs_present(self):
        jobs = self_review._parse_schedule_table()
        ids = {j["id"] for j in jobs}
        self.assertIn("scoreboard-600", ids)
        self.assertIn("train-60", ids)
        self.assertIn("billing-300", ids)


class TestProtectedJobs(unittest.TestCase):
    def test_billing_guard_protected(self):
        job = {"id": "billingguard", "script": "billingguard"}
        s = self_review._score_job(job, {}, {})
        self.assertTrue(s["protected"])
        self.assertEqual(s["score"], float("inf"))

    def test_kill_switch_protected(self):
        job = {"id": "killswitch", "script": "kill_switch"}
        s = self_review._score_job(job, {}, {})
        self.assertTrue(s["protected"])

    def test_pause_arbiter_protected(self):
        job = {"id": "pause-arbiter-300", "script": "pause_arbiter.py"}
        s = self_review._score_job(job, {}, {})
        self.assertTrue(s["protected"])

    def test_worktreegc_protected(self):
        job = {"id": "worktreegc", "script": "worktreegc"}
        s = self_review._score_job(job, {}, {})
        self.assertTrue(s["protected"])

    def test_normal_job_not_protected(self):
        job = {"id": "anomaly-3600", "script": "anomaly.py"}
        s = self_review._score_job(job, {}, {})
        self.assertFalse(s["protected"])


class TestJobScoring(unittest.TestCase):
    def test_zero_incidents_neutral_score(self):
        job = {"id": "test-job", "script": "test.py"}
        s = self_review._score_job(job, {}, {})
        self.assertEqual(s["score"], 50.0)
        self.assertEqual(s["incidents"], 0)

    def test_incidents_reduce_score(self):
        job = {"id": "bad-job", "script": "bad.py"}
        incidents = {"bad.py": 3}
        s = self_review._score_job(job, {}, incidents)
        self.assertEqual(s["score"], 20.0)  # 50 - 3*10
        self.assertEqual(s["incidents"], 3)

    def test_incidents_by_job_id(self):
        job = {"id": "my-job", "script": "my.py"}
        incidents = {"my-job": 2}
        s = self_review._score_job(job, {}, incidents)
        self.assertEqual(s["incidents"], 2)

    def test_zero_kpi_zero_incidents_not_punished(self):
        """Infrastructure jobs with no KPI but no incidents stay neutral."""
        job = {"id": "infra-job", "script": "infra.py"}
        s = self_review._score_job(job, {}, {})
        self.assertGreaterEqual(s["score"], 50.0)

    def test_negative_contribution_vs_zero(self):
        """Job with incidents scores lower than job with zero incidents."""
        good = {"id": "good", "script": "good.py"}
        bad = {"id": "bad", "script": "bad.py"}
        s_good = self_review._score_job(good, {}, {})
        s_bad = self_review._score_job(bad, {}, {"bad.py": 5})
        self.assertGreater(s_good["score"], s_bad["score"])


class TestMonthlyAudit(unittest.TestCase):
    def setUp(self):
        global _db_data, _approvals
        _db_data = {}
        _approvals = []

    def test_audit_returns_report(self):
        r = self_review.monthly_audit()
        self.assertIsNotNone(r)
        self.assertIn("total_jobs", r)
        self.assertIn("bottom_decile", r)
        self.assertIn("all_scores", r)

    def test_audit_files_one_approval(self):
        self_review.monthly_audit()
        material_approvals = [a for a in _approvals if a.get("kind") == "material"]
        self.assertEqual(len(material_approvals), 1, "Should file exactly 1 material approval card")

    def test_audit_approval_is_material(self):
        self_review.monthly_audit()
        self.assertTrue(any(a["kind"] == "material" for a in _approvals))

    def test_bottom_decile_excludes_protected(self):
        r = self_review.monthly_audit()
        for j in r["bottom_decile"]:
            self.assertNotIn(j["id"], self_review._PROTECTED_JOBS)
            self.assertNotIn(j["script"], self_review._PROTECTED_JOBS)

    def test_total_jobs_count(self):
        r = self_review.monthly_audit()
        self.assertGreater(r["total_jobs"], 50)

    def test_protected_jobs_counted(self):
        r = self_review.monthly_audit()
        self.assertGreater(r["protected_jobs"], 0)

    def test_bottom_decile_size(self):
        r = self_review.monthly_audit()
        expected = max(1, math.ceil(r["scored_jobs"] * 0.1))
        self.assertEqual(r["bottom_decile_count"], expected)

    def test_all_scores_has_all_jobs(self):
        r = self_review.monthly_audit()
        self.assertEqual(len(r["all_scores"]), r["total_jobs"])

    def test_protected_in_all_scores(self):
        r = self_review.monthly_audit()
        protected = [s for s in r["all_scores"] if s["score"] == "protected"]
        self.assertGreater(len(protected), 0)

    def test_audit_approval_detail_is_json(self):
        self_review.monthly_audit()
        material = [a for a in _approvals if a.get("kind") == "material"]
        if material:
            detail = json.loads(material[0]["detail"])
            self.assertIn("bottom_decile", detail)


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
