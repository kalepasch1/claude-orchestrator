"""Tests for runner/guardrail_hold_streak.py.

SAMPLE_LOG is the consolidated text of stale-backlog batch 380b833: five
hourly P1-queue-clearance runs, every one of them holding on the same
Guardrail 8 stop, over roughly 59 hours with no operator response.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from guardrail_hold_streak import (  # noqa: E402
    HOLD_HOURS_ESCALATION_THRESHOLD,
    HOLD_STREAK_ESCALATION_THRESHOLD,
    analyze,
    main,
    parse_hold_logs,
    summarize_hold_streaks,
)

ESCALATION_SLUG = "escalate-p1-queue-clearance-stalled-20260808-e9k2"
ESCALATION_ID = "250cc82c-c27e-4cdc-a77c-9ee503db8e76"

SAMPLE_LOG = """
Consolidated stale backlog recovery.

Original intents:
1. log-p1-queue-clearance-20260808-4zlg: WHAT: Log entry -- orch-operator P1 queue
clearance run 2026-08-08 ~14:59 UTC. HOLDING again -- did NOT execute (a) dead-weight
triage, (b) throughput raise, or (c) prioritize-by-value, since standing stop condition
(Guardrail 8, tripped 2026-08-08 00:01 UTC by
escalate-p1-queue-clearance-stalled-20260808-e9k2) remains unaddressed ~15h later, now
the 16th consecutive hourly log on this stall. MEASURED: QUEUED = 911.
2. log-p1-queue-clearance-20260808-w9tz: WHAT: Log entry -- orch-operator P1 queue
clearance run 2026-08-08 ~16:00-16:01 UTC. Mid-run I discovered the standing Guardrail-8
stop condition tripped 2026-08-08 00:01 UTC by
escalate-p1-queue-clearance-stalled-20260808-e9k2, still open/unaddressed ~16h later.
MEASURED (this run): QUEUED=1147.
3. log-p1-queue-clearance-20260809-rbql: WHAT: Log entry -- orch-operator P1 queue
clearance run 2026-08-09 ~16:59 UTC. HOLDING again this run -- did NOT execute (a)
dead-weight triage, (b) throughput/concurrency raise, or (c) prioritize-by-value, because
the standing Guardrail-8 stop (escalate-p1-queue-clearance-stalled-20260808-e9k2, id
250cc82c-c27e-4cdc-a77c-9ee503db8e76, filed 2026-08-08 00:01:24 UTC) remains open:
state=QUEUED, priority=5, operator_approved_at=NULL, now ~40h58m unaddressed by a hum
4. log-p1-queue-clearance-20260810-31fc: WHAT: Log entry -- orch-operator P1 queue
clearance run 2026-08-10 ~09:52 UTC. HOLDING again this run -- did NOT execute (a)
dead-weight triage, (b) throughput/concurrency raise, or (c) prioritize-by-value, because
the standing Guardrail-8 stop (escalate-p1-queue-clearance-stalled-20260808-e9k2, id
250cc82c-c27e-4cdc-a77c-9ee503db8e76, filed 2026-08-08 00:01:24 UTC) remains open:
verified via direct id lookup state=QUEUED, priority=5, operator_approved_at=NULL,
5. log-p1-queue-clearance-20260810-h2ux: WHAT: Log entry -- orch-operator P1 queue
clearance run 2026-08-10 ~10:59 UTC. HOLDING again this run -- did NOT execute (a)
dead-weight triage, (b) throughput/concurrency raise, or (c) prioritize-by-value, because
the standing Guardrail-8 stop (escalate-p1-queue-clearance-stalled-20260808-e9k2, id
250cc82c-c27e-4cdc-a77c-9ee503db8e76, filed 2026-08-08 00:01:24 UTC) remains open:
verified via direct id lookup state=QUEUED, priority=5, operator_approved_at=NULL, now
~59h unaddressed by a hum
"""


def test_every_holding_run_is_captured():
    entries = parse_hold_logs(SAMPLE_LOG)
    assert len(entries) == 5
    assert entries[0]["run_id"] == "log-p1-queue-clearance-20260808-4zlg"


def test_runs_are_attributed_to_the_same_escalation():
    entries = parse_hold_logs(SAMPLE_LOG)
    assert {e["escalation_slug"] for e in entries} == {ESCALATION_SLUG}


def test_escalation_uuid_is_read_where_the_log_records_it():
    entries = parse_hold_logs(SAMPLE_LOG)
    with_uuid = [e for e in entries if e["escalation_id"]]
    assert len(with_uuid) == 3
    assert with_uuid[0]["escalation_id"] == ESCALATION_ID


def test_run_timestamps_prefer_the_run_line_over_the_tripped_line():
    entries = parse_hold_logs(SAMPLE_LOG)
    assert entries[0]["ran_at"] == "2026-08-08T14:59:00Z"
    assert entries[-1]["ran_at"] == "2026-08-10T10:59:00Z"


def test_unaddressed_hours_parse_including_the_minutes_form():
    entries = parse_hold_logs(SAMPLE_LOG)
    hours = [e["hours_unaddressed"] for e in entries]
    assert hours[0] == 15.0
    assert hours[1] == 16.0
    assert hours[2] == round(40 + 58 / 60.0, 2)
    assert hours[3] is None  # entry 4 was truncated before the age
    assert hours[4] == 59.0


def test_the_streak_is_reported_as_one_escalation():
    report = analyze(SAMPLE_LOG)
    assert len(report["escalations"]) == 1
    streak = report["escalations"][0]
    assert streak["consecutive_holds"] == 5
    assert streak["escalation_slug"] == ESCALATION_SLUG


def test_streak_spans_first_to_last_run():
    streak = analyze(SAMPLE_LOG)["escalations"][0]
    assert streak["first_hold_at"] == "2026-08-08T14:59:00Z"
    assert streak["last_hold_at"] == "2026-08-10T10:59:00Z"
    assert streak["max_hours_unaddressed"] == 59.0


def test_a_long_stall_asks_for_a_human():
    report = analyze(SAMPLE_LOG)
    assert report["needs_human_escalation"] is True
    assert "Page a human" in report["escalations"][0]["recommendation"]


def test_recommendation_never_orders_a_held_step():
    text = analyze(SAMPLE_LOG)["escalations"][0]["recommendation"].lower()
    assert "advisory only" in text
    for verb in ("raise throughput", "increase concurrency", "reorder by value"):
        assert verb not in text


def test_safety_flag_is_asserted():
    assert analyze(SAMPLE_LOG)["safety"]["does_not_change_throughput_or_priority"] is True


def test_a_short_fresh_streak_does_not_page_anyone():
    entries = [
        {
            "run_id": "log-p1-queue-clearance-20260808-aaaa",
            "ran_at": "2026-08-08T01:00:00Z",
            "escalation_slug": ESCALATION_SLUG,
            "escalation_id": None,
            "hours_unaddressed": 1.0,
        }
    ]
    report = summarize_hold_streaks(entries)
    assert report["needs_human_escalation"] is False
    assert "within normal range" in report["escalations"][0]["recommendation"]


def test_streak_threshold_alone_is_enough_to_page():
    entries = [
        {
            "run_id": "log-p1-queue-clearance-20260808-{0}".format(index),
            "ran_at": "2026-08-08T0{0}:00:00Z".format(index),
            "escalation_slug": ESCALATION_SLUG,
            "escalation_id": None,
            "hours_unaddressed": 1.0,
        }
        for index in range(HOLD_STREAK_ESCALATION_THRESHOLD)
    ]
    assert summarize_hold_streaks(entries)["needs_human_escalation"] is True


def test_age_threshold_alone_is_enough_to_page():
    entries = [
        {
            "run_id": "log-p1-queue-clearance-20260808-solo",
            "ran_at": "2026-08-08T01:00:00Z",
            "escalation_slug": ESCALATION_SLUG,
            "escalation_id": None,
            "hours_unaddressed": HOLD_HOURS_ESCALATION_THRESHOLD,
        }
    ]
    assert summarize_hold_streaks(entries)["needs_human_escalation"] is True


def test_separate_escalations_are_counted_separately():
    entries = parse_hold_logs(SAMPLE_LOG)
    entries[0]["escalation_slug"] = "escalate-p1-queue-clearance-other-20260901-zzzz"
    report = summarize_hold_streaks(entries)
    assert len(report["escalations"]) == 2
    assert report["escalations"][0]["consecutive_holds"] == 4


def test_runs_that_did_not_hold_are_ignored():
    text = (
        "1. log-p1-queue-clearance-20260808-good: run 2026-08-08 ~14:59 UTC. "
        "Executed normally, queue cleared."
    )
    assert parse_hold_logs(text) == []


def test_analysis_is_fail_soft():
    for junk in (None, "", "no structure here"):
        report = analyze(junk)
        assert report["escalations"] == []
        assert report["total_hold_runs"] == 0
        assert report["needs_human_escalation"] is False
        assert report["safety"]["does_not_change_throughput_or_priority"] is True


def test_cli_emits_json(tmp_path, capsys):
    path = tmp_path / "holds.log"
    path.write_text(SAMPLE_LOG, encoding="utf-8")
    assert main([str(path)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["total_hold_runs"] == 5
    assert payload["needs_human_escalation"] is True


def test_streak_carries_the_uuid_even_when_the_first_run_omitted_it():
    # Entry 1 names only the slug; entries 3-5 also print the uuid.
    streak = analyze(SAMPLE_LOG)["escalations"][0]
    assert streak["escalation_id"] == ESCALATION_ID
