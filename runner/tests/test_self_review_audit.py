#!/usr/bin/env python3
"""Tests for self_review.audit_subsystem_jobs and run_monthly_audit."""
import os, sys, types, collections
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest


# Build a synthetic _SCHEDULE for controlled tests (20 jobs so bottom decile = 2)
_FAKE_SCHEDULE = [
    ("alpha-60",   "alpha.py",            "interval", 60),
    ("bravo-300",  "bravo.py",            "interval", 300),
    ("charlie-60", "charlie.py",          "interval", 60),
    ("delta-900",  "delta.py",            "interval", 900),
    ("echo-120",   "echo.py",             "interval", 120),
    ("foxtrot-60", "foxtrot.py",          "interval", 60),
    ("golf-300",   "golf.py",             "interval", 300),
    ("hotel-600",  "hotel.py",            "interval", 600),
    ("india-120",  "india.py",            "interval", 120),
    ("juliet-60",  "juliet.py",           "interval", 60),
    ("kilo-120",   "kilo.py",             "interval", 120),
    ("lima-300",   "lima.py",             "interval", 300),
    ("mike-60",    "mike.py",             "interval", 60),
    ("november-900","november.py",        "interval", 900),
    ("oscar-120",  "oscar.py",            "interval", 120),
    ("papa-60",    "papa.py",             "interval", 60),
    ("quebec-300", "quebec.py",           "interval", 300),
    ("romeo-600",  "romeo.py",            "interval", 600),
    ("sierra-120", "sierra.py",           "interval", 120),
    # infrastructure job -- must be exempt from disable
    ("sentinel-300","sentinel.py",        "interval", 300),
]

_FAKE_KPI = {
    "alpha.py": 50.0,   "bravo.py": 45.0,    "charlie.py": 40.0,
    "delta.py": 35.0,   "echo.py": 30.0,     "foxtrot.py": 25.0,
    "golf.py": 20.0,    "hotel.py": 15.0,    "india.py": 12.0,
    "juliet.py": 0.0,   "kilo.py": 10.0,     "lima.py": 9.0,
    "mike.py": 8.0,     "november.py": 7.0,  "oscar.py": 6.0,
    "papa.py": 5.0,     "quebec.py": 4.0,    "romeo.py": 3.0,
    "sierra.py": 1.0,   "sentinel.py": 0.0,
}

_FAKE_INCIDENTS = {
    "juliet.py": 3,     # value = 0 - 6 = -6  (worst non-infra)
    "sierra.py": 2,     # value = 1 - 4 = -3  (second worst non-infra)
    "sentinel.py": 5,   # value = 0 - 10 = -10 (worst overall, but infra)
}


_fake_db_inserts = []


@pytest.fixture(autouse=True)
def _patch_self_review(monkeypatch):
    """Patch internals so tests don't touch real infra."""
    import self_review

    # Stub out db.insert on the module reference self_review uses
    fake_db = types.ModuleType("db")
    fake_db.select = lambda *a, **kw: []
    fake_db.insert = lambda table, row: _fake_db_inserts.append((table, row))
    monkeypatch.setattr(self_review, "db", fake_db)

    monkeypatch.setattr(self_review, "_load_schedule", lambda: list(_FAKE_SCHEDULE))
    monkeypatch.setattr(self_review, "_fetch_kpi_contributions", lambda: dict(_FAKE_KPI))
    monkeypatch.setattr(self_review, "_fetch_incident_counts", lambda: dict(_FAKE_INCIDENTS))
    monkeypatch.setattr(self_review, "INCIDENT_PENALTY_WEIGHT", 2.0)
    _fake_db_inserts.clear()
    yield


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_enumerates_all_schedule_jobs():
    """audit_subsystem_jobs returns one record per _SCHEDULE entry."""
    import self_review
    records = self_review.audit_subsystem_jobs()
    job_keys = {r["key"] for r in records}
    expected_keys = {e[0] for e in _FAKE_SCHEDULE}
    assert job_keys == expected_keys


def test_ranks_jobs_high_kpi_first():
    """Jobs with higher KPI contribution (minus incident penalty) rank first."""
    import self_review
    records = self_review.audit_subsystem_jobs()
    alpha = next(r for r in records if r["job"] == "alpha.py")
    bravo = next(r for r in records if r["job"] == "bravo.py")
    assert alpha["rank"] < bravo["rank"]
    # Verify overall ordering: values must be non-increasing
    values = [r["value"] for r in records]
    assert values == sorted(values, reverse=True)


def test_bottom_decile_gets_disable_recommendation():
    """With 20 jobs, bottom decile (2 jobs) includes flagged non-infra jobs."""
    import self_review
    records = self_review.audit_subsystem_jobs()
    disabled = [r for r in records if r["disable_recommendation"]]
    assert len(disabled) >= 1
    # juliet.py: KPI=0, incidents=3 -> value=-6 (worst non-infra)
    juliet = next(r for r in records if r["job"] == "juliet.py")
    assert juliet["disable_recommendation"] is True


def test_infrastructure_jobs_exempt_from_disabling():
    """Infrastructure jobs are never recommended for disable even if bottom-ranked."""
    import self_review
    records = self_review.audit_subsystem_jobs()
    sentinel = next(r for r in records if r["job"] == "sentinel.py")
    assert sentinel["is_infrastructure"] is True
    assert sentinel["disable_recommendation"] is False


def test_empty_schedule_handled_gracefully():
    """Empty schedule returns empty list, no crash."""
    import self_review
    orig = self_review._load_schedule
    self_review._load_schedule = lambda: []
    try:
        records = self_review.audit_subsystem_jobs()
        assert records == []
    finally:
        self_review._load_schedule = orig


def test_run_monthly_audit_writes_to_db():
    """run_monthly_audit persists audit records via db.insert."""
    import self_review
    records = self_review.run_monthly_audit()
    assert len(records) == len(_FAKE_SCHEDULE)
    audit_inserts = [(t, r) for t, r in _fake_db_inserts if t == "subsystem_audits"]
    assert len(audit_inserts) == len(_FAKE_SCHEDULE)


def test_run_monthly_audit_empty_schedule():
    """run_monthly_audit with empty schedule prints message, returns empty."""
    import self_review
    orig = self_review._load_schedule
    self_review._load_schedule = lambda: []
    try:
        records = self_review.run_monthly_audit()
        assert records == []
    finally:
        self_review._load_schedule = orig
