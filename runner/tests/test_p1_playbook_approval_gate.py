"""Tests for runner/p1_playbook_approval_gate.py.

The fixtures below mirror the fleet state recorded in the 2026-08-10..13
P1-queue-clearance logs: Guardrail 8 escalation still QUEUED and unapproved,
five blocking human-decision items all pending.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from p1_playbook_approval_gate import (  # noqa: E402
    BLOCKING_HUMAN_DECISIONS,
    HELD_PLAYBOOK_STEPS,
    evaluate_gate,
    format_report,
    is_unapproved,
    main,
    report_blocking_decisions,
)

ESCALATION_ID = "b78b7bdb-2f07-45e3-8ce6-66e23d0b923f"


def standing_escalation(**overrides):
    escalation = {
        "id": ESCALATION_ID,
        "slug": "escalate-p1-queue-clearance-no-improvement-20260810-nk73",
        "state": "QUEUED",
        "priority": 5,
        "operator_approved_at": None,
    }
    escalation.update(overrides)
    return escalation


def all_pending_decisions():
    return [
        {"slug": slug, "operator_approved_at": None} for slug in BLOCKING_HUMAN_DECISIONS
    ]


def all_approved_decisions():
    return [
        {"slug": slug, "operator_approved_at": "2026-08-14T10:00:00Z"}
        for slug in BLOCKING_HUMAN_DECISIONS
    ]


def test_standing_halt_refuses_to_proceed():
    gate = evaluate_gate(standing_escalation(), all_pending_decisions())
    assert gate["may_proceed"] is False
    assert gate["halt_standing"] is True
    assert gate["pending_count"] == 5


def test_halt_reason_is_explicit_and_names_the_escalation():
    gate = evaluate_gate(standing_escalation(), all_pending_decisions())
    assert gate["reason"].startswith("HALT GUARDRAIL 8")
    assert ESCALATION_ID in gate["reason"]


def test_no_held_step_is_ever_executed():
    for decisions in (all_pending_decisions(), all_approved_decisions()):
        gate = evaluate_gate(standing_escalation(state="DONE"), decisions)
        assert gate["executed_steps"] == []


def test_all_five_decisions_are_reported_even_when_absent():
    rows = report_blocking_decisions([])
    assert len(rows) == 5
    assert {row["slug"] for row in rows} == set(BLOCKING_HUMAN_DECISIONS)
    assert all(row["status"] == "MISSING" for row in rows)


def test_a_missing_decision_is_treated_as_unapproved():
    partial = all_approved_decisions()[:-1]
    gate = evaluate_gate(standing_escalation(state="DONE"), partial)
    assert gate["may_proceed"] is False
    assert gate["missing_count"] == 1
    assert BLOCKING_HUMAN_DECISIONS[-1] in gate["reason"]


def test_report_shows_approval_state_per_decision():
    decisions = all_pending_decisions()
    decisions[0]["operator_approved_at"] = "2026-08-14T10:00:00Z"
    rows = {row["slug"]: row for row in report_blocking_decisions(decisions)}
    assert rows[BLOCKING_HUMAN_DECISIONS[0]]["status"] == "APPROVED"
    assert rows[BLOCKING_HUMAN_DECISIONS[1]]["status"] == "PENDING"


def test_gate_opens_only_when_halt_cleared_and_all_five_approved():
    gate = evaluate_gate(standing_escalation(state="DONE"), all_approved_decisions())
    assert gate["may_proceed"] is True
    assert gate["pending_count"] == 0
    assert gate["missing_count"] == 0


def test_approved_escalation_still_blocked_by_one_pending_decision():
    decisions = all_approved_decisions()
    decisions[2]["operator_approved_at"] = None
    gate = evaluate_gate(standing_escalation(state="DONE"), decisions)
    assert gate["may_proceed"] is False
    assert gate["pending_count"] == 1


def test_null_spellings_all_read_as_unapproved():
    for spelling in (None, "NULL", "null", "None", "", "   "):
        assert is_unapproved(spelling) is True
    assert is_unapproved("2026-08-14T10:00:00Z") is False


def test_junk_records_do_not_open_the_gate():
    gate = evaluate_gate(standing_escalation(state="DONE"), ["not-a-dict", None, 7])
    assert gate["may_proceed"] is False
    assert gate["missing_count"] == 5


def test_missing_escalation_is_fail_soft_and_closed():
    gate = evaluate_gate(None, all_pending_decisions())
    assert gate["may_proceed"] is False
    assert gate["pending_count"] == 5


def test_formatted_report_lists_every_held_step():
    text = format_report(evaluate_gate(standing_escalation(), all_pending_decisions()))
    assert "HALT" in text
    for step in HELD_PLAYBOOK_STEPS:
        assert step in text
    for slug in BLOCKING_HUMAN_DECISIONS:
        assert slug in text


def test_cli_exits_non_zero_while_approvals_are_pending(tmp_path, capsys):
    payload = {"escalation": standing_escalation(), "decisions": all_pending_decisions()}
    path = tmp_path / "state.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert main([str(path)]) == 1
    assert "HALT GUARDRAIL 8" in capsys.readouterr().out


def test_cli_exits_zero_once_everything_is_approved(tmp_path, capsys):
    payload = {
        "escalation": standing_escalation(state="DONE"),
        "decisions": all_approved_decisions(),
    }
    path = tmp_path / "state.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert main([str(path), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["may_proceed"] is True


def test_cli_treats_unreadable_input_as_not_approved(tmp_path, capsys):
    path = tmp_path / "broken.json"
    path.write_text("{not json at all", encoding="utf-8")
    assert main([str(path)]) == 1
    capsys.readouterr()
