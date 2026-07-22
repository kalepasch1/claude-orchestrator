"""Tests for score_job_kpi() and count_job_incidents() in self_review.py."""
import os, sys, types
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Stub db module before importing self_review so it never hits the network.
_db_responses = {}

def _fake_select(table, params=None):
    key = table
    if key in _db_responses:
        val = _db_responses[key]
        if callable(val):
            return val(table, params)
        return val
    return []

_fake_db = types.ModuleType("db")
_fake_db.select = _fake_select
_fake_db.insert = lambda *a, **kw: None
_fake_db.update = lambda *a, **kw: None
_fake_db.count = lambda *a, **kw: 0
sys.modules["db"] = _fake_db

from self_review import score_job_kpi, count_job_incidents, INFRA_JOBS


# ── Helpers ──────────────────────────────────────────────────────────────────

def _setup(outcomes=None, postmortems=None, controls=None):
    """Set up fake db responses for a test."""
    _db_responses.clear()
    if outcomes is not None:
        _db_responses["outcomes"] = outcomes
    if postmortems is not None:
        _db_responses["postmortems"] = postmortems
    if controls is not None:
        _db_responses["controls"] = controls


def _teardown():
    _db_responses.clear()


# ── score_job_kpi tests ─────────────────────────────────────────────────────

def test_kpi_empty_name_returns_zero():
    """Empty/None job name returns 0.0."""
    assert score_job_kpi("") == 0.0
    assert score_job_kpi(None) == 0.0


def test_kpi_no_outcomes_returns_zero():
    """Missing scoreboard data returns sensible default (0.0)."""
    _setup(outcomes=[])
    result = score_job_kpi("deploy_worker")
    _teardown()
    assert result == 0.0


def test_kpi_all_merges_positive():
    """Job with all merges scores positively."""
    _setup(outcomes=[
        {"tests_passed": True, "integrated": True, "usd": 0.05, "slug": "build-alpha"},
        {"tests_passed": True, "integrated": True, "usd": 0.03, "slug": "build-alpha"},
    ])
    result = score_job_kpi("build-alpha")
    _teardown()
    assert result > 0, f"All-merge job should be positive, got {result}"


def test_kpi_all_failures_negative():
    """Job with all failures scores negatively."""
    _setup(outcomes=[
        {"tests_passed": False, "integrated": False, "usd": 0.10, "slug": "bad-job"},
        {"tests_passed": False, "integrated": False, "usd": 0.10, "slug": "bad-job"},
        {"tests_passed": False, "integrated": False, "usd": 0.10, "slug": "bad-job"},
    ])
    result = score_job_kpi("bad-job")
    _teardown()
    assert result < 0, f"All-fail job should be negative, got {result}"


def test_kpi_zero_incident_zero_kpi_vs_negative():
    """Zero-incident jobs with zero KPI scored differently than negative-KPI jobs."""
    _setup(outcomes=[])
    zero_kpi = score_job_kpi("clean-job")

    _setup(outcomes=[
        {"tests_passed": False, "integrated": False, "usd": 1.0, "slug": "bad-job"},
        {"tests_passed": False, "integrated": False, "usd": 1.0, "slug": "bad-job"},
    ])
    neg_kpi = score_job_kpi("bad-job")
    _teardown()
    assert zero_kpi == 0.0
    assert neg_kpi < 0.0
    assert zero_kpi > neg_kpi


def test_kpi_db_error_returns_zero():
    """Database error returns sensible default, not an exception."""
    def _raise(*a, **kw):
        raise RuntimeError("db down")
    _db_responses.clear()
    _db_responses["outcomes"] = _raise
    result = score_job_kpi("any-job")
    _teardown()
    assert result == 0.0


def test_kpi_consistent_across_runs():
    """Scoring is deterministic: same input produces same output."""
    rows = [
        {"tests_passed": True, "integrated": True, "usd": 0.05, "slug": "job-x"},
        {"tests_passed": True, "integrated": False, "usd": 0.02, "slug": "job-x"},
        {"tests_passed": False, "integrated": False, "usd": 0.10, "slug": "job-x"},
    ]
    _setup(outcomes=rows)
    r1 = score_job_kpi("job-x")
    r2 = score_job_kpi("job-x")
    r3 = score_job_kpi("job-x")
    _teardown()
    assert r1 == r2 == r3


# ── count_job_incidents tests ────────────────────────────────────────────────

def test_incidents_empty_name():
    assert count_job_incidents("") == 0
    assert count_job_incidents(None) == 0


def test_incidents_infra_jobs_exempt():
    """Infrastructure-only jobs (kill_switch, pause_arbiter) don't get penalized."""
    _setup(
        outcomes=[{"id": 1}, {"id": 2}],
        postmortems=[{"id": 1}],
        controls=[{"key": "pause_arbiter_trip"}],
    )
    for job in ("kill_switch", "pause_arbiter", "billing_guard", "sentinel"):
        result = count_job_incidents(job)
        assert result == 0, f"Infra job {job} should be exempt, got {result}"
    _teardown()


def test_incidents_counts_build_failures():
    """Build failures from outcomes are counted."""
    _setup(outcomes=[{"id": 1}, {"id": 2}, {"id": 3}])
    result = count_job_incidents("deploy-worker")
    _teardown()
    assert result >= 3


def test_incidents_counts_postmortems():
    """Revert postmortems are counted."""
    _setup(outcomes=[], postmortems=[{"id": 10}, {"id": 11}])
    result = count_job_incidents("merge-train")
    _teardown()
    assert result >= 2


def test_incidents_partial_data_ok():
    """Incident queries handle partial data: one table errors, others still count."""
    def _raise_on_postmortems(table, params=None):
        if table == "postmortems":
            raise RuntimeError("table missing")
        return [{"id": 1}]
    _db_responses.clear()
    _db_responses["outcomes"] = [{"id": 1}, {"id": 2}]
    _db_responses["postmortems"] = _raise_on_postmortems
    _db_responses["controls"] = []
    # Even though postmortems errors, we still get outcomes count
    result = count_job_incidents("some-job")
    _teardown()
    assert result >= 2


def test_incidents_zero_for_clean_job():
    """A job with no incidents returns 0."""
    _setup(outcomes=[], postmortems=[], controls=[])
    result = count_job_incidents("perfect-job")
    _teardown()
    assert result == 0


def test_incidents_consistent_across_runs():
    """Incident counting is deterministic."""
    _setup(
        outcomes=[{"id": 1}],
        postmortems=[{"id": 2}],
        controls=[{"key": "x"}],
    )
    r1 = count_job_incidents("job-y")
    r2 = count_job_incidents("job-y")
    r3 = count_job_incidents("job-y")
    _teardown()
    assert r1 == r2 == r3
    assert r1 == 3  # 1 outcome + 1 postmortem + 1 control
