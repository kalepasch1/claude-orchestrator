#!/usr/bin/env python3
"""
guardrail_hold_streak.py — notice when the same guardrail hold has been
re-logged hour after hour with nobody acting on it.

The P1-queue-clearance playbook runs hourly. When a Guardrail 8 stop is
standing it correctly declines to act and writes a HOLD log. That is the right
behaviour once. Repeated sixteen times against the same unapproved escalation
it is no longer a decision, it is a loop: every run re-derives the same halt
from scratch, writes the same log, and the escalation ages another hour
without anyone being told it needs a human.

This module reads those HOLD logs and reports the streak — how many
consecutive runs held on each escalation, and how long it has gone unaddressed
— so that "still holding" can escalate instead of accumulating.

Read-only and advisory. It recommends that a human be paged; it does not
triage dead weight, raise throughput, or reorder by value. Those are the steps
the guardrail holds, and nothing here can execute them.

Fail-soft: unparseable input yields empty results, never an exception.
"""
from __future__ import annotations

import re
import sys
from typing import Dict, List, Optional

# A hold that has repeated this many times, or aged this many hours without an
# operator, has stopped being a routine decline and needs a human.
HOLD_STREAK_ESCALATION_THRESHOLD = 3
HOLD_HOURS_ESCALATION_THRESHOLD = 24.0

_UUID = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"

_RE_RUN_ID = re.compile(r"(log-p1-queue-clearance-\d{8}-[a-z0-9]+)")
_RE_ESCALATION_SLUG = re.compile(r"(escalate-p1-queue-clearance-[a-z0-9\-]*[a-z0-9])")
# The compactor hard-wraps, so "id" and the uuid are routinely split across a
# newline; match any run of whitespace rather than a single space.
_RE_ESCALATION_UUID = re.compile(r"\bid[=\s]+\(?(" + _UUID + r")\)?")
_RE_RUN_TS = re.compile(r"(\d{4}-\d{2}-\d{2})\s*~?\s*(\d{2}:\d{2})")

# "~15h later", "~59h unaddressed", "~40h58m unaddressed by a hum..."
_RE_UNADDRESSED = re.compile(
    r"~?\s*(\d+)\s*h(?:\s*(\d+)\s*m)?\s*(?:later|unaddressed)", re.IGNORECASE
)

# A run that held is one that declined to execute the playbook steps. Most say
# so outright ("HOLDING", "did NOT execute"), but a run that discovers the stop
# mid-way records only that it found a standing stop condition — that is still
# a hold, and missing it would undercount the streak.
_HOLD_MARKERS = ("did not execute", "holding", "stop condition")


def _iso(date_part: str, time_part: str) -> str:
    return "{0}T{1}:00Z".format(date_part, time_part)


def _run_blocks(text: str) -> List[Dict]:
    """Split consolidated log text into one block per distinct run id."""
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


def _hours_unaddressed(block_text: str) -> Optional[float]:
    match = _RE_UNADDRESSED.search(block_text)
    if not match:
        return None
    try:
        hours = float(match.group(1))
    except (TypeError, ValueError):
        return None
    if match.group(2):
        try:
            hours += float(match.group(2)) / 60.0
        except (TypeError, ValueError):
            pass
    return round(hours, 2)


def parse_hold_logs(text: Optional[str]) -> List[Dict]:
    """Extract one record per P1 run that held on a guardrail stop."""
    if not text:
        return []

    entries: List[Dict] = []
    for block in _run_blocks(text):
        lowered = block["text"].lower()
        if not any(marker in lowered for marker in _HOLD_MARKERS):
            continue

        slug_match = _RE_ESCALATION_SLUG.search(block["text"])
        uuid_match = _RE_ESCALATION_UUID.search(block["text"])
        ts_match = _RE_RUN_TS.search(block["text"])

        entries.append({
            "run_id": block["run_id"],
            "ran_at": _iso(ts_match.group(1), ts_match.group(2)) if ts_match else None,
            "escalation_slug": slug_match.group(1) if slug_match else None,
            "escalation_id": uuid_match.group(1) if uuid_match else None,
            "hours_unaddressed": _hours_unaddressed(block["text"]),
        })
    return entries


def _escalation_key(entry: Dict) -> str:
    return entry.get("escalation_slug") or entry.get("escalation_id") or "unknown"


def summarize_hold_streaks(entries: Optional[List[Dict]]) -> Dict:
    """Group hold records by escalation and report each streak.

    ``needs_human_escalation`` trips on either signal: enough consecutive
    holds, or enough elapsed time. A fast hourly cadence reaches the streak
    threshold first; a slow one reaches the age threshold first. Requiring
    both would let either cadence hide the stall.
    """
    entries = entries or []
    grouped: Dict[str, List[Dict]] = {}
    for entry in entries:
        grouped.setdefault(_escalation_key(entry), []).append(entry)

    escalations = []
    for key, group in grouped.items():
        dated = sorted([e for e in group if e.get("ran_at")], key=lambda e: e["ran_at"])
        ordered = dated or group
        hours = [e["hours_unaddressed"] for e in group if e.get("hours_unaddressed") is not None]
        max_hours = max(hours) if hours else None
        streak = len(group)

        needs = streak >= HOLD_STREAK_ESCALATION_THRESHOLD or (
            max_hours is not None and max_hours >= HOLD_HOURS_ESCALATION_THRESHOLD
        )

        # Only some runs bother to print the uuid alongside the slug; take it
        # from whichever run did rather than from whichever ran first.
        escalation_id = next(
            (e.get("escalation_id") for e in group if e.get("escalation_id")), None
        )

        escalations.append({
            "escalation_slug": group[0].get("escalation_slug"),
            "escalation_id": escalation_id,
            "consecutive_holds": streak,
            "first_hold_at": ordered[0].get("ran_at"),
            "last_hold_at": ordered[-1].get("ran_at"),
            "max_hours_unaddressed": max_hours,
            "run_ids": [e["run_id"] for e in ordered],
            "needs_human_escalation": needs,
            "recommendation": (
                "Page a human: {0} consecutive P1 runs have held on {1}"
                "{2}. The hold itself is correct — the absence of an operator "
                "response is the problem. Advisory only; no triage, throughput "
                "or priority change is applied.".format(
                    streak,
                    key,
                    "" if max_hours is None else " over ~{0}h".format(max_hours),
                )
                if needs
                else "Hold streak within normal range; continue routine hourly checks."
            ),
        })

    escalations.sort(key=lambda item: item["consecutive_holds"], reverse=True)

    return {
        "escalations": escalations,
        "total_hold_runs": len(entries),
        "needs_human_escalation": any(item["needs_human_escalation"] for item in escalations),
        "safety": {"does_not_change_throughput_or_priority": True},
    }


def analyze(text: Optional[str]) -> Dict:
    """Parse consolidated HOLD log text and summarize the streaks."""
    return summarize_hold_streaks(parse_hold_logs(text))


def main(argv: Optional[List[str]] = None) -> int:
    """Read consolidated log text and print the hold-streak report as JSON."""
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Guardrail hold-streak report")
    parser.add_argument("path", nargs="?", help="log file; reads stdin when omitted")
    args = parser.parse_args(argv)

    if args.path:
        with open(args.path, "r", encoding="utf-8", errors="replace") as handle:
            text = handle.read()
    else:
        text = sys.stdin.read()

    print(json.dumps(analyze(text), indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
