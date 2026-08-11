"""Regression coverage for the operator/self-improvement delivery conversion path."""
from __future__ import annotations

import os
import sys
import types

RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RUNNER not in sys.path:
    sys.path.insert(0, RUNNER)

import feedback
import feedback_review
import improvement_scrutiny
import loops
import merge_train
import meta_loop


def test_feedback_rejects_schema_echo_and_dedupes_valid_report(monkeypatch):
    inserts = []
    monkeypatch.setattr(feedback.db, "select", lambda *_a, **_k: [])
    monkeypatch.setattr(feedback.db, "insert", lambda table, row: inserts.append((table, row)))
    feedback._RECENT_FINGERPRINTS.clear()

    assert feedback.submit("strategy", "...", "...", "low|med|high") is False
    assert feedback.submit(
        "strategy", "Merge train waits behind duplicate fleet work.",
        "Prioritize authenticated tasks and retain regression gates.", "high",
        project="beethoven", slug="operator-one",
    ) is True
    assert feedback.submit(
        "strategy", "Merge train waits behind duplicate fleet work.",
        "Prioritize authenticated tasks and retain regression gates.", "high",
        project="beethoven", slug="operator-one",
    ) is False
    assert len(inserts) == 1


def test_feedback_review_advances_rows_and_files_executable_proposal(monkeypatch):
    valid = {
        "id": "valid-1", "source": "agent", "category": "strategy", "severity": "high",
        "observation": "Operator work is starved by speculative self-improvement tasks.",
        "suggestion": "Pause speculative generation while operator work is pending.",
    }
    invalid = {
        "id": "invalid-1", "source": "agent", "category": "strategy",
        "severity": "low|med|high", "observation": "...", "suggestion": "...",
    }
    inserts, updates = [], []

    def select(table, query=None):
        if table == "orchestrator_feedback":
            return [] if (query or {}).get("source") == "eq.human" else [valid, invalid]
        if table == "improvement_proposals":
            return []
        return []

    monkeypatch.setattr(feedback_review.db, "select", select)
    monkeypatch.setattr(feedback_review.db, "insert", lambda table, row: inserts.append((table, row)))
    monkeypatch.setattr(feedback_review.db, "update", lambda table, match, patch: updates.append((table, match, patch)))
    monkeypatch.setattr(feedback_review.claude_cli, "run", lambda *_a, **_k: {"text": "Bound speculative generation behind operator backlog."})
    monkeypatch.setattr(feedback_review, "_ab_test", lambda *_a, **_k: "skip")

    assert feedback_review.run() == 1
    proposal = next(row for table, row in inserts if table == "improvement_proposals")
    assert proposal["status"] == "for_review"
    assert improvement_scrutiny.implementation_spec_ready(proposal["proposal"])["pass"]
    assert not any(table == "approvals" for table, _row in inserts)
    statuses = {match["id"]: patch["status"] for table, match, patch in updates
                if table == "orchestrator_feedback"}
    assert statuses == {"invalid-1": "dismissed", "valid-1": "triaged"}


def test_loop_scheduler_runs_fleet_handler_once_for_many_app_rows(monkeypatch):
    due = [
        {"id": "l1", "project": "one", "type": "remediate", "enabled": True, "last_run": None},
        {"id": "l2", "project": "two", "type": "remediate", "enabled": True, "last_run": None},
    ]
    calls, updates = [], []
    monkeypatch.setattr(loops, "ensure_all", lambda: 0)
    monkeypatch.setattr(loops.db, "select", lambda table, *_a, **_k: due if table == "loops" else [])
    monkeypatch.setattr(loops.db, "update", lambda table, match, patch: updates.append((table, match, patch)))
    monkeypatch.setitem(sys.modules, "watchdog", types.SimpleNamespace(check=lambda: calls.append("check")))

    assert loops.run_due() == 1
    assert calls == ["check"]
    assert {match["id"] for table, match, _patch in updates if table == "loops"} == {"l1", "l2"}


def test_merge_batch_prioritizes_authenticated_work_without_bypassing_risk(monkeypatch):
    monkeypatch.setitem(sys.modules, "value_router", types.SimpleNamespace(estimate_value=lambda _task: 0))
    monkeypatch.setattr(merge_train, "_risk_level", lambda _card, _task: "low")
    old_machine = ({"id": "c1", "created_at": "2026-01-01"}, "machine-task",
                   {"id": "t1", "slug": "machine-task"})
    new_operator = ({"id": "c2", "created_at": "2026-02-01"}, "operator-task",
                    {"id": "t2", "slug": "operator-task", "submitted_by": "user-1"})

    ordered = merge_train._select_batch([old_machine, new_operator])
    assert [entry[1] for entry in ordered] == ["operator-task", "machine-task"]
    assert all(entry[3] == "low" for entry in ordered)


def test_meta_loop_excludes_synthetic_smoke_project(monkeypatch):
    monkeypatch.setattr(meta_loop.db, "select", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("no query expected")))
    assert meta_loop._project_score("smoke-test") is None
