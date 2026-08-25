#!/usr/bin/env python3
"""
stale_backlog_guardrail_report.py — read consolidated P1 queue-clearance logs.

The stale-backlog compactor collapses many P1-queue-clearance log entries into
one free-text blob. Everything a recovery pass needs to decide whether it may
act is in that blob as prose: whether the Guardrail 8 halt is still standing,
which human bypass reports are still unreviewed, and which runs the
queue-velocity PID shelved.

Reading it by eye is how the same halt got re-litigated four times. This module
turns the prose into structured facts so the decision is mechanical.

Parsing is deliberately fail-soft: a missing or malformed field yields None or
an empty list rather than raising, so a recovery pass can never wedge on a
log entry whose shape drifted.

This module only *reports*. It never raises throughput, re-prioritizes, or
triages dead weight — those are exactly the steps Guardrail 8 exists to hold.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

# Guardrail 8 facts. The escalation id appears as either "id=<uuid>" or
# "id <uuid>"; both spellings are in the wild in the same batch.
_UUID = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
_RE_ESCALATION_ID = re.compile(r"\bid[= ]\(?(" + _UUID + r")\)?")
_RE_STATE = re.compile(r"\bstate\s*=\s*([A-Za-z_]+)")
_RE_PRIORITY = re.compile(r"\bpriority\s*=\s*(\d+)")
_RE_APPROVED_AT = re.compile(r"\boperator_approved_at\s*=\s*(NULL|[0-9T:\-\.\+Z ]+?)(?=[,\s]|$)")

# "since tripped (2026-08-10 22:01:16 UTC)" and the older "filed 2026-08-10
# 22:01:16 UTC" both name the moment the halt went up.
_RE_TRIPPED = re.compile(r"tripped\s*\((\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2}:\d{2})\s*UTC\)")
_RE_FILED = re.compile(r"filed\s+(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2}:\d{2})\s*UTC")

# Pending human bypass reports, with the optional "(~26.0h old)" age suffix.
_RE_BYPASS = re.compile(r"(human-decision-p1-halt-bypassed[a-z0-9\-]*)")
_RE_BYPASS_AGE = re.compile(r"^\s*\(~\s*([0-9]+(?:\.[0-9]+)?)\s*h")

# P1 queue-clearance run ids and the run timestamp inside each entry.
_RE_RUN_ID = re.compile(r"(log-p1-queue-clearance-\d{8}-[a-z0-9]+)")
_RE_RUN_TS = re.compile(r"(\d{4}-\d{2}-\d{2})\s*~?\s*(\d{2}:\d{2})\s*UTC")

# The queue-velocity PID records its shelve once per batch, in the footer.
_RE_SHELVED = re.compile(r"shelved by queue-velocity PID\s*(?:\(([^)]*)\))?", re.IGNORECASE)

_OUTCOME_NO_STEPS = (
    "did NOT execute steps (a) dead-weight triage, "
    "(b) throughput/concurrency, (c) prioritize-by-value"
)
_OUTCOME_SHELVED = "shelved by queue-velocity PID"


def _iso(date_part: str, time_part: str) -> str:
    """Render a "2026-08-10" + "22:01:16" pair as ISO8601 UTC."""
    if len(time_part) == 5:  # HH:MM — the run entries omit seconds
        time_part = time_part + ":00"
    return "{0}T{1}Z".format(date_part, time_part)


def _parse_guardrail8(text: str) -> Dict:
    """Pull the Guardrail 8 halt status out of the consolidated log text."""
    escalation = _RE_ESCALATION_ID.search(text)
    state = _RE_STATE.search(text)
    priority = _RE_PRIORITY.search(text)
    approved = _RE_APPROVED_AT.search(text)

    tripped = _RE_TRIPPED.search(text) or _RE_FILED.search(text)

    priority_value = 0
    if priority:
        try:
            priority_value = int(priority.group(1))
        except (TypeError, ValueError):
            priority_value = 0

    return {
        "escalation_id": escalation.group(1) if escalation else None,
        "state": state.group(1) if state else None,
        "priority": priority_value,
        # "NULL" is carried through as the literal string the log uses, so the
        # gating rule can tell "recorded as unapproved" from "never mentioned".
        "operator_approved_at": approved.group(1).strip() if approved else None,
        "tripped_at": _iso(tripped.group(1), tripped.group(2)) if tripped else None,
    }


def _parse_pending_bypass(text: str) -> List[Dict]:
    """Collect unreviewed human bypass reports, first occurrence wins."""
    found: List[Dict] = []
    seen = set()
    for match in _RE_BYPASS.finditer(text):
        bypass_id = match.group(1).rstrip("-")
        if bypass_id in seen:
            continue
        seen.add(bypass_id)
        age_match = _RE_BYPASS_AGE.match(text[match.end():])
        age = None
        if age_match:
            try:
                age = float(age_match.group(1))
            except (TypeError, ValueError):
                age = None
        found.append({"id": bypass_id, "age_hours": age})
    return found


def _run_blocks(text: str) -> List[Dict]:
    """Split the log into one text block per distinct P1 run id."""
    starts: List[Dict] = []
    seen = set()
    for match in _RE_RUN_ID.finditer(text):
        run_id = match.group(1)
        if run_id in seen:
            continue
        seen.add(run_id)
        starts.append({"run_id": run_id, "start": match.start()})

    blocks = []
    for index, entry in enumerate(starts):
        end = starts[index + 1]["start"] if index + 1 < len(starts) else len(text)
        blocks.append({"run_id": entry["run_id"], "text": text[entry["start"]:end]})
    return blocks


def _parse_p1_runs(text: str) -> List[Dict]:
    """Extract each P1 queue-clearance run with its timestamp and outcome.

    The queue-velocity shelve is attributed to the single most recent run
    rather than to whichever block happens to contain the footer text. The PID
    shelves the run that was in flight, and the batch footer records that
    shelve once — attributing per-block would double-count it whenever the
    compactor repeats an entry, which it does.
    """
    runs: List[Dict] = []
    for block in _run_blocks(text):
        ts_match = _RE_RUN_TS.search(block["text"])
        outcome = _OUTCOME_NO_STEPS if "did NOT execute steps" in block["text"] else None
        runs.append({
            "run_id": block["run_id"],
            "timestamp_utc": _iso(ts_match.group(1), ts_match.group(2)) if ts_match else None,
            "outcome": outcome,
            "shelved_reason": None,
        })

    shelved = _RE_SHELVED.search(text)
    if shelved and runs:
        dated = [r for r in runs if r["timestamp_utc"]]
        target = max(dated, key=lambda r: r["timestamp_utc"]) if dated else runs[-1]
        reason = (shelved.group(1) or "").strip() or "queue-velocity PID"
        target["shelved_reason"] = reason
        target["outcome"] = _OUTCOME_SHELVED
    return runs


def parse_backlog_log(text: Optional[str]) -> Dict:
    """Parse a consolidated stale-backlog recovery log into structured facts.

    Returns a dict with three keys: ``guardrail8`` (halt status),
    ``pending_human_bypass`` (unreviewed bypass reports) and ``p1_runs``
    (queue-clearance runs). Empty input yields empty structures, never an
    exception.
    """
    if not text:
        return {
            "guardrail8": {
                "escalation_id": None,
                "state": None,
                "priority": 0,
                "operator_approved_at": None,
                "tripped_at": None,
            },
            "pending_human_bypass": [],
            "p1_runs": [],
        }

    return {
        "guardrail8": _parse_guardrail8(text),
        "pending_human_bypass": _parse_pending_bypass(text),
        "p1_runs": _parse_p1_runs(text),
    }


# The three steps Guardrail 8 exists to hold. A blocked decision may not plan
# any of them, so they are named here rather than left to prose.
HELD_STEPS = (
    "dead-weight triage",
    "throughput/concurrency raise",
    "re-prioritization by value",
)


def _is_unapproved(value: Optional[str]) -> bool:
    """True when operator_approved_at records no real approval timestamp."""
    if value is None:
        return True
    return str(value).strip().upper() in {"", "NULL", "NONE"}


def evaluate_guardrail8(parsed: Optional[Dict]) -> Dict:
    """Decide whether Guardrail 8 blocks a queue-clearance pass.

    The halt stands while the escalation is still QUEUED and no operator has
    approved it. While it stands, ``planned_subtasks`` is empty by
    construction: the only steps this pass could plan are the ones the
    guardrail holds, so planning anything at all would route around it.
    """
    parsed = parsed or {}
    guardrail = parsed.get("guardrail8") or {}
    state = (guardrail.get("state") or "").strip().upper()
    unapproved = _is_unapproved(guardrail.get("operator_approved_at"))

    if state == "QUEUED" and unapproved:
        escalation = guardrail.get("escalation_id") or "unknown escalation"
        return {
            "guardrail8": {
                "should_block": True,
                "reason": "escalation {0} is state=QUEUED with operator_approved_at unset".format(
                    escalation
                ),
                "required_next_action": "await_operator_approval",
            },
            "planned_subtasks": [],
        }

    return {
        "guardrail8": {
            "should_block": False,
            "reason": "no standing Guardrail 8 halt: state={0}, approved={1}".format(
                state or "unknown", not unapproved
            ),
            "required_next_action": "proceed",
        },
        "planned_subtasks": [],
    }


# A bypass report older than this has sat long enough that the reviewer should
# be asked for context rather than nodded through.
BYPASS_STALE_HOURS = 24.0


def _bypass_action(age_hours: Optional[float]) -> str:
    """Choose a review action for one pending bypass report.

    Unknown age is treated the same as stale, not the same as fresh. The
    compactor truncates the age suffix often enough that defaulting an
    unmeasurable report to "confirm" would auto-approve bypasses of a standing
    halt purely because the log got cut off mid-line.
    """
    if age_hours is None:
        return "request_more_info"
    return "request_more_info" if age_hours > BYPASS_STALE_HOURS else "confirm"


def build_bypass_reviews(parsed: Optional[Dict], decision: Optional[Dict]) -> Dict:
    """Turn pending human bypass reports into actionable review instructions.

    Only produces instructions while the guardrail decision is blocking — if
    nothing is being held, there is no bypass left to review.
    """
    parsed = parsed or {}
    decision = decision or {}
    blocking = bool((decision.get("guardrail8") or {}).get("should_block"))
    if not blocking:
        return {"bypass_reviews": [], "instructions_complete": True}

    escalation = (
        (decision.get("guardrail8") or {}).get("escalation_id")
        or (parsed.get("guardrail8") or {}).get("escalation_id")
        or "unknown escalation"
    )

    reviews = []
    for report in parsed.get("pending_human_bypass") or []:
        age = report.get("age_hours")
        action = _bypass_action(age)
        age_text = "age unknown" if age is None else "{0:.1f}h old".format(age)
        reviews.append({
            "id": report.get("id"),
            "age_hours": age,
            "action": action,
            "suggested_message": (
                "Bypass report {0} ({1}) is still unreviewed while Guardrail 8 "
                "escalation {2} remains QUEUED and unapproved. {3}".format(
                    report.get("id"),
                    age_text,
                    escalation,
                    "Please confirm the bypass or withdraw it."
                    if action == "confirm"
                    else "Please supply the justification and current status before it is actioned.",
                )
            ),
        })

    return {"bypass_reviews": reviews, "instructions_complete": True}


_QUEUE_VELOCITY_RECOMMENDATION = (
    "Revisit the queue-velocity PID tuning: review the low-EV threshold and "
    "consider resetting the accumulated integral term, under operator approval. "
    "Recommendation only — no throughput, concurrency or prioritization change "
    "is applied here."
)


def _is_shelved_by_pid(run: Dict) -> bool:
    """True when this run was shelved by the queue-velocity PID."""
    reason = (run.get("shelved_reason") or "").lower()
    outcome = (run.get("outcome") or "").lower()
    if "shelved by queue-velocity pid" in outcome:
        return True
    return "low ev" in reason and "integral" in reason


def assess_queue_velocity(parsed: Optional[Dict]) -> Dict:
    """Report P1 runs the queue-velocity PID shelved, without acting on them.

    A shelved run looks like a stalled queue, and the reflex is to raise
    throughput or re-prioritize. Both are steps Guardrail 8 holds, so this
    function deliberately stops at a recommendation and asserts that it made
    no such change.
    """
    parsed = parsed or {}
    runs = parsed.get("p1_runs") or []
    shelved = [run.get("run_id") for run in runs if _is_shelved_by_pid(run)]

    return {
        "queue_velocity": {
            "observed": bool(shelved),
            "shelved_runs": shelved,
            "recommended_adjustment": (
                _QUEUE_VELOCITY_RECOMMENDATION
                if shelved
                else "No queue-velocity shelving observed; no adjustment recommended."
            ),
        },
        # Asserted, not merely intended: this module has no code path that
        # changes throughput, concurrency or priority.
        "safety": {"does_not_change_throughput_or_priority": True},
    }
