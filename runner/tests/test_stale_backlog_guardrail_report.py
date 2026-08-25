"""Tests for runner/stale_backlog_guardrail_report.py.

SAMPLE_LOG is the verbatim consolidated log text from the stale-backlog batch
7cc8037, kept unedited so the assertions below are the batch's own acceptance
criteria rather than a paraphrase of them.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stale_backlog_guardrail_report import (  # noqa: E402
    HELD_STEPS,
    evaluate_guardrail8,
    parse_backlog_log,
)

ESCALATION_ID = "b78b7bdb-2f07-45e3-8ce6-66e23d0b923f"

SAMPLE_LOG = """
Consolidated stale backlog recovery.

Project: unknown
Collapsed queued tasks: 4

Original intents:
1. log-p1-queue-clearance-20260812-w83k: LOG (no action taken): P1-queue-clearance
playbook run at 2026-08-12 ~20:59 UTC did NOT execute steps (a) dead-weight-triage,
(b) throughput/concurrency, or (c) prioritize-by-value. Guardrail 8 halt remains
standing: escalate-p1-queue-clearance-no-improvement-20260810-nk73
(id=b78b7bdb-2f07-45e3-8ce6-66e23d0b923f) filed 2026-08-10 22:01:16 UTC, still
state=QUEUED, operator_approved_at=NULL (~47.0h unapproved). Two unresolved bypass
reports also pending human review, unapproved:
human-decision-p1-halt-bypassed-20260811-hb41 (~26.0h old) and
human-decision-p1-halt-bypassed-again-20260812-b155 (~
2. log-p1-queue-clearance-20260812-n2c9: WHAT: Log entry -- orch-operator P1 queue
clearance run 2026-08-12 ~23:00 UTC, fresh scheduled session, independently
re-derived via direct SQL. GUARDRAIL 8 STATUS: still in effect --
escalate-p1-queue-clearance-no-improvement-20260810-nk73
(id b78b7bdb-2f07-45e3-8ce6-66e23d0b923f) remains state=QUEUED, priority=5,
operator_approved_at=NULL, now 49.0h since tripped (2026-08-10 22:01:16 UTC). Per
Guardrail 8, did NOT execute steps (a) dead-weight triage, (b) throughput/concurrency
raise, or (c) priori
3. log-p1-queue-clearance-20260813-q0n5: WHAT: Log entry -- orch-operator P1 queue
clearance run 2026-08-13 ~00:00 UTC, fresh scheduled session. GUARDRAIL 8 STATUS:
still in effect -- escalate-p1-queue-clearance-no-improvement-20260810-nk73
(id b78b7bdb-2f07-45e3-8ce6-66e23d0b923f) remains state=QUEUED, priority=5,
operator_approved_at=NULL, now 50.0h since tripped (2026-08-10 22:01:16 UTC). Per
Guardrail 8, did NOT execute steps (a) dead-weight triage, (b) throughput/concurrency
raise, or (c) priori
4. log-p1-queue-clearance-20260813-m2xq: WHAT: Log entry -- orch-operator P1 queue
clearance run 2026-08-13 ~01:00 UTC, fresh scheduled session. GUARDRAIL 8 STATUS:
still in effect -- escalate-p1-queue-clearance-no-improvement-20260810-nk73
(id b78b7bdb-2f07-45e3-8ce6-66e23d0b923f) remains state=QUEUED, priority=5,
operator_approved_at=NULL, now ~51h since tripped (2026-08-10 22:01:16 UTC). Per
Guardrail 8, did NOT execute steps (a) dead-weight triage, (b) throughput/concurrency
raise, or (c) priorit

shelved by queue-velocity PID (low EV, integral too high)
"""


def test_guardrail8_facts_match_the_log():
    parsed = parse_backlog_log(SAMPLE_LOG)
    guardrail = parsed["guardrail8"]
    assert guardrail["escalation_id"] == ESCALATION_ID
    assert guardrail["state"] == "QUEUED"
    assert guardrail["priority"] == 5
    assert guardrail["operator_approved_at"] == "NULL"
    assert guardrail["tripped_at"] == "2026-08-10T22:01:16Z"


def test_both_pending_bypass_reports_are_found():
    parsed = parse_backlog_log(SAMPLE_LOG)
    pending = parsed["pending_human_bypass"]
    assert len(pending) == 2
    assert pending[0]["id"].startswith("human-decision-p1-halt-bypassed-20260811-hb41")
    assert pending[1]["id"].startswith("human-decision-p1-halt-bypassed-again-20260812-b155")


def test_bypass_age_is_read_when_present_and_none_when_truncated():
    parsed = parse_backlog_log(SAMPLE_LOG)
    pending = parsed["pending_human_bypass"]
    assert pending[0]["age_hours"] == 26.0
    # The compactor truncated the second entry mid-suffix; age is unknown, not zero.
    assert pending[1]["age_hours"] is None


def test_p1_runs_include_both_20260812_entries():
    parsed = parse_backlog_log(SAMPLE_LOG)
    run_ids = [run["run_id"] for run in parsed["p1_runs"]]
    assert "log-p1-queue-clearance-20260812-w83k" in run_ids
    assert "log-p1-queue-clearance-20260812-n2c9" in run_ids
    assert len(run_ids) == len(set(run_ids)), "run ids must be de-duplicated"


def test_run_timestamps_come_from_the_run_line_not_the_halt_line():
    parsed = parse_backlog_log(SAMPLE_LOG)
    by_id = {run["run_id"]: run for run in parsed["p1_runs"]}
    # The first entry also mentions the 2026-08-10 halt; the run time must win.
    assert by_id["log-p1-queue-clearance-20260812-w83k"]["timestamp_utc"] == "2026-08-12T20:59:00Z"
    assert by_id["log-p1-queue-clearance-20260813-m2xq"]["timestamp_utc"] == "2026-08-13T01:00:00Z"


def test_queue_velocity_shelve_lands_on_exactly_one_most_recent_run():
    parsed = parse_backlog_log(SAMPLE_LOG)
    shelved = [run for run in parsed["p1_runs"] if run["shelved_reason"]]
    assert len(shelved) == 1
    assert shelved[0]["run_id"].startswith("log-p1-queue-clearance-20260813")
    assert "low EV" in shelved[0]["shelved_reason"]


def test_unshelved_runs_report_the_skipped_steps_as_outcome():
    parsed = parse_backlog_log(SAMPLE_LOG)
    by_id = {run["run_id"]: run for run in parsed["p1_runs"]}
    outcome = by_id["log-p1-queue-clearance-20260812-n2c9"]["outcome"]
    assert "did NOT execute steps" in outcome
    assert by_id["log-p1-queue-clearance-20260812-n2c9"]["shelved_reason"] is None


def test_empty_and_junk_input_are_fail_soft():
    for junk in (None, "", "nothing structured here"):
        parsed = parse_backlog_log(junk)
        assert parsed["pending_human_bypass"] == []
        assert parsed["p1_runs"] == []
        assert parsed["guardrail8"]["escalation_id"] is None
        assert parsed["guardrail8"]["priority"] == 0


def test_standing_halt_blocks_and_plans_nothing():
    decision = evaluate_guardrail8(parse_backlog_log(SAMPLE_LOG))
    assert decision["guardrail8"]["should_block"] is True
    assert decision["guardrail8"]["required_next_action"] != "proceed"
    assert decision["planned_subtasks"] == []


def test_blocked_decision_names_the_escalation():
    decision = evaluate_guardrail8(parse_backlog_log(SAMPLE_LOG))
    assert ESCALATION_ID in decision["guardrail8"]["reason"]


def test_approved_escalation_lets_the_pass_proceed():
    parsed = parse_backlog_log(SAMPLE_LOG)
    parsed["guardrail8"]["operator_approved_at"] = "2026-08-13T09:00:00Z"
    decision = evaluate_guardrail8(parsed)
    assert decision["guardrail8"]["should_block"] is False
    assert decision["guardrail8"]["required_next_action"] == "proceed"


def test_resolved_escalation_lets_the_pass_proceed():
    parsed = parse_backlog_log(SAMPLE_LOG)
    parsed["guardrail8"]["state"] = "DONE"
    decision = evaluate_guardrail8(parsed)
    assert decision["guardrail8"]["should_block"] is False


def test_null_spellings_all_count_as_unapproved():
    for spelling in ("NULL", "null", "", "  ", None, "None"):
        parsed = parse_backlog_log(SAMPLE_LOG)
        parsed["guardrail8"]["operator_approved_at"] = spelling
        decision = evaluate_guardrail8(parsed)
        assert decision["guardrail8"]["should_block"] is True, spelling


def test_blocked_decision_never_plans_a_held_step():
    decision = evaluate_guardrail8(parse_backlog_log(SAMPLE_LOG))
    planned = " ".join(decision["planned_subtasks"]).lower()
    for step in HELD_STEPS:
        assert step.lower() not in planned


def test_gating_is_fail_soft_on_empty_input():
    for junk in (None, {}, {"guardrail8": {}}):
        decision = evaluate_guardrail8(junk)
        assert decision["guardrail8"]["should_block"] is False
        assert decision["planned_subtasks"] == []
