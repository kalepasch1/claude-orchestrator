"""Fast-lane admission: shorter SLA + dedicated capacity.

Section 2 of Economic-Scheduler-Revenue (operator, 2026-08-01). The routing
half (lane="revenue-critical") shipped with a test; the fast-lane half —
lane_sla_minutes / sla_status / sla_breaches / reserved_capacity / admit —
shipped with zero callers and zero assertions, i.e. as dead code, which the
task's own contract forbids ("wire it, test it, no dead code").

These tests cover that API and the lane_scheduler wiring that now consumes it.
"""
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

es = pytest.importorskip("economic_scheduler")


def _iso(dt):
    return dt.replace(tzinfo=timezone.utc).isoformat()


NOW = datetime(2026, 9, 9, 12, 0, 0)
NOW_ISO = _iso(NOW)


def _task(minutes_old, lane=es.REVENUE_CRITICAL_LANE, tid="t"):
    return {"id": tid, "lane": lane,
            "created_at": _iso(NOW - timedelta(minutes=minutes_old))}


# ── SLA budgets ──────────────────────────────────────────────────────────────

def test_revenue_critical_sla_is_shorter_than_default():
    assert es.lane_sla_minutes(es.REVENUE_CRITICAL_LANE) < es.DEFAULT_SLA_MINUTES


def test_unknown_lane_gets_the_default_budget_not_zero():
    assert es.lane_sla_minutes("no-such-lane") == es.DEFAULT_SLA_MINUTES
    assert es.lane_sla_minutes(None) == es.DEFAULT_SLA_MINUTES
    assert es.lane_sla_minutes(object()) == es.DEFAULT_SLA_MINUTES


# ── sla_status ───────────────────────────────────────────────────────────────

def test_fresh_revenue_task_is_not_breached():
    s = es.sla_status(_task(5), NOW_ISO)
    assert s["breached"] is False
    assert s["unknown"] is False
    assert s["minutes_remaining"] > 0


def test_old_revenue_task_is_breached():
    s = es.sla_status(_task(es.lane_sla_minutes(es.REVENUE_CRITICAL_LANE) + 30), NOW_ISO)
    assert s["breached"] is True
    assert s["minutes_remaining"] < 0


def test_same_age_bulk_task_is_not_breached_under_the_longer_budget():
    """The point of the fast lane: identical age, different verdict."""
    age = es.lane_sla_minutes(es.REVENUE_CRITICAL_LANE) + 30
    assert es.sla_status(_task(age), NOW_ISO)["breached"] is True
    assert es.sla_status(_task(age, lane="bulk"), NOW_ISO)["breached"] is False


def test_unreadable_timestamp_reports_unknown_not_healthy():
    s = es.sla_status({"lane": es.REVENUE_CRITICAL_LANE, "created_at": "not-a-date"}, NOW_ISO)
    assert s["unknown"] is True
    assert s["breached"] is False
    assert s["age_minutes"] is None


def test_sla_status_never_raises_on_junk():
    for junk in (None, {}, {"lane": 5}, "string"):
        assert isinstance(es.sla_status(junk, NOW_ISO), dict)


def test_sla_breaches_sorted_worst_overrun_first():
    budget = es.lane_sla_minutes(es.REVENUE_CRITICAL_LANE)
    rows = [_task(budget + 10, tid="mild"),
            _task(budget + 500, tid="worst"),
            _task(1, tid="fine"),
            _task(budget + 100, tid="bad")]
    ids = [b["id"] for b in es.sla_breaches(rows, NOW_ISO)]
    assert ids == ["worst", "bad", "mild"]


# ── reserved capacity ────────────────────────────────────────────────────────

def test_reserved_capacity_scales_with_the_fleet():
    assert es.reserved_capacity(100) == int(100 * es.RESERVED_CAPACITY_FRACTION)


def test_reserved_capacity_never_starves_the_lane_on_a_small_fleet():
    """Any capacity at all reserves at least one slot."""
    for total in (1, 2, 3):
        assert es.reserved_capacity(total) >= 1


def test_reserved_capacity_is_capped_so_bulk_is_never_shut_out():
    for total in (4, 10, 100):
        assert es.reserved_capacity(total) <= int(total * es.RESERVED_CAPACITY_MAX_FRACTION)


def test_reserved_capacity_of_nothing_is_nothing():
    assert es.reserved_capacity(0) == 0
    assert es.reserved_capacity(-5) == 0
    assert es.reserved_capacity("junk") == 0
    assert es.reserved_capacity(None) == 0


# ── admit ────────────────────────────────────────────────────────────────────

def test_revenue_work_fills_the_reserved_slots_first():
    tasks = [_task(1, lane="bulk", tid=f"b{i}") for i in range(20)]
    tasks += [_task(1, tid=f"r{i}") for i in range(5)]
    out = es.admit(tasks, total_lanes=8)
    admitted = [t["id"] for t in out["admitted"]]
    assert any(a.startswith("r") for a in admitted)
    assert out["reserved_used"] >= 1


def test_bulk_is_never_completely_starved_by_revenue_overflow():
    """Regression: 20 revenue tasks against 8 lanes once admitted zero bulk."""
    tasks = [_task(1, tid=f"r{i}") for i in range(20)]
    tasks += [_task(1, lane="bulk", tid=f"b{i}") for i in range(20)]
    out = es.admit(tasks, total_lanes=8)
    admitted = [t["id"] for t in out["admitted"]]
    assert any(a.startswith("b") for a in admitted), "bulk starved"
    assert any(a.startswith("r") for a in admitted)


def test_admit_never_exceeds_the_lane_count():
    tasks = [_task(1, tid=f"r{i}") for i in range(50)]
    tasks += [_task(1, lane="bulk", tid=f"b{i}") for i in range(50)]
    for total in (1, 4, 8, 16):
        assert len(es.admit(tasks, total_lanes=total)["admitted"]) <= total


def test_breached_revenue_work_is_admitted_before_fresh_revenue_work():
    budget = es.lane_sla_minutes(es.REVENUE_CRITICAL_LANE)
    tasks = [_task(1, tid="fresh"), _task(budget + 200, tid="late")]
    out = es.admit(tasks, total_lanes=4, now_iso=NOW_ISO)
    assert out["admitted"][0]["id"] == "late"


def test_admit_reports_starved_bulk_as_a_number():
    tasks = [_task(1, lane="bulk", tid=f"b{i}") for i in range(30)]
    out = es.admit(tasks, total_lanes=4)
    assert out["starved_bulk"] > 0


def test_admit_on_an_empty_fleet_admits_nothing():
    out = es.admit([_task(1)], total_lanes=0)
    assert out["admitted"] == []


def test_admit_tolerates_junk_rows():
    out = es.admit([None, "x", 5, _task(1)], total_lanes=4)
    assert all(isinstance(t, dict) for t in out["admitted"])


# ── lane_scheduler wiring ────────────────────────────────────────────────────

ls = pytest.importorskip("lane_scheduler")


def test_lane_scheduler_orders_breached_tasks_first():
    """The wiring under test: previously this was raw Postgres order."""
    budget = es.lane_sla_minutes(es.REVENUE_CRITICAL_LANE)
    rows = [_task(1, tid="fresh"),
            _task(budget + 10, tid="late"),
            _task(budget + 900, tid="latest")]
    ordered, breached = ls._revenue_critical_ordering(rows, NOW_ISO)
    assert [t["id"] for t in ordered][:2] == ["latest", "late"]
    assert breached == 2


def test_lane_scheduler_ordering_puts_unknown_timestamps_last():
    rows = [{"id": "junk", "lane": es.REVENUE_CRITICAL_LANE, "created_at": "nope"},
            _task(1, tid="fresh")]
    ordered, _ = ls._revenue_critical_ordering(rows, NOW_ISO)
    assert ordered[-1]["id"] == "junk"


def test_lane_scheduler_ordering_is_stable_for_equal_ages():
    rows = [_task(5, tid="a"), _task(5, tid="b"), _task(5, tid="c")]
    ordered, breached = ls._revenue_critical_ordering(rows, NOW_ISO)
    assert [t["id"] for t in ordered] == ["a", "b", "c"]
    assert breached == 0


def test_lane_scheduler_ordering_tolerates_empty_and_junk():
    assert ls._revenue_critical_ordering([], NOW_ISO) == ([], 0)
    ordered, breached = ls._revenue_critical_ordering([None, "x"], NOW_ISO)
    assert ordered == []
    assert breached == 0
