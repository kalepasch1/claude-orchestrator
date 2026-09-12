"""pressure() must see the whole backlog, not the first page of it.

db's own truncated-scan detector had been reporting this call for
integration_sweeper.py:551 -- "tasks returned exactly its limit (200) ordered by
updated_at.asc. Anything past the cap is invisible to this caller." Ascending
order made it worse than an undercount: the cap always fell on the OLDEST rows,
so once the backlog exceeded it, newly-waiting work could never appear in the
pressure figure at all. Pressure is the signal for how starved a project is, so
a number that saturates and stops responding is the one thing it must not be.

Pure: db is stubbed, no network, no git.
"""
import os
import sys

import pytest

_RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _RUNNER not in sys.path:
    sys.path.insert(0, _RUNNER)

import integration_sweeper as isw  # noqa: E402


PROJECTS = [{"id": "p1", "name": "alpha", "repo_path": "/tmp/alpha"}]


def _passed_task(n):
    """A task pressure() should count: passed, waiting to integrate."""
    return {"id": f"t{n}", "slug": f"feat-{n}", "project_id": "p1",
            "state": "DONE", "note": "tests passed; awaiting integration",
            "updated_at": f"2026-08-{(n % 28) + 1:02d}T00:00:00"}


@pytest.fixture()
def stub_db(monkeypatch):
    """Record how the tasks table is read, and serve a large backlog."""
    calls = {"select_all": [], "select": []}

    def fake_select(table, params=None):
        calls["select"].append((table, dict(params or {})))
        return list(PROJECTS) if table == "projects" else []

    def fake_select_all(table, params=None, **kwargs):
        calls["select_all"].append((table, dict(params or {}), dict(kwargs)))
        return [_passed_task(i) for i in range(500)]

    monkeypatch.setattr(isw.db, "select", fake_select)
    monkeypatch.setattr(isw.db, "select_all", fake_select_all)
    monkeypatch.setattr(isw, "_agent_branch_exists", lambda repo, slug: True)
    return calls


def test_backlog_beyond_the_old_cap_is_counted(stub_db):
    """500 waiting tasks with the old limit of 200 reported 200."""
    out = isw.pressure(limit=200)
    assert out["projects"]["alpha"]["passed_waiting"] == 500


def test_tasks_are_read_through_the_paging_helper(stub_db):
    isw.pressure(limit=200)
    tables = [t for t, _p, _k in stub_db["select_all"]]
    assert "tasks" in tables, "tasks must be paged to exhaustion, not single-shot"


def test_no_silent_limit_is_sent_for_tasks(stub_db):
    """A `limit` in the params is the silent horizon this fixes."""
    isw.pressure(limit=200)
    _table, params, _kwargs = stub_db["select_all"][0]
    assert "limit" not in params


def test_order_is_deterministic(stub_db):
    """Offset paging over an unordered relation may repeat or skip rows."""
    isw.pressure(limit=200)
    _table, _params, kwargs = stub_db["select_all"][0]
    assert kwargs.get("order") == "updated_at.asc"


def test_paging_budget_never_drops_below_a_floor(stub_db):
    """A small caller limit must not reintroduce a tiny horizon."""
    isw.pressure(limit=5)
    _table, _params, kwargs = stub_db["select_all"][0]
    assert kwargs.get("max_rows") >= 1000


def test_a_larger_caller_limit_is_honoured(stub_db):
    isw.pressure(limit=5000)
    _table, _params, kwargs = stub_db["select_all"][0]
    assert kwargs.get("max_rows") == 5000


def test_state_filter_is_still_applied_server_side(stub_db):
    isw.pressure(limit=200)
    _table, params, _kwargs = stub_db["select_all"][0]
    assert params.get("state") == "in.(DONE,BLOCKED,RUNNING)"


def test_empty_backlog_is_fail_soft(monkeypatch):
    monkeypatch.setattr(isw.db, "select", lambda table, params=None: list(PROJECTS)
                        if table == "projects" else [])
    monkeypatch.setattr(isw.db, "select_all", lambda *a, **k: [])
    assert isw.pressure(limit=200)["projects"] == {}
