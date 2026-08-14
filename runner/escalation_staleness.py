#!/usr/bin/env python3
"""
escalation_staleness.py — expire standing playbook halts that nobody is acting on.

The orch-operator playbook halts a loop when it stops improving: file an
escalation task, stop running the loop's steps until a human resolves it. The
halt has no expiry, and the escalation is only "resolved" by a human touching
it. When nobody touches it, the halt stands forever: escalate-p1-queue-clearance-
no-improvement-20260810-nk73 was filed 2026-08-10 22:01 UTC and was still QUEUED
with operator_approved_at NULL three days later, during which every hourly run
logged "did not execute (a)/(b)/(c)" while the queue it was meant to protect grew
from 776 to 864. The halt was designed to summon a human and instead became a
permanent stop.

A halt is a request for attention. If the request has gone unanswered long past
any plausible response time, continuing to honor it is not caution — it is a
loop that has quietly stopped doing its job. This module makes that state
observable and lets it expire:

    fresh      (< STALE_HOURS)   halt honored, human may still be coming
    stale      (>= STALE_HOURS)  halt honored, alert raised — nobody has looked
    abandoned  (>= EXPIRE_HOURS) halt expires; the loop resumes and says so

Expiry never resolves the escalation or hides it — the task stays QUEUED and the
alert stays open. It only stops the escalation from silently blocking unrelated
work forever.

Pure decision functions (classify_escalation, halt_decision) take data and
return verdicts, so they are testable without a database. Only run() touches
the DB, and every write is fail-soft.

Env vars:
    ORCH_ESCALATION_STALE_HOURS      hours before an escalation is 'stale'   (default 24)
    ORCH_ESCALATION_EXPIRE_HOURS     hours before a halt expires             (default 72)
    ORCH_ESCALATION_EXPIRY_ENABLED   "true" (default) to allow halt expiry
"""
import argparse
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db  # noqa: E402

STALE_HOURS = float(os.environ.get("ORCH_ESCALATION_STALE_HOURS", "24"))
EXPIRE_HOURS = float(os.environ.get("ORCH_ESCALATION_EXPIRE_HOURS", "72"))
EXPIRY_ENABLED = os.environ.get(
    "ORCH_ESCALATION_EXPIRY_ENABLED", "true").lower() in ("1", "true", "yes", "on")

# Slug prefixes the playbooks use when they stop a loop and ask for a human.
ESCALATION_PREFIXES = ("escalate-", "human-decision-")

ALERT_KIND = "escalation_unanswered"


# ── helpers ────────────────────────────────────────────────────────
def _now():
    return dt.datetime.now(dt.timezone.utc)


def _parse_ts(value):
    """Parse a Postgres/ISO timestamp into an aware datetime, or None."""
    if not value:
        return None
    if isinstance(value, dt.datetime):
        return value if value.tzinfo else value.replace(tzinfo=dt.timezone.utc)
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)


def is_escalation(task):
    """True when *task* is a playbook escalation / human-decision record."""
    slug = (task or {}).get("slug") or ""
    return slug.startswith(ESCALATION_PREFIXES)


def age_hours(task, now=None):
    """Hours since the escalation was filed; 0.0 when the timestamp is unusable."""
    created = _parse_ts((task or {}).get("created_at"))
    if created is None:
        return 0.0
    return max(0.0, ((now or _now()) - created).total_seconds() / 3600.0)


# ── decisions ──────────────────────────────────────────────────────
def classify_escalation(task, now=None, stale_hours=None, expire_hours=None):
    """Classify one escalation task.

    Returns dict: slug, age_hours, answered, status
    where status is 'answered' | 'fresh' | 'stale' | 'abandoned'.
    """
    stale_h = STALE_HOURS if stale_hours is None else stale_hours
    expire_h = EXPIRE_HOURS if expire_hours is None else expire_hours
    hours = age_hours(task, now)

    # Any operator touch counts as answered, whether or not it approved the ask:
    # the point of the halt is to get a human to look, not to get a yes.
    answered = bool(task.get("operator_approved_at")
                    or task.get("counsel_approved_at")
                    or (task.get("state") or "").upper() not in ("QUEUED", "BLOCKED"))

    if answered:
        status = "answered"
    elif hours >= expire_h:
        status = "abandoned"
    elif hours >= stale_h:
        status = "stale"
    else:
        status = "fresh"

    return {
        "slug": task.get("slug"),
        "id": task.get("id"),
        "age_hours": round(hours, 1),
        "answered": answered,
        "status": status,
    }


def halt_decision(escalations, expiry_enabled=None):
    """Decide whether a standing playbook halt should still be honored.

    *escalations* is an iterable of classify_escalation() results.

    The halt is released only when there is at least one escalation and every
    unanswered one has been abandoned. A single fresh or stale escalation keeps
    the halt: the point is to expire dead requests, not to race a human who is
    partway through reading them.
    """
    enabled = EXPIRY_ENABLED if expiry_enabled is None else expiry_enabled
    open_ones = [e for e in escalations if not e["answered"]]

    if not open_ones:
        return {"honor_halt": False, "reason": "no unanswered escalations",
                "expired": [], "blocking": []}

    abandoned = [e for e in open_ones if e["status"] == "abandoned"]
    blocking = [e for e in open_ones if e["status"] != "abandoned"]

    if blocking or not abandoned:
        return {"honor_halt": True,
                "reason": "unanswered escalation still within response window",
                "expired": [], "blocking": [e["slug"] for e in blocking or open_ones]}

    if not enabled:
        return {"honor_halt": True,
                "reason": "halt expiry disabled (ORCH_ESCALATION_EXPIRY_ENABLED)",
                "expired": [], "blocking": [e["slug"] for e in abandoned]}

    oldest = max(e["age_hours"] for e in abandoned)
    return {"honor_halt": False,
            "reason": (f"{len(abandoned)} escalation(s) unanswered for up to "
                       f"{oldest:.0f}h — halt expired, loop resumes; "
                       f"escalations remain queued"),
            "expired": [e["slug"] for e in abandoned],
            "blocking": []}


# ── database ───────────────────────────────────────────────────────
def open_escalations(limit=200):
    """Fetch QUEUED/BLOCKED escalation tasks. Returns [] on any DB failure."""
    rows = []
    for prefix in ESCALATION_PREFIXES:
        try:
            rows.extend(db.select("tasks", {
                "select": "id,slug,state,created_at,operator_approved_at,counsel_approved_at",
                "slug": f"like.{prefix}*",
                "state": "in.(QUEUED,BLOCKED)",
                "order": "created_at.asc",
                "limit": str(limit),
            }) or [])
        except Exception as exc:
            print(f"escalation_staleness: select failed for {prefix}: {str(exc)[:120]}",
                  file=sys.stderr)
    # One query per prefix, so dedupe by id: a task counted twice would inflate
    # the counts and could open two alerts for the same escalation.
    seen, unique = set(), []
    for row in rows:
        key = row.get("id") or row.get("slug")
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    return unique


def _alert_open(slug):
    try:
        return bool(db.select("runner_alerts", {
            "select": "id", "kind": f"eq.{ALERT_KIND}",
            "detail": f"ilike.*slug={slug}*", "resolved": "eq.false", "limit": "1",
        }) or [])
    except Exception:
        return False


def emit_alerts(classified, dry_run=False):
    """Open one unresolved alert per stale/abandoned escalation. Returns count."""
    opened = 0
    for item in classified:
        if item["status"] not in ("stale", "abandoned"):
            continue
        if _alert_open(item["slug"]):
            continue
        if dry_run:
            opened += 1
            continue
        try:
            db.insert("runner_alerts", {
                "kind": ALERT_KIND,
                "detail": (f"slug={item['slug']} status={item['status']} "
                           f"age_hours={item['age_hours']} — escalation filed by a "
                           f"playbook halt has had no operator response"),
                "resolved": False,
            })
            opened += 1
        except Exception as exc:
            print(f"escalation_staleness: alert write failed: {str(exc)[:120]}",
                  file=sys.stderr)
    return opened


def run(dry_run=False):
    """Classify open escalations, alert on unanswered ones, report the halt verdict."""
    now = _now()
    tasks = [t for t in open_escalations() if is_escalation(t)]
    classified = [classify_escalation(t, now=now) for t in tasks]
    decision = halt_decision(classified)
    alerted = emit_alerts(classified, dry_run=dry_run)
    return {
        "checked": len(classified),
        "counts": {s: sum(1 for c in classified if c["status"] == s)
                   for s in ("answered", "fresh", "stale", "abandoned")},
        "alerts_opened": alerted,
        "honor_halt": decision["honor_halt"],
        "reason": decision["reason"],
        "expired": decision["expired"],
        "blocking": decision["blocking"],
        "dry_run": dry_run,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="classify and report; open no alerts")
    args = parser.parse_args()
    import json
    print(json.dumps(run(dry_run=args.dry_run), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
