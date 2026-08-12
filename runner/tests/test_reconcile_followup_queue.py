#!/usr/bin/env python3
"""Coverage for reconcile_followup_queue.

The invariants under test:
  * an item with remaining value ALWAYS gets durable provenance, or the gate fails;
  * re-running a reconciliation converges instead of fanning out duplicate tasks;
  * UNKNOWN is never silently absorbed.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import reconcile_followup_queue as rfq  # noqa: E402

FINGERPRINT = "a92ff481c0bad121e4c407fc10f3d96046c11b28ec1004cd6e328dab4e173a7c"


class FakeDB:
    def __init__(self, slugs=(), explode=False, select_explodes=False):
        self.inserted = []
        self._slugs = list(slugs)
        self.explode = explode
        self.select_explodes = select_explodes

    def select_all(self, table, params=None):
        if self.select_explodes:
            raise RuntimeError("db down")
        return [{"slug": s} for s in self._slugs]

    def insert(self, table, row, upsert=False):
        if self.explode:
            raise RuntimeError("write failed")
        self.inserted.append((table, row))
        self._slugs.append(row.get("slug"))


def _record(cls, source="refs/heads/codex/thing", **kw):
    base = {"source": source, "classification": cls, "unique_commits": 2,
            "paths": ["runner/a.py"], "task": "", "branch": "", "commit": "abc123",
            "detail": ""}
    base.update(kw)
    return base


# ── planning ────────────────────────────────────────────────────────────────

def test_recoverable_value_plans_a_recovery_task():
    plan = rfq.plan_followups([_record("RECOVERABLE_VALUE")], FINGERPRINT)[0]
    assert plan["action"] == "queue"
    assert plan["kind"] == "recovery"
    assert plan["slug"].startswith("reconcile-recover-")
    assert FINGERPRINT in plan["prompt"]


def test_conflicted_plans_a_focused_task():
    plan = rfq.plan_followups(
        [_record("CONFLICTED_NEEDS_FOCUSED_TASK", detail="both modified runner/x.py")],
        FINGERPRINT)[0]
    assert plan["action"] == "queue"
    assert plan["slug"].startswith("reconcile-conflict-")
    assert "both modified runner/x.py" in plan["prompt"]


def test_conflict_prompt_forbids_forcing_and_deleting():
    plan = rfq.plan_followups([_record("CONFLICTED_NEEDS_FOCUSED_TASK")], FINGERPRINT)[0]
    assert "READ-ONLY" in plan["prompt"]
    assert "do not force an overwrite" in plan["prompt"].lower()
    assert "isolated worktree" in plan["prompt"]


@pytest.mark.parametrize("cls", rfq.SETTLED)
def test_settled_classifications_need_no_task(cls):
    plan = rfq.plan_followups([_record(cls)], FINGERPRINT)[0]
    assert plan["action"] == "none"
    assert plan["reason"]


def test_unknown_classification_escalates():
    plan = rfq.plan_followups([_record("UNKNOWN")], FINGERPRINT)[0]
    assert plan["action"] == "escalate"
    assert "zero UNKNOWN" in plan["reason"]


def test_plan_emits_one_entry_per_record():
    records = [_record("RECOVERABLE_VALUE", source="a"),
               _record("ALREADY_PRESENT", source="b"),
               _record("UNKNOWN", source="c")]
    assert len(rfq.plan_followups(records, FINGERPRINT)) == 3


def test_plan_is_deterministic():
    record = _record("RECOVERABLE_VALUE")
    first = rfq.plan_followups([record], FINGERPRINT)[0]["slug"]
    second = rfq.plan_followups([record], FINGERPRINT)[0]["slug"]
    assert first == second, "slugs must collide across runs, not fan out"


def test_slugs_are_queue_safe():
    plan = rfq.plan_followups(
        [_record("RECOVERABLE_VALUE",
                 source="refs/orch-rescue/20260803T000716-Claude_Orchestrator!!")],
        FINGERPRINT)[0]
    assert plan["slug"] == plan["slug"].lower()
    assert " " not in plan["slug"] and "/" not in plan["slug"]
    assert len(plan["slug"]) <= 90


def test_plan_handles_empty_input():
    assert rfq.plan_followups([], FINGERPRINT) == []
    assert rfq.plan_followups(None, FINGERPRINT) == []


# ── queueing ────────────────────────────────────────────────────────────────

def test_queue_inserts_one_task_per_actionable_plan():
    plans = rfq.plan_followups(
        [_record("RECOVERABLE_VALUE", source="a"),
         _record("CONFLICTED_NEEDS_FOCUSED_TASK", source="b"),
         _record("ALREADY_PRESENT", source="c")], FINGERPRINT)
    db = FakeDB()
    out = rfq.queue_followups(plans, db=db)
    assert len(out["queued"]) == 2
    assert len(db.inserted) == 2
    assert all(table == "tasks" for table, _ in db.inserted)


def test_queued_rows_carry_state_kind_and_provenance_note():
    plans = rfq.plan_followups([_record("RECOVERABLE_VALUE")], FINGERPRINT)
    db = FakeDB()
    rfq.queue_followups(plans, db=db, project_id="p1", base_branch="master")
    row = db.inserted[0][1]
    assert row["state"] == "QUEUED"
    assert row["kind"] == "recovery"
    assert row["project_id"] == "p1"
    assert row["base_branch"] == "master"
    assert FINGERPRINT in row["note"]
    assert "refs/heads/codex/thing" in row["note"]


def test_existing_slug_is_adopted_not_duplicated():
    plans = rfq.plan_followups([_record("RECOVERABLE_VALUE")], FINGERPRINT)
    db = FakeDB(slugs=[plans[0]["slug"]])
    out = rfq.queue_followups(plans, db=db)
    assert out["queued"] == []
    assert len(out["adopted"]) == 1
    assert db.inserted == []


def test_rerunning_converges(monkeypatch):
    """Two passes over the same evidence must produce one task, not two."""
    records = [_record("RECOVERABLE_VALUE", source="x"),
               _record("CONFLICTED_NEEDS_FOCUSED_TASK", source="y")]
    db = FakeDB()
    rfq.run(records, FINGERPRINT, db=db)
    first = len(db.inserted)
    rfq.run(records, FINGERPRINT, db=db)
    assert len(db.inserted) == first == 2


def test_per_run_cap_is_respected(monkeypatch):
    monkeypatch.setattr(rfq, "MAX_PER_RUN", 2)
    records = [_record("RECOVERABLE_VALUE", source=f"s{i}") for i in range(5)]
    db = FakeDB()
    out = rfq.queue_followups(rfq.plan_followups(records, FINGERPRINT), db=db)
    assert len(out["queued"]) == 2
    assert len(out["failed"]) == 3
    assert all("cap" in f["error"] for f in out["failed"])


def test_insert_failure_is_recorded_not_raised():
    plans = rfq.plan_followups([_record("RECOVERABLE_VALUE")], FINGERPRINT)
    out = rfq.queue_followups(plans, db=FakeDB(explode=True))
    assert out["queued"] == []
    assert out["failed"] and "write failed" in out["failed"][0]["error"]


def test_unreadable_queue_fails_soft_to_empty_known_set():
    plans = rfq.plan_followups([_record("RECOVERABLE_VALUE")], FINGERPRINT)
    db = FakeDB(select_explodes=True)
    out = rfq.queue_followups(plans, db=db)
    assert len(out["queued"]) == 1  # a possible duplicate beats a dropped recovery


def test_escalated_items_are_surfaced():
    plans = rfq.plan_followups([_record("UNKNOWN", source="mystery")], FINGERPRINT)
    out = rfq.queue_followups(plans, db=FakeDB())
    assert out["escalated"] == ["mystery"]


def test_missing_db_module_is_fail_soft(monkeypatch):
    import builtins
    real_import = builtins.__import__

    def no_db(name, *a, **k):
        if name == "db":
            raise ImportError("simulated")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", no_db)
    out = rfq.queue_followups(rfq.plan_followups([_record("RECOVERABLE_VALUE")],
                                                 FINGERPRINT))
    assert out["error"] and "db unavailable" in out["error"]


def test_kill_switch(monkeypatch):
    monkeypatch.setenv("ORCH_FOLLOWUP_QUEUE_ENABLED", "false")
    out = rfq.queue_followups([], db=FakeDB())
    assert "disabled" in out["error"]


# ── provenance gate ─────────────────────────────────────────────────────────

def test_gate_passes_when_everything_is_covered():
    records = [_record("RECOVERABLE_VALUE", source="a"),
               _record("ALREADY_PRESENT", source="b")]
    db = FakeDB()
    report = rfq.run(records, FINGERPRINT, db=db)
    assert report["gate"]["ok"] is True
    assert report["complete"] is True
    assert report["gate"]["covered"] == 1
    assert report["gate"]["settled"] == 1


def test_gate_fails_on_any_unknown_item():
    records = [_record("RECOVERABLE_VALUE", source="a"),
               _record("UNKNOWN", source="mystery")]
    report = rfq.run(records, FINGERPRINT, db=FakeDB())
    assert report["gate"]["ok"] is False
    assert report["gate"]["unknown"] == ["mystery"]
    assert report["complete"] is False


def test_gate_fails_when_a_valuable_item_has_no_provenance():
    records = [_record("RECOVERABLE_VALUE", source="a", commit="")]
    plans = rfq.plan_followups(records, FINGERPRINT)  # planned but never queued
    gate = rfq.provenance_gate(records, plans)
    assert gate["ok"] is False
    assert gate["unprovenanced"] == ["a"]


def test_existing_task_provenance_satisfies_the_gate():
    records = [_record("ACTIVE_IN_ANOTHER_TASK", source="a", task="some-live-slug")]
    report = rfq.run(records, FINGERPRINT, db=FakeDB())
    assert report["gate"]["ok"] is True


def test_gate_fails_when_a_queue_write_failed():
    records = [_record("RECOVERABLE_VALUE", source="a", commit="")]
    report = rfq.run(records, FINGERPRINT, db=FakeDB(explode=True))
    assert report["complete"] is False
    assert report["queue"]["failed"]


def test_gate_on_empty_input_is_vacuously_ok():
    gate = rfq.provenance_gate([], [])
    assert gate["ok"] is True
    assert gate["total"] == 0


def test_run_reports_a_stamp_and_the_fingerprint():
    report = rfq.run([_record("ALREADY_PRESENT")], FINGERPRINT, db=FakeDB())
    assert report["fingerprint"] == FINGERPRINT
    assert report["stamp"]
