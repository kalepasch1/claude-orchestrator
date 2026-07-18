#!/usr/bin/env python3
"""Tests for monthly_subsystem_audit.py — 25 test cases covering:
- Scoring math (normal, zero, negative)
- Hard-excluded jobs never proposed
- Bottom decile calculation
- Zero-incident zero-KPI treated differently from negative
- Report generation
- Edge cases (empty lists, single job, all excluded)
"""
import os, sys, math, json
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from monthly_subsystem_audit import (
    HARD_EXCLUDED_JOBS, _is_hard_excluded, score_jobs, bottom_decile,
    build_report, _attribute_job,
)

import unittest

def _job(jid, script):
    return {"id": jid, "script": script}


class TestHardExcluded(unittest.TestCase):
    """Hard-excluded jobs must never be proposed for disable."""

    def test_billing_guard_excluded(self):
        self.assertTrue(_is_hard_excluded(_job("billingguard", "billingguard")))

    def test_pause_arbiter_excluded(self):
        self.assertTrue(_is_hard_excluded(_job("pause-arbiter-300", "pause_arbiter.py")))

    def test_worktreegc_excluded(self):
        self.assertTrue(_is_hard_excluded(_job("worktreegc", "worktreegc")))

    def test_resource_governor_excluded(self):
        self.assertTrue(_is_hard_excluded(_job("governor-60", "resource_governor.py")))

    def test_sentinel_excluded(self):
        self.assertTrue(_is_hard_excluded(_job("sentinel-300", "sentinel.py")))

    def test_selfheal_excluded(self):
        self.assertTrue(_is_hard_excluded(_job("selfheal-120", "selfheal")))

    def test_normal_job_not_excluded(self):
        self.assertFalse(_is_hard_excluded(_job("improve-900", "improve")))

    def test_canary_not_excluded(self):
        self.assertFalse(_is_hard_excluded(_job("codercanary-1800", "coder_canary.py")))


class TestScoring(unittest.TestCase):
    """Score formula: kpi_contribution - (incident_count * 10)."""

    def test_positive_kpi_no_incidents(self):
        jobs = [_job("a", "a.py")]
        outcomes = [{"integrated": True} for _ in range(5)]
        scored = score_jobs(jobs, outcomes=outcomes, incidents=[])
        self.assertEqual(scored[0]["kpi_contribution"], 5)
        self.assertEqual(scored[0]["incident_count"], 0)
        self.assertEqual(scored[0]["score"], 5)

    def test_zero_kpi_zero_incidents(self):
        jobs = [_job("a", "a.py")]
        scored = score_jobs(jobs, outcomes=[], incidents=[])
        self.assertEqual(scored[0]["score"], 0)
        self.assertEqual(scored[0]["kpi_contribution"], 0)
        self.assertEqual(scored[0]["incident_count"], 0)

    def test_incidents_reduce_score(self):
        jobs = [_job("mytest", "mytest.py")]
        incidents = [{"type": "pause", "source": "mytest", "at": "2026-01-01"}]
        scored = score_jobs(jobs, outcomes=[], incidents=incidents)
        self.assertEqual(scored[0]["incident_count"], 1)
        self.assertEqual(scored[0]["score"], -10)

    def test_multiple_incidents(self):
        jobs = [_job("bad-job", "bad.py")]
        incidents = [
            {"type": "pause", "source": "bad-job triggered pause", "at": "2026-01-01"},
            {"type": "pause", "source": "bad-job again", "at": "2026-01-02"},
        ]
        scored = score_jobs(jobs, outcomes=[], incidents=incidents)
        self.assertEqual(scored[0]["incident_count"], 2)
        self.assertEqual(scored[0]["score"], -20)

    def test_kpi_offsets_incidents(self):
        jobs = [_job("mixed", "mixed.py")]
        outcomes = [{"integrated": True} for _ in range(15)]
        incidents = [{"type": "pause", "source": "mixed caused issue", "at": "2026-01-01"}]
        scored = score_jobs(jobs, outcomes=outcomes, incidents=incidents)
        self.assertEqual(scored[0]["score"], 15 - 10)  # 5

    def test_excluded_job_gets_inf_score(self):
        jobs = [_job("billingguard", "billingguard")]
        scored = score_jobs(jobs, outcomes=[], incidents=[])
        self.assertEqual(scored[0]["score"], float("inf"))
        self.assertTrue(scored[0]["is_excluded"])

    def test_sorting_worst_first(self):
        jobs = [_job("good", "good.py"), _job("bad", "bad.py")]
        outcomes = [{"integrated": True} for _ in range(10)]
        incidents = [{"type": "pause", "source": "bad caused it", "at": "2026-01-01"}]
        scored = score_jobs(jobs, outcomes=outcomes, incidents=incidents)
        self.assertEqual(scored[0]["job_id"], "bad")
        self.assertEqual(scored[1]["job_id"], "good")

    def test_excluded_sorts_last(self):
        jobs = [_job("billingguard", "billingguard"), _job("normal", "normal.py")]
        scored = score_jobs(jobs, outcomes=[], incidents=[])
        self.assertEqual(scored[-1]["job_id"], "billingguard")


class TestBottomDecile(unittest.TestCase):
    """Bottom decile proposals."""

    def test_empty_returns_empty(self):
        self.assertEqual(bottom_decile([]), [])

    def test_single_job_negative_score_proposed(self):
        scored = [{"job_id": "a", "script": "a.py", "score": -5, "is_excluded": False,
                   "kpi_contribution": 0, "incident_count": 1, "reason": ""}]
        result = bottom_decile(scored)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["job_id"], "a")

    def test_single_job_positive_score_not_proposed(self):
        scored = [{"job_id": "a", "script": "a.py", "score": 10, "is_excluded": False,
                   "kpi_contribution": 10, "incident_count": 0, "reason": ""}]
        result = bottom_decile(scored)
        self.assertEqual(len(result), 0)

    def test_excluded_never_proposed(self):
        scored = [{"job_id": "billingguard", "script": "billingguard", "score": float("inf"),
                   "is_excluded": True, "kpi_contribution": 0, "incident_count": 0, "reason": ""}]
        result = bottom_decile(scored)
        self.assertEqual(len(result), 0)

    def test_ten_jobs_one_bottom(self):
        scored = []
        for i in range(10):
            scored.append({"job_id": f"j{i}", "script": f"j{i}.py",
                          "score": i * 10, "is_excluded": False,
                          "kpi_contribution": i * 10, "incident_count": 0, "reason": ""})
        scored.sort(key=lambda x: x["score"])
        result = bottom_decile(scored)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["job_id"], "j0")

    def test_zero_score_jobs_proposed(self):
        """Zero KPI + zero incidents = score 0, which IS in bottom decile if it's the lowest."""
        scored = [
            {"job_id": "zero", "script": "z.py", "score": 0, "is_excluded": False,
             "kpi_contribution": 0, "incident_count": 0, "reason": ""},
            {"job_id": "good", "script": "g.py", "score": 50, "is_excluded": False,
             "kpi_contribution": 50, "incident_count": 0, "reason": ""},
        ]
        result = bottom_decile(scored)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["job_id"], "zero")

    def test_negative_vs_zero_ordering(self):
        """Jobs with negative score rank below zero-score jobs."""
        scored = [
            {"job_id": "neg", "script": "n.py", "score": -10, "is_excluded": False,
             "kpi_contribution": 0, "incident_count": 1, "reason": ""},
            {"job_id": "zero", "script": "z.py", "score": 0, "is_excluded": False,
             "kpi_contribution": 0, "incident_count": 0, "reason": ""},
            {"job_id": "pos", "script": "p.py", "score": 10, "is_excluded": False,
             "kpi_contribution": 10, "incident_count": 0, "reason": ""},
        ]
        result = bottom_decile(scored)
        self.assertEqual(result[0]["job_id"], "neg")

    def test_all_excluded_returns_empty(self):
        scored = [
            {"job_id": "billingguard", "script": "billingguard", "score": float("inf"),
             "is_excluded": True, "kpi_contribution": 0, "incident_count": 0, "reason": ""},
            {"job_id": "governor-60", "script": "resource_governor.py", "score": float("inf"),
             "is_excluded": True, "kpi_contribution": 0, "incident_count": 0, "reason": ""},
        ]
        result = bottom_decile(scored)
        self.assertEqual(len(result), 0)


class TestReport(unittest.TestCase):
    """Report generation."""

    def test_report_contains_header(self):
        scored = [{"job_id": "a", "script": "a.py", "score": 5, "is_excluded": False,
                   "kpi_contribution": 5, "incident_count": 0, "reason": ""}]
        report = build_report(scored)
        self.assertIn("Monthly Subsystem Audit Report", report)

    def test_report_contains_job(self):
        scored = [{"job_id": "mytest-300", "script": "mytest.py", "score": 3, "is_excluded": False,
                   "kpi_contribution": 3, "incident_count": 0, "reason": ""}]
        report = build_report(scored)
        self.assertIn("mytest-300", report)
        self.assertIn("mytest.py", report)

    def test_report_excluded_marked(self):
        scored = [{"job_id": "billingguard", "script": "billingguard", "score": float("inf"),
                   "is_excluded": True, "kpi_contribution": 0, "incident_count": 0, "reason": ""}]
        report = build_report(scored)
        self.assertIn("EXCLUDED", report)

    def test_report_empty_list(self):
        report = build_report([])
        self.assertIn("Total jobs: 0", report)


class TestAttributeJob(unittest.TestCase):
    """Individual job attribution."""

    def test_no_matching_incidents(self):
        job = _job("alpha", "alpha.py")
        incidents = [{"type": "pause", "source": "beta caused it", "at": "2026-01-01"}]
        attr = _attribute_job(job, [], incidents)
        self.assertEqual(attr["incident_count"], 0)

    def test_matching_incident_by_job_id(self):
        job = _job("alpha-300", "alpha.py")
        incidents = [{"type": "pause", "source": "alpha-300 triggered pause", "at": "2026-01-01"}]
        attr = _attribute_job(job, [], incidents)
        self.assertEqual(attr["incident_count"], 1)

    def test_matching_incident_by_script(self):
        job = _job("x-600", "mymodule.py")
        incidents = [{"type": "pause", "source": "mymodule error", "at": "2026-01-01"}]
        attr = _attribute_job(job, [], incidents)
        self.assertEqual(attr["incident_count"], 1)

    def test_kpi_from_integrated_outcomes(self):
        job = _job("a", "a.py")
        outcomes = [{"integrated": True}, {"integrated": False}, {"integrated": True}]
        attr = _attribute_job(job, outcomes, [])
        self.assertEqual(attr["kpi_contribution"], 2)

    def test_excluded_flag_set(self):
        job = _job("billingguard", "billingguard")
        attr = _attribute_job(job, [], [])
        self.assertTrue(attr["is_excluded"])

    def test_normal_not_excluded(self):
        job = _job("improve-900", "improve")
        attr = _attribute_job(job, [], [])
        self.assertFalse(attr["is_excluded"])


if __name__ == "__main__":
    unittest.main()
