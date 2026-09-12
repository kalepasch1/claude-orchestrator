#!/usr/bin/env python3
"""
p1_playbook_approval_gate.py — refuse to run the P1 queue-clearance playbook
while its blocking approvals are still outstanding.

The P1-queue-clearance playbook has three steps that change fleet behaviour:
(a) dead-weight triage, (b) a throughput/concurrency raise, and
(c) prioritize-by-value reordering. Guardrail 8 holds all three until an
operator approves the standing escalation and the five blocking
human-decision items.

Every run since 2026-08-10 has correctly declined to execute them, but the
check lived in prose in a runbook, so each run re-derived it by hand and the
decision was only as good as the operator reading it that hour. This module
makes the check mechanical and gives it one answer.

Scope, deliberately: this gate is read-only. It decides whether the playbook
may proceed and explains why not. It does not triage, raise concurrency, or
reorder anything — implementing those is what the guardrail forbids, so this
module has no code path that could.

Fail-soft: missing or malformed records are treated as "not approved", which
is the safe direction. A record this gate cannot read is never a green light.
"""
from __future__ import annotations

import sys
from typing import Dict, Iterable, List, Optional

# The five human-decision items that block a P1 halt bypass. Named explicitly
# rather than discovered by query: the gate must fail when one goes missing
# from the database, and a wildcard lookup cannot tell "absent" from "none".
BLOCKING_HUMAN_DECISIONS = (
    "human-decision-p1-halt-bypassed-20260811-hb41",
    "human-decision-p1-halt-bypassed-again-20260812-b155",
    "human-decision-authorize-lane-target-raise-20260810-lt2x",
    "human-decision-runner-heartbeat-outage-20260810-m63m",
    "human-decision-mac-powerhub-dirty-tracked-file-20260809-vz84",
)

# The playbook steps Guardrail 8 holds.
HELD_PLAYBOOK_STEPS = (
    "dead-weight triage",
    "throughput/concurrency raise",
    "prioritize-by-value reordering",
)

HALT_REASON = (
    "HALT GUARDRAIL 8: escalation {escalation} is state={state} with "
    "operator_approved_at unset, and {pending}/{total} blocking human-decision "
    "items remain unapproved. Steps (a) dead-weight triage, "
    "(b) throughput/concurrency raise and (c) prioritize-by-value reordering "
    "are not executed."
)


def is_unapproved(value: Optional[str]) -> bool:
    """True when a record carries no real operator approval timestamp.

    The database writes a genuine NULL, the log renders it as the string
    "NULL", and JSON exports have produced "None" and "". All four mean the
    same thing and all four must gate identically.
    """
    if value is None:
        return True
    return str(value).strip().upper() in {"", "NULL", "NONE"}


def _index(records: Optional[Iterable[Dict]]) -> Dict[str, Dict]:
    """Index decision records by slug, tolerating junk entries."""
    indexed: Dict[str, Dict] = {}
    for record in records or []:
        if not isinstance(record, dict):
            continue
        slug = record.get("slug") or record.get("id")
        if slug:
            indexed[str(slug)] = record
    return indexed


def report_blocking_decisions(records: Optional[Iterable[Dict]]) -> List[Dict]:
    """Report approval status for each of the five blocking decisions.

    Every named decision appears in the output whether or not the query
    returned it, so a silently missing row is visible rather than absent.
    """
    indexed = _index(records)
    rows = []
    for slug in BLOCKING_HUMAN_DECISIONS:
        record = indexed.get(slug)
        if record is None:
            rows.append({
                "slug": slug,
                "present": False,
                "operator_approved_at": None,
                "unapproved": True,
                "status": "MISSING",
            })
            continue
        approved_at = record.get("operator_approved_at")
        unapproved = is_unapproved(approved_at)
        rows.append({
            "slug": slug,
            "present": True,
            "operator_approved_at": None if unapproved else approved_at,
            "unapproved": unapproved,
            "status": "PENDING" if unapproved else "APPROVED",
        })
    return rows


def evaluate_gate(
    escalation: Optional[Dict],
    decision_records: Optional[Iterable[Dict]] = None,
) -> Dict:
    """Decide whether the P1 queue-clearance playbook may execute its steps.

    Returns a dict with ``may_proceed`` (always False while anything is
    pending or unreadable), ``reason``, the per-decision ``decisions`` report,
    and ``executed_steps`` — which is empty by construction.
    """
    escalation = escalation if isinstance(escalation, dict) else {}
    state = str(escalation.get("state") or "").strip().upper()
    escalation_id = escalation.get("id") or escalation.get("slug") or "unknown escalation"
    halt_standing = state == "QUEUED" and is_unapproved(escalation.get("operator_approved_at"))

    decisions = report_blocking_decisions(decision_records)
    pending = [row for row in decisions if row["unapproved"]]
    missing = [row for row in decisions if not row["present"]]

    if halt_standing or pending:
        reason = HALT_REASON.format(
            escalation=escalation_id,
            state=state or "unknown",
            pending=len(pending),
            total=len(BLOCKING_HUMAN_DECISIONS),
        )
        if missing:
            reason += " {0} item(s) were not found and are treated as unapproved: {1}.".format(
                len(missing), ", ".join(row["slug"] for row in missing)
            )
        return {
            "may_proceed": False,
            "reason": reason,
            "halt_standing": halt_standing,
            "pending_count": len(pending),
            "missing_count": len(missing),
            "decisions": decisions,
            "executed_steps": [],
        }

    return {
        "may_proceed": True,
        "reason": (
            "Guardrail 8 escalation {0} is state={1} and all {2} blocking "
            "human-decision items are approved.".format(
                escalation_id, state or "unknown", len(BLOCKING_HUMAN_DECISIONS)
            )
        ),
        "halt_standing": False,
        "pending_count": 0,
        "missing_count": 0,
        "decisions": decisions,
        # Clearing the gate authorises the playbook to act; it does not make
        # this module the thing that acts.
        "executed_steps": [],
    }


def format_report(gate: Dict) -> str:
    """Render a gate decision as an operator-readable report."""
    lines = ["P1 QUEUE-CLEARANCE PLAYBOOK — APPROVAL GATE", ""]
    lines.append("Decision: {0}".format("PROCEED" if gate.get("may_proceed") else "HALT"))
    lines.append("Reason:   {0}".format(gate.get("reason", "")))
    lines.append("")
    lines.append("Blocking human-decision items:")
    for row in gate.get("decisions") or []:
        lines.append(
            "  [{0:<8}] {1} (operator_approved_at={2})".format(
                row["status"],
                row["slug"],
                row["operator_approved_at"] if row["operator_approved_at"] else "NULL",
            )
        )
    lines.append("")
    lines.append("Steps held by Guardrail 8 (not executed):")
    for step in HELD_PLAYBOOK_STEPS:
        lines.append("  - {0}".format(step))
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    """Read escalation + decision records as JSON and print the gate report.

    Exits non-zero whenever the playbook may not proceed, so a scheduled run
    that ignores the report still cannot pass a shell `&&`.
    """
    import argparse
    import json

    parser = argparse.ArgumentParser(description="P1 playbook approval gate")
    parser.add_argument(
        "path",
        nargs="?",
        help='JSON file: {"escalation": {...}, "decisions": [...]}; reads stdin when omitted',
    )
    parser.add_argument("--json", action="store_true", help="emit JSON instead of text")
    args = parser.parse_args(argv)

    raw = ""
    if args.path:
        with open(args.path, "r", encoding="utf-8", errors="replace") as handle:
            raw = handle.read()
    else:
        raw = sys.stdin.read()

    try:
        payload = json.loads(raw) if raw.strip() else {}
    except ValueError:
        # Unreadable input is not an approval.
        payload = {}

    gate = evaluate_gate(payload.get("escalation"), payload.get("decisions"))
    print(json.dumps(gate, indent=2) if args.json else format_report(gate))
    return 0 if gate["may_proceed"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
