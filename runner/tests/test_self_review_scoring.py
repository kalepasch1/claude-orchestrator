"""Tests for score_job_kpi() and count_job_incidents() in self_review.py.

REWRITTEN 2026-08-24 (transport of the db fake only; the assertions are the same
behaviours, tightened).

This file used to install a fake `db` into `sys.modules` at import time and never remove
it. That is order-dependent in both directions:

  * it only works if `self_review` has not already been imported. Anything that imports
    it first — runner/tests/test_monthly_audit.py exercises the other half of the same
    module — leaves `self_review.db` bound to the REAL db, the `_db_responses` table is
    then consulted by nobody, and nine tests here fail against live-shaped defaults. In
    isolation the file passed; in-suite it went red, which is the worst of both.
  * the stub outlives this module, so every later test in the session gets a `db` whose
    select() returns [] — a fake nobody asked for.

The fake is now scoped to the call under test and applied to `self_review.db`, the name
the functions actually resolve, so import order stops mattering and nothing survives the
test. `sys.modules` is not touched.
"""
import contextlib
import os
import sys
import types
import unittest.mock as mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import self_review
from self_review import score_job_kpi, count_job_incidents, INFRA_JOBS

# What self_review.db was bound to before this file ran. The leak check at the bottom
# compares against this rather than sys.modules["db"], because other files in this suite
# still install their own module-level db stubs and that is not what is under test here.
_DB_AT_IMPORT = self_review.db


# ── Helpers ──────────────────────────────────────────────────────────────────

@contextlib.contextmanager
def _db(**tables):
    """Answer db.select() per table for the duration of the block.

    A value may be a list of rows, or a callable(table, params) — used to make one
    table raise while the others still answer, which is the fail-soft path.
    """
    def _select(table, params=None):
        value = tables.get(table, [])
        if callable(value):
            return value(table, params)
        return value

    stub = types.SimpleNamespace(
        select=_select,
        insert=lambda *a, **kw: None,
        update=lambda *a, **kw: None,
        count=lambda *a, **kw: 0,
    )
    # Patch the module attribute, not sys.modules: score_job_kpi resolves `db` in
    # self_review's globals at call time, and mock.patch puts the real one back.
    with mock.patch.object(self_review, "db", stub):
        yield


# ── score_job_kpi tests ─────────────────────────────────────────────────────

def test_kpi_empty_name_returns_zero():
    """Empty/None job name returns 0.0."""
    assert score_job_kpi("") == 0.0
    assert score_job_kpi(None) == 0.0


def test_kpi_no_outcomes_returns_zero():
    """Missing scoreboard data returns sensible default (0.0)."""
    with _db(outcomes=[]):
        assert score_job_kpi("deploy_worker") == 0.0


def test_kpi_all_merges_positive():
    """Job with all merges scores positively.

    Pinned to the exact arithmetic the docstring describes (+1.0 per merge, +0.25 per
    pass-not-merged, -0.5 per fail, minus spend capped at n*0.5): 2 merges, no fails,
    $0.08 spent -> 2.0 - 0.08.
    """
    with _db(outcomes=[
        {"tests_passed": True, "integrated": True, "usd": 0.05, "slug": "build-alpha"},
        {"tests_passed": True, "integrated": True, "usd": 0.03, "slug": "build-alpha"},
    ]):
        result = score_job_kpi("build-alpha")
    assert result > 0, f"All-merge job should be positive, got {result}"
    assert result == 1.92, result


def test_kpi_all_failures_negative():
    """Job with all failures scores negatively: 3 * -0.5, minus $0.30 of spend."""
    with _db(outcomes=[
        {"tests_passed": False, "integrated": False, "usd": 0.10, "slug": "bad-job"},
        {"tests_passed": False, "integrated": False, "usd": 0.10, "slug": "bad-job"},
        {"tests_passed": False, "integrated": False, "usd": 0.10, "slug": "bad-job"},
    ]):
        result = score_job_kpi("bad-job")
    assert result < 0, f"All-fail job should be negative, got {result}"
    assert result == -1.8, result


def test_kpi_spend_penalty_is_capped_at_half_a_dollar_per_row():
    """A single ruinous row cannot drag the whole job's KPI down without bound.

    New: the `min(spend, n * 0.5)` cap was the one clause in the formula no test
    covered, and it is the clause that stops one expensive outcome dominating.
    """
    with _db(outcomes=[{"tests_passed": True, "integrated": True, "usd": 500.0,
                        "slug": "pricey"}]):
        result = score_job_kpi("pricey")
    assert result == 0.5, result  # +1.0 merge, spend penalty clamped to 1 * 0.5


def test_kpi_query_is_scoped_to_the_job():
    """The slug filter is what ties outcomes rows to a job; nothing else does."""
    seen = {}

    def _capture(table, params=None):
        seen["table"] = table
        seen["params"] = dict(params or {})
        return []

    with _db(outcomes=_capture):
        score_job_kpi("build-alpha")
    assert seen["table"] == "outcomes"
    assert "build-alpha" in seen["params"]["slug"]


def test_kpi_zero_incident_zero_kpi_vs_negative():
    """Zero-incident jobs with zero KPI scored differently than negative-KPI jobs."""
    with _db(outcomes=[]):
        zero_kpi = score_job_kpi("clean-job")
    with _db(outcomes=[
        {"tests_passed": False, "integrated": False, "usd": 1.0, "slug": "bad-job"},
        {"tests_passed": False, "integrated": False, "usd": 1.0, "slug": "bad-job"},
    ]):
        neg_kpi = score_job_kpi("bad-job")
    assert zero_kpi == 0.0
    assert neg_kpi < 0.0
    assert zero_kpi > neg_kpi


def test_kpi_db_error_returns_zero():
    """Database error returns sensible default, not an exception."""
    def _raise(*a, **kw):
        raise RuntimeError("db down")

    with _db(outcomes=_raise):
        assert score_job_kpi("any-job") == 0.0


def test_kpi_consistent_across_runs():
    """Scoring is deterministic: same input produces same output."""
    rows = [
        {"tests_passed": True, "integrated": True, "usd": 0.05, "slug": "job-x"},
        {"tests_passed": True, "integrated": False, "usd": 0.02, "slug": "job-x"},
        {"tests_passed": False, "integrated": False, "usd": 0.10, "slug": "job-x"},
    ]
    with _db(outcomes=rows):
        r1 = score_job_kpi("job-x")
        r2 = score_job_kpi("job-x")
        r3 = score_job_kpi("job-x")
    assert r1 == r2 == r3
    assert r1 == 0.58, r1  # 1.0 merge + 0.25 pass-not-merged - 0.5 fail - $0.17


# ── count_job_incidents tests ────────────────────────────────────────────────

def test_incidents_empty_name():
    assert count_job_incidents("") == 0
    assert count_job_incidents(None) == 0


def test_incidents_infra_jobs_exempt():
    """Infrastructure-only jobs (kill_switch, pause_arbiter) don't get penalized."""
    exempt = ("kill_switch", "pause_arbiter", "billing_guard", "sentinel")
    assert set(exempt) <= set(INFRA_JOBS), "these must actually be in the exempt set"
    with _db(
        outcomes=[{"id": 1}, {"id": 2}],
        postmortems=[{"id": 1}],
        controls=[{"key": "pause_arbiter_trip"}],
    ):
        for job in exempt:
            result = count_job_incidents(job)
            assert result == 0, f"Infra job {job} should be exempt, got {result}"


def test_incidents_counts_build_failures():
    """Build failures from outcomes are counted."""
    # Was `>= 3`, which would also have accepted a double-count; the three tables
    # contribute 3 + 0 + 0 here, so the total is exactly 3.
    with _db(outcomes=[{"id": 1}, {"id": 2}, {"id": 3}]):
        assert count_job_incidents("deploy-worker") == 3


def test_incidents_counts_postmortems():
    """Revert postmortems are counted."""
    with _db(outcomes=[], postmortems=[{"id": 10}, {"id": 11}]):
        assert count_job_incidents("merge-train") == 2


def test_incidents_partial_data_ok():
    """Incident queries handle partial data: one table errors, others still count."""
    def _raise_on_postmortems(table, params=None):
        raise RuntimeError("table missing")

    with _db(outcomes=[{"id": 1}, {"id": 2}],
             postmortems=_raise_on_postmortems,
             controls=[]):
        # The postmortems query raises; the outcomes count must still survive it.
        assert count_job_incidents("some-job") == 2


def test_incidents_zero_for_clean_job():
    """A job with no incidents returns 0."""
    with _db(outcomes=[], postmortems=[], controls=[]):
        assert count_job_incidents("perfect-job") == 0


def test_incidents_consistent_across_runs():
    """Incident counting is deterministic."""
    with _db(outcomes=[{"id": 1}], postmortems=[{"id": 2}], controls=[{"key": "x"}]):
        r1 = count_job_incidents("job-y")
        r2 = count_job_incidents("job-y")
        r3 = count_job_incidents("job-y")
    assert r1 == r2 == r3
    assert r1 == 3  # 1 outcome + 1 postmortem + 1 control


def test_db_module_is_not_left_stubbed():
    """The fake must not outlive the block that installs it (this file used to leak one)."""
    with _db(outcomes=[]):
        assert isinstance(self_review.db, types.SimpleNamespace)
    assert self_review.db is _DB_AT_IMPORT
    assert not isinstance(self_review.db, types.SimpleNamespace)
