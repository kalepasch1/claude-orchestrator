#!/usr/bin/env python3
"""Coverage for branch_recovery_ledger.

The invariants under test:
  * every safe_delete outcome becomes a durable row, including the refusals;
  * the ledger NEVER raises — a down DB degrades to a no-op, it does not wedge a sweep;
  * task state is never touched; only `note` is stamped.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import branch_recovery_ledger as brl  # noqa: E402


class FakeDB:
    def __init__(self, insert_explodes=False, update_explodes=False, rows=None):
        self.inserted = []
        self.updated = []
        self.insert_explodes = insert_explodes
        self.update_explodes = update_explodes
        self._rows = rows or []

    def insert(self, table, row, upsert=False):
        if self.insert_explodes:
            raise RuntimeError("write failed")
        self.inserted.append((table, row))

    def update(self, table, match, patch):
        if self.update_explodes:
            raise RuntimeError("update failed")
        self.updated.append((table, match, patch))

    def select(self, table, params=None):
        return list(self._rows)


@pytest.fixture()
def fake_db(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr(brl, "_db", lambda: db)
    return db


def _safe_delete_result(**kw):
    base = {"branch": "agent/thing", "archived": "refs/archive/agent/thing",
            "shared": False, "local_deleted": True, "remote_deleted": False,
            "durable": True, "reason": "grace sweep"}
    base.update(kw)
    return base


# ── single actions ──────────────────────────────────────────────────────────

def test_action_writes_one_namespaced_row(fake_db):
    out = brl.log_recovery_action("archived", "agent/thing", repo="/r", slug="thing")
    assert out["logged"] is True
    table, row = fake_db.inserted[0]
    assert table == brl.EVENT_TABLE
    assert row["kind"] == brl.KIND
    assert row["action"] == "archived"
    assert "agent/thing" in row["detail"]


def test_failed_action_records_value_zero(fake_db):
    brl.log_recovery_action("deleted", "agent/thing", ok=False)
    assert fake_db.inserted[0][1]["value"] == 0


def test_unknown_action_is_recorded_not_dropped(fake_db):
    brl.log_recovery_action("teleported", "agent/thing")
    assert fake_db.inserted[0][1]["action"] == "unknown:teleported"


def test_missing_branch_is_refused_without_a_row(fake_db):
    out = brl.log_recovery_action("archived", "")
    assert out["logged"] is False
    assert fake_db.inserted == []


def test_extra_payload_is_serialised_into_detail(fake_db):
    brl.log_recovery_action("rebased", "agent/thing", extra={"behind": 42})
    assert "42" in fake_db.inserted[0][1]["detail"]


def test_detail_is_truncated_not_unbounded(fake_db, monkeypatch):
    monkeypatch.setattr(brl, "DETAIL_LIMIT", 60)
    brl.log_recovery_action("archived", "agent/thing", reason="x" * 500)
    assert len(fake_db.inserted[0][1]["detail"]) <= 60


# ── safe_delete fan-out ─────────────────────────────────────────────────────

def test_archive_and_delete_are_separate_rows(fake_db):
    out = brl.log_safe_delete(_safe_delete_result(), repo="/r", slug="thing")
    assert out["logged"] == ["archived", "deleted"]
    assert [r["action"] for _, r in fake_db.inserted] == ["archived", "deleted"]


def test_a_refused_delete_is_still_logged_as_skipped(fake_db):
    """Archived-but-not-deleted must stay legible; it is the durability guard working."""
    out = brl.log_safe_delete(
        _safe_delete_result(local_deleted=False, error="not durable"))
    assert "skipped" in out["logged"]
    skipped = [r for _, r in fake_db.inserted if r["action"] == "skipped"][0]
    assert skipped["value"] == 0
    assert "not durable" in skipped["detail"]


def test_shared_push_gets_its_own_row(fake_db):
    brl.log_safe_delete(_safe_delete_result(shared=True))
    assert "shared" in [r["action"] for _, r in fake_db.inserted]


def test_result_without_a_branch_is_an_error_not_a_row(fake_db):
    out = brl.log_safe_delete({"local_deleted": True})
    assert out["error"] == "result has no branch"
    assert fake_db.inserted == []


# ── mark recovered ──────────────────────────────────────────────────────────

def test_mark_recovered_stamps_note_and_logs(fake_db):
    out = brl.mark_branch_recovered("thing", detail="restored from refs/archive")
    assert out["marked"] is True and out["logged"] is True
    table, match, patch = fake_db.updated[0]
    assert table == "tasks"
    assert match == {"slug": "eq.thing"}
    assert list(patch) == ["note"]


def test_mark_recovered_never_touches_task_state(fake_db):
    brl.mark_branch_recovered("thing")
    assert "state" not in fake_db.updated[0][2]


def test_mark_recovered_defaults_the_branch_name(fake_db):
    brl.mark_branch_recovered("thing")
    assert "agent/thing" in fake_db.inserted[0][1]["detail"]


def test_mark_recovered_without_a_slug_is_refused(fake_db):
    out = brl.mark_branch_recovered("")
    assert out["marked"] is False
    assert fake_db.updated == []


# ── summary ─────────────────────────────────────────────────────────────────

def test_summary_totals_only_numeric_counts(fake_db):
    brl.log_sweep_summary({"cleaned": 2, "rebased": 3, "project": "beethoven"},
                          repo="/r")
    row = fake_db.inserted[0][1]
    assert row["action"] == "sweep_summary"
    assert row["value"] == 5


def test_empty_sweep_still_writes_a_row(fake_db):
    """An empty sweep and a sweep that never ran must not look identical."""
    assert brl.log_sweep_summary({"cleaned": 0, "rebased": 0})["logged"] is True
    assert fake_db.inserted[0][1]["value"] == 0


# ── fail-soft ───────────────────────────────────────────────────────────────

def test_insert_failure_is_reported_not_raised(monkeypatch):
    monkeypatch.setattr(brl, "_db", lambda: FakeDB(insert_explodes=True))
    out = brl.log_recovery_action("archived", "agent/thing")
    assert out["logged"] is False
    assert "RuntimeError" in out["error"]


def test_update_failure_is_reported_not_raised(monkeypatch):
    monkeypatch.setattr(brl, "_db", lambda: FakeDB(update_explodes=True))
    out = brl.mark_branch_recovered("thing")
    assert out["marked"] is False
    assert "RuntimeError" in out["error"]


def test_no_db_degrades_to_a_no_op(monkeypatch):
    monkeypatch.setattr(brl, "_db", lambda: None)
    assert brl.log_recovery_action("archived", "agent/x")["error"] == "db unavailable"
    assert brl.log_sweep_summary({})["error"] == "db unavailable"
    assert brl.recent_actions() == []


def test_safe_delete_fanout_survives_a_dead_db(monkeypatch):
    monkeypatch.setattr(brl, "_db", lambda: FakeDB(insert_explodes=True))
    assert brl.log_safe_delete(_safe_delete_result())["logged"] == ["archived", "deleted"]


def test_kill_switch_blocks_every_write(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr(brl, "_db", lambda: db)
    monkeypatch.setenv("ORCH_BRANCH_RECOVERY_LEDGER", "false")
    assert brl.log_recovery_action("archived", "agent/x")["logged"] is False
    assert brl.mark_branch_recovered("thing")["marked"] is False
    assert brl.log_sweep_summary({"cleaned": 1})["logged"] is False
    assert db.inserted == [] and db.updated == []


def test_unserialisable_payload_falls_back_instead_of_failing(fake_db):
    brl.log_recovery_action("archived", "agent/x", extra={"obj": object()})
    assert fake_db.inserted[0][1]["detail"]


# ── reads ───────────────────────────────────────────────────────────────────

def test_recent_actions_filters_by_branch(monkeypatch):
    rows = [{"detail": '{"branch": "agent/a"}'}, {"detail": '{"branch": "agent/b"}'}]
    monkeypatch.setattr(brl, "_db", lambda: FakeDB(rows=rows))
    assert len(brl.recent_actions(branch="agent/a")) == 1
    assert len(brl.recent_actions()) == 2
