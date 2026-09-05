"""Tests for runner/fast_auto_merge.py — the event-driven auto-approve gate.

The module switched from an hourly batch sweep to a test-completion event
(`on_test_completion` / `dispatch_test_completion`) but shipped without tests, so
the one behaviour that matters — a PASSING event approves a low-risk merge and a
non-passing event does NOT — was unasserted. This file covers that gate.

`db` is stubbed on the module object rather than mocked at import time: the
module does `import db` after a sys.path insert, so the attribute is the seam.
No test here touches the network or a real database.
"""
import os
import sys

import pytest

RUNNER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "runner")
sys.path.insert(0, os.path.abspath(RUNNER))

import fast_auto_merge  # noqa: E402


class FakeDB:
    """Minimal db stand-in: records inserts, serves canned approval cards."""

    def __init__(self, cards=None, raise_on_select=False):
        self.cards = cards or []
        self.raise_on_select = raise_on_select
        self.inserts = []
        self.selects = []

    def select(self, table, params=None):
        self.selects.append((table, params))
        if self.raise_on_select:
            raise RuntimeError("db unreachable")
        if table == "approvals":
            return list(self.cards)
        return []

    def insert(self, table, row):
        self.inserts.append((table, row))
        return {"id": len(self.inserts)}


LOW_RISK_TASK = {
    "id": "t-1",
    "slug": "backlog-batch-tidy-imports",
    "kind": "build",
    "project_id": "p-1",
    "state": "DONE",
}


@pytest.fixture
def fake_db(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr(fast_auto_merge, "db", db)
    # Default ON, but pin it so a stray env var cannot flip the suite.
    monkeypatch.setenv("ORCH_FAST_MERGE_EVENT_DISPATCH", "1")
    return db


# --- event_is_passing: ambiguity must never mean "yes" -------------------------

@pytest.mark.parametrize("event", [
    {"status": "passed"},
    {"status": "PASSED"},
    {"conclusion": "success"},
    {"result": "green"},
    {"state": "ok", "failed": 0},
    {"passed": True},
    {"status": "passed", "failed": [], "errors": 0},
    {"status": "passed", "completed": True},
])
def test_event_is_passing_accepts_green_runs(event):
    assert fast_auto_merge.event_is_passing(event) is True


@pytest.mark.parametrize("event", [
    None,
    {},
    "passed",
    {"status": "failed"},
    {"status": "running"},
    {"status": "in_progress"},
    {"conclusion": "cancelled"},
    {"status": "passed", "completed": False},
    {"status": "passed", "failed": 2},
    {"status": "passed", "failures": ["test_a"]},
    {"status": "passed", "errors": 1},
    {"status": "passed", "passed": False},
    {"passed": True, "failed": 3},
    {"status": "banana"},
])
def test_event_is_passing_rejects_everything_else(event):
    assert fast_auto_merge.event_is_passing(event) is False


# --- on_test_completion: the gate ---------------------------------------------

def test_passing_event_auto_approves_a_low_risk_merge(fake_db):
    verdict = fast_auto_merge.on_test_completion(
        {"kind": "test:completed", "status": "passed", "task": LOW_RISK_TASK}
    )
    assert verdict["approved"] is True
    assert verdict["slug"] == LOW_RISK_TASK["slug"]
    assert len(fake_db.inserts) == 1
    table, row = fake_db.inserts[0]
    assert table == "approvals"
    assert row["status"] == "approved"
    assert row["slug"] == LOW_RISK_TASK["slug"]
    assert "fast-auto-merge" in row["decided_by"]


@pytest.mark.parametrize("event", [
    {"status": "failed", "task": LOW_RISK_TASK},
    {"status": "running", "task": LOW_RISK_TASK},
    {"status": "passed", "completed": False, "task": LOW_RISK_TASK},
    {"status": "passed", "failed": 1, "task": LOW_RISK_TASK},
])
def test_non_passing_event_never_approves(fake_db, event):
    verdict = fast_auto_merge.on_test_completion(event)
    assert verdict["approved"] is False
    assert fake_db.inserts == [], "a non-green run must not create an approval"


def test_high_risk_task_is_not_fast_merged_even_on_pass(fake_db):
    """The slug keyword guard: a green run does not fast-merge an auth change."""
    task = dict(LOW_RISK_TASK, slug="rotate-auth-token-secret")
    verdict = fast_auto_merge.on_test_completion({"status": "passed", "task": task})
    assert verdict["approved"] is False
    assert "low-risk" in verdict["reason"]
    assert fake_db.inserts == []


def test_out_of_class_kind_is_not_fast_merged(fake_db):
    task = dict(LOW_RISK_TASK, kind="recovery")
    verdict = fast_auto_merge.on_test_completion({"status": "passed", "task": task})
    assert verdict["approved"] is False
    assert fake_db.inserts == []


def test_existing_approval_card_blocks_a_second_one(monkeypatch):
    db = FakeDB(cards=[{"id": 1, "status": "approved", "decided_by": "human"}])
    monkeypatch.setattr(fast_auto_merge, "db", db)
    verdict = fast_auto_merge.on_test_completion({"status": "passed", "task": LOW_RISK_TASK})
    assert verdict["approved"] is False
    assert "already exists" in verdict["reason"]
    assert db.inserts == []


def test_unreadable_approvals_table_fails_closed(monkeypatch):
    """If we cannot tell whether an approval exists, do not create one."""
    db = FakeDB(raise_on_select=True)
    monkeypatch.setattr(fast_auto_merge, "db", db)
    verdict = fast_auto_merge.on_test_completion({"status": "passed", "task": LOW_RISK_TASK})
    assert verdict["approved"] is False
    assert "approval lookup failed" in verdict["reason"]
    assert db.inserts == []


def test_event_without_a_resolvable_task_is_declined(fake_db):
    verdict = fast_auto_merge.on_test_completion({"status": "passed"})
    assert verdict["approved"] is False
    assert fake_db.inserts == []


def test_event_resolves_task_by_slug_lookup(monkeypatch):
    """No inline task dict: the handler must look the row up, not give up."""
    db = FakeDB()
    looked_up = dict(LOW_RISK_TASK)

    def select(table, params=None):
        db.selects.append((table, params))
        if table == "tasks":
            return [looked_up]
        return []

    db.select = select
    monkeypatch.setattr(fast_auto_merge, "db", db)
    verdict = fast_auto_merge.on_test_completion(
        {"status": "passed", "slug": LOW_RISK_TASK["slug"]}
    )
    assert verdict["approved"] is True
    assert any(t == "tasks" for t, _ in db.selects)


# --- dispatch_test_completion: the production trigger --------------------------

def test_dispatch_approves_when_tests_passed(fake_db):
    verdict = fast_auto_merge.dispatch_test_completion(LOW_RISK_TASK, True)
    assert verdict is not None and verdict["approved"] is True
    assert len(fake_db.inserts) == 1


def test_dispatch_declines_when_tests_failed(fake_db):
    verdict = fast_auto_merge.dispatch_test_completion(LOW_RISK_TASK, False)
    assert verdict is not None and verdict["approved"] is False
    assert fake_db.inserts == []


def test_dispatch_is_a_no_op_when_disabled(fake_db, monkeypatch):
    monkeypatch.setenv("ORCH_FAST_MERGE_EVENT_DISPATCH", "0")
    assert fast_auto_merge.dispatch_test_completion(LOW_RISK_TASK, True) is None
    assert fake_db.inserts == []


def test_dispatch_never_raises_on_the_hot_path(monkeypatch):
    """dispatch runs inside runner.record(); it must not lose an outcome row."""
    class Exploding:
        def select(self, *a, **k):
            raise RuntimeError("boom")

        def insert(self, *a, **k):
            raise RuntimeError("boom")

    monkeypatch.setattr(fast_auto_merge, "db", Exploding())
    monkeypatch.setenv("ORCH_FAST_MERGE_EVENT_DISPATCH", "1")
    # Fails closed, and returns rather than propagating.
    result = fast_auto_merge.dispatch_test_completion(LOW_RISK_TASK, True)
    assert result is None or result["approved"] is False


# --- the batch sweep stays retired --------------------------------------------

def test_batch_sweep_is_off_by_default(monkeypatch):
    monkeypatch.delenv("ORCH_FAST_MERGE_BATCH_SWEEP", raising=False)
    assert fast_auto_merge.batch_sweep_enabled() is False


def test_batch_sweep_is_opt_in_only(monkeypatch):
    monkeypatch.setenv("ORCH_FAST_MERGE_BATCH_SWEEP", "1")
    assert fast_auto_merge.batch_sweep_enabled() is True


def test_subscribe_registers_the_handler_on_a_bus():
    class Bus:
        def __init__(self):
            self.handlers = []

        def subscribe(self, kind, handler):
            self.handlers.append((kind, handler))

    bus = Bus()
    assert fast_auto_merge.subscribe(bus) is True
    assert bus.handlers == [(fast_auto_merge.EVENT_KIND, fast_auto_merge.on_test_completion)]


def test_subscribe_without_a_dispatcher_is_a_no_op():
    assert fast_auto_merge.subscribe(None) is False
