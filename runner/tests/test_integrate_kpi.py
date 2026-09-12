#!/usr/bin/env python3
"""Focused tests for integrate_kpi — the deploy/integrate health number.

This module reports the KPI a human reads to decide whether the build is self-healing,
and it had no tests. The parts that would misreport silently are the two definitions
baked into compute(): which outcomes count as churn (excluded entirely) and what sits in
the denominator of merge_rate. Both are judgement calls encoded as code, and a KPI that
quietly changes its own definition is worse than no KPI — it moves, and nobody knows why.

compute() reads the database, so `db` is replaced with a stub. runner/tests/conftest.py
restores the real module afterwards, which is why that fixture exists.
"""
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import integrate_kpi


def _outcome(project, slug, tests_passed=False, integrated=False, usd=0.0):
    return {"project": project, "slug": slug, "tests_passed": tests_passed,
            "integrated": integrated, "usd": usd, "created_at": "2026-08-23T00:00:00"}


class _StubDb:
    """Serves the three tables compute() reads, in the order it asks for them."""

    def __init__(self, outcomes=None, tasks=None, projects=None):
        self.outcomes = outcomes or []
        self.tasks = tasks or []
        self.projects = projects or []

    def select(self, table, params=None):
        if table == "outcomes":
            return self.outcomes
        if table == "tasks":
            return self.tasks
        if table == "projects":
            return self.projects
        return []


class IsChurnTest(unittest.TestCase):
    """Churn is excluded from every count; what counts as churn is therefore load-bearing."""

    def test_continuation_and_mechanical_batches_are_churn(self):
        self.assertTrue(integrate_kpi._is_churn("cont-5f9e0e"))
        self.assertTrue(integrate_kpi._is_churn("batch-mech-01"))

    def test_real_work_is_not_churn(self):
        for slug in ["qafix-pareto-2080", "relfix-racefeed", "canary-gpt-mini-3", "content-pipeline"]:
            self.assertFalse(integrate_kpi._is_churn(slug), slug)

    def test_a_slug_merely_containing_cont_is_not_churn(self):
        # The prefix matters. 'content-pipeline' and 'contract-sync' are real work, and
        # treating them as churn would delete them from the KPI entirely.
        self.assertFalse(integrate_kpi._is_churn("contract-sync"))

    def test_missing_slug_is_not_churn(self):
        # Fail-soft: a row without a slug still counts, rather than vanishing.
        self.assertFalse(integrate_kpi._is_churn(None))
        self.assertFalse(integrate_kpi._is_churn(""))


class MergeRateTest(unittest.TestCase):
    """merge_rate = integrated / post-QA eligible. The denominator is the claim."""

    def setUp(self):
        self._real_db = sys.modules.get("db")

    def tearDown(self):
        if self._real_db is not None:
            sys.modules["db"] = self._real_db
            integrate_kpi.db = self._real_db

    def _compute(self, **kw):
        stub = _StubDb(**kw)
        integrate_kpi.db = stub
        return integrate_kpi.compute()

    def test_failed_drafting_attempts_do_not_dilute_merge_rate(self):
        # The docstring's promise: an attempt that never reached QA is attempt yield, not
        # mergeable work. Counting it in merge_rate would make a healthy train look broken
        # every time drafting got noisy.
        out = self._compute(outcomes=[
            _outcome("p", "a", tests_passed=True, integrated=True),
            _outcome("p", "b", tests_passed=False, integrated=False),
        ])
        self.assertEqual(out["p"]["completed"], 1)
        self.assertEqual(out["p"]["merge_rate"], 1.0)
        self.assertEqual(out["p"]["attempts"], 2)
        self.assertEqual(out["p"]["attempt_yield"], 0.5)

    def test_churn_is_excluded_from_every_count(self):
        out = self._compute(outcomes=[
            _outcome("p", "real", tests_passed=True, integrated=True),
            _outcome("p", "cont-noise", tests_passed=True, integrated=False),
        ])
        self.assertEqual(out["p"]["attempts"], 1)
        self.assertEqual(out["p"]["completed"], 1)
        self.assertEqual(out["p"]["merge_rate"], 1.0)

    def test_nothing_merged_reports_none_not_zero(self):
        # None says 'no denominator'; 0.0 would say 'we merged nothing out of many', and
        # the two demand different reactions.
        out = self._compute(outcomes=[_outcome("p", "a", tests_passed=False)])
        self.assertIsNone(out["p"]["merge_rate"])
        self.assertIsNone(out["p"]["usd_per_merge"])

    def test_usd_per_merge_is_the_north_star_and_divides_by_merges(self):
        out = self._compute(outcomes=[
            _outcome("p", "a", tests_passed=True, integrated=True, usd=3.0),
            _outcome("p", "b", tests_passed=True, integrated=False, usd=1.0),
        ])
        self.assertEqual(out["p"]["usd"], 4.0)
        self.assertEqual(out["p"]["usd_per_merge"], 4.0)

    def test_projects_are_reported_separately(self):
        out = self._compute(outcomes=[
            _outcome("alpha", "a", tests_passed=True, integrated=True),
            _outcome("beta", "b", tests_passed=True, integrated=False),
        ])
        self.assertEqual(out["alpha"]["merge_rate"], 1.0)
        self.assertEqual(out["beta"]["merge_rate"], 0.0)

    def test_self_heal_counts_attach_to_the_project_name(self):
        # Reported by project id in the tasks table but by name everywhere else; a
        # mismatch here shows up as a phantom project in the dashboard.
        out = self._compute(
            outcomes=[_outcome("alpha", "a", tests_passed=True, integrated=True)],
            tasks=[{"project_id": 1, "build_fail_count": 2, "force_coder": "claude"}],
            projects=[{"id": 1, "name": "alpha"}],
        )
        self.assertEqual(out["alpha"]["build_fail_open"], 1)
        self.assertEqual(out["alpha"]["coder_switched"], 1)

    def test_an_empty_window_reports_no_projects_rather_than_failing(self):
        self.assertEqual(self._compute(outcomes=[]), {})


if __name__ == "__main__":
    unittest.main()
