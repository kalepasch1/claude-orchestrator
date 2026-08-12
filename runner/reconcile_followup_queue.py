#!/usr/bin/env python3
"""
reconcile_followup_queue.py — turn a reconciliation classification into durable queue
and branch provenance, and refuse to call the reconciliation complete without it.

WHY THIS IS A SEPARATE STEP
---------------------------
Classifying recovered ChatGPT/Codex evidence is only half the job. The recurring failure
is what happens after: an item is correctly marked RECOVERABLE_VALUE or
CONFLICTED_NEEDS_FOCUSED_TASK, a summary says "queued a follow-up", and no row is ever
written. The next sweep re-discovers the same ref, re-classifies it, and reports it as
new — the fleet has now spent three sessions on one branch and shipped none of it.

So provenance is made mechanical here:

  * `plan_followups()` decides what each item needs — a focused conflict task, a recovery
    task, or nothing — and is a pure function, so it is testable without a DB or a repo.
  * `queue_followups()` writes those rows **idempotently**. A slug already present in the
    queue (in any live or terminal state) is adopted, not duplicated: re-running a
    reconciliation must converge, not fan out.
  * `provenance_gate()` is the completion bar. It fails on any UNKNOWN item, and on any
    item with remaining value that has no task, branch or commit to point at. "Zero
    UNKNOWN items and durable queue/branch provenance for every item with remaining
    value" stops being a claim in a summary and becomes a boolean.

Every evidence source stays read-only: this module writes queue rows, never git.

Public API
----------
    plan_followups(records, fingerprint)          -> [plan, ...]
    queue_followups(plans, *, db=None, ...)       -> dict
    provenance_gate(records, plans)               -> dict
    run(records, fingerprint, *, db=None)         -> dict

Environment
-----------
    ORCH_FOLLOWUP_QUEUE_ENABLED   Kill switch (default: true)
    ORCH_FOLLOWUP_MAX_PER_RUN     Cap on rows queued in one pass (default: 25)
"""
from __future__ import annotations

import json
import os
import re
import time

# Classifications that carry remaining value and therefore REQUIRE provenance.
NEEDS_PROVENANCE = ("RECOVERABLE_VALUE", "CONFLICTED_NEEDS_FOCUSED_TASK")

# Classifications that are complete as-is: the work shipped, is owned elsewhere, or lost
# to a newer implementation. These need a ledger row, not a task.
SETTLED = ("ALREADY_PRESENT", "SUPERSEDED_BY_NEWER", "ACTIVE_IN_ANOTHER_TASK")

MAX_PER_RUN = int(os.environ.get("ORCH_FOLLOWUP_MAX_PER_RUN", "25"))

# Any state at all counts as "already queued". A slug sitting in DONE or QUARANTINED has
# been dealt with; re-queueing it is exactly the duplicate-work loop this module exists
# to stop.
_SLUG_SAFE = re.compile(r"[^a-z0-9-]+")


def _enabled() -> bool:
    return os.environ.get("ORCH_FOLLOWUP_QUEUE_ENABLED", "true").strip().lower() \
        not in ("0", "false", "no", "off")


def _slugify(value: str, *, prefix: str = "", limit: int = 90) -> str:
    base = _SLUG_SAFE.sub("-", (value or "").strip().lower()).strip("-")
    base = re.sub(r"-{2,}", "-", base)
    slug = f"{prefix}{base}" if prefix else base
    return slug[:limit].strip("-") or f"{prefix}unnamed"


# ── Planning (pure) ─────────────────────────────────────────────────────────

def _source_slug(record: dict) -> str:
    """A stable slug for the evidence item, independent of run order.

    Derived from the source ref rather than a counter so that two reconciliations of the
    same evidence produce the same slug and therefore collide instead of duplicating.
    """
    source = record.get("source") or record.get("name") or ""
    for prefix in ("refs/heads/agent/", "refs/heads/", "refs/"):
        if source.startswith(prefix):
            source = source[len(prefix):]
            break
    return _slugify(source)


def plan_followups(records, fingerprint: str) -> list:
    """What each classified item needs. Pure: no DB, no git, no clock beyond the stamp.

    Returns one plan per record, including `action="none"` for settled items — a plan
    list that silently omits items cannot be checked for completeness.
    """
    plans = []
    for record in records or []:
        cls = str(record.get("classification") or "").upper()
        source = record.get("source") or record.get("name") or ""
        plan = {
            "source": source,
            "classification": cls,
            "action": "none",
            "slug": "",
            "kind": "",
            "prompt": "",
            "reason": "",
            "fingerprint": fingerprint,
        }

        if cls == "CONFLICTED_NEEDS_FOCUSED_TASK":
            plan["action"] = "queue"
            plan["kind"] = "recovery"
            plan["slug"] = _slugify(_source_slug(record), prefix="reconcile-conflict-")
            plan["prompt"] = (
                f"Focused reconciliation of conflicted recovered evidence `{source}`.\n\n"
                f"The reconciliation sweep (audit fingerprint {fingerprint}) found this "
                f"ref carries {record.get('unique_commits', '?')} unique commit(s) that do "
                f"NOT merge cleanly onto the default branch.\n\n"
                f"Conflict detail: {record.get('detail') or 'see merge-tree output'}\n"
                f"Paths: {', '.join(record.get('paths') or []) or 'unknown'}\n\n"
                f"Treat `{source}` as READ-ONLY evidence. Work in a newly allocated "
                f"isolated worktree, resolve the conflict by taking the newest/most "
                f"complete implementation on each hunk, run the affected tests, and "
                f"deliver through the normal agent branch + merge train. Do not force an "
                f"overwrite and do not delete, reset, clean, pop or move the evidence.")
            plan["reason"] = "conflicts must be resolved by a focused task, never forced"

        elif cls == "RECOVERABLE_VALUE":
            plan["action"] = "queue"
            plan["kind"] = "recovery"
            plan["slug"] = _slugify(_source_slug(record), prefix="reconcile-recover-")
            plan["prompt"] = (
                f"Recover the unique value on `{source}`.\n\n"
                f"The reconciliation sweep (audit fingerprint {fingerprint}) classified "
                f"this as RECOVERABLE_VALUE: {record.get('unique_commits', '?')} unique "
                f"commit(s) that apply cleanly and that no live task or remote branch "
                f"already owns.\n\n"
                f"Paths: {', '.join(record.get('paths') or []) or 'unknown'}\n\n"
                f"Apply the minimum coherent diff in a newly allocated isolated worktree, "
                f"run the relevant tests, and deliver through the normal agent branch + "
                f"merge train. `{source}` is READ-ONLY evidence — do not delete, reset, "
                f"clean, pop or move it.")
            plan["reason"] = "unique unclaimed work that applies cleanly"

        elif cls in SETTLED:
            plan["reason"] = f"{cls.lower().replace('_', ' ')} — ledger row only"

        else:
            plan["action"] = "escalate"
            plan["reason"] = (f"unclassified evidence ({cls or 'UNKNOWN'}); completion "
                              f"requires zero UNKNOWN items")

        plans.append(plan)
    return plans


# ── Queueing (idempotent) ───────────────────────────────────────────────────

def existing_slugs(db, project_id: str = "") -> set:
    """Every slug already in the queue, in ANY state. Fail-soft: empty set.

    Deliberately not filtered by state. A slug in DONE has been handled; re-queueing it
    is the duplicate-work loop. The safe failure mode of an empty set is a duplicate
    task, which the operator can close — the unsafe one would be silently dropping work.
    """
    try:
        rows = db.select_all("tasks", {"select": "slug"}) or []
    except Exception:  # noqa: BLE001 — fail-soft
        return set()
    return {row["slug"] for row in rows if row.get("slug")}


def queue_followups(plans, *, db=None, project_id: str = "", base_branch: str = "master",
                    source_label: str = "chatgpt-local-reconcile") -> dict:
    """Insert one task row per actionable plan, skipping slugs the queue already has."""
    out = {"queued": [], "adopted": [], "escalated": [], "failed": [], "error": None}
    if not _enabled():
        out["error"] = "disabled by ORCH_FOLLOWUP_QUEUE_ENABLED"
        return out
    if db is None:
        try:
            import db as _db
            db = _db
        except Exception as exc:  # noqa: BLE001 — fail-soft
            out["error"] = f"db unavailable: {type(exc).__name__}: {exc}"
            return out

    known = existing_slugs(db, project_id)
    queued_this_run = 0

    for plan in plans or []:
        if plan.get("action") == "escalate":
            out["escalated"].append(plan.get("source"))
            continue
        if plan.get("action") != "queue":
            continue

        slug = plan.get("slug") or ""
        if not slug:
            out["failed"].append({"source": plan.get("source"), "error": "empty slug"})
            continue
        if slug in known:
            # Already represented. Adopt it as this item's provenance rather than
            # creating a second task for the same evidence.
            out["adopted"].append({"source": plan.get("source"), "slug": slug})
            plan["queued_slug"] = slug
            continue
        if queued_this_run >= MAX_PER_RUN:
            out["failed"].append({"source": plan.get("source"),
                                  "error": f"per-run cap {MAX_PER_RUN} reached"})
            continue

        row = {
            "slug": slug,
            "kind": plan.get("kind") or "recovery",
            "state": "QUEUED",
            "prompt": plan.get("prompt") or "",
            "base_branch": base_branch,
            "note": f"{source_label}: follow-up for {plan.get('source')} "
                    f"({plan.get('classification')}) fingerprint={plan.get('fingerprint')}",
        }
        if project_id:
            row["project_id"] = project_id
        try:
            db.insert("tasks", row, upsert=False)
        except Exception as exc:  # noqa: BLE001 — per-row fail-soft
            out["failed"].append({"source": plan.get("source"),
                                  "error": f"{type(exc).__name__}: {exc}"})
            continue
        known.add(slug)
        queued_this_run += 1
        plan["queued_slug"] = slug
        out["queued"].append({"source": plan.get("source"), "slug": slug})

    return out


# ── Completion bar ──────────────────────────────────────────────────────────

def provenance_gate(records, plans) -> dict:
    """The reconciliation's completion bar, as a boolean rather than a claim.

    Passes only when BOTH hold:
      * zero UNKNOWN / unclassified items, and
      * every item with remaining value points at a durable artefact — a queued or
        adopted task slug, an existing branch, or a commit SHA.
    """
    result = {"ok": False, "unknown": [], "unprovenanced": [], "covered": 0,
              "settled": 0, "total": len(records or [])}
    by_source = {p.get("source"): p for p in (plans or [])}

    for record in records or []:
        cls = str(record.get("classification") or "").upper()
        source = record.get("source") or record.get("name") or ""

        if cls not in NEEDS_PROVENANCE and cls not in SETTLED:
            result["unknown"].append(source)
            continue
        if cls in SETTLED:
            result["settled"] += 1
            continue

        plan = by_source.get(source) or {}
        provenance = (plan.get("queued_slug") or record.get("task")
                      or record.get("branch") or record.get("commit"))
        if provenance:
            result["covered"] += 1
        else:
            result["unprovenanced"].append(source)

    result["ok"] = not result["unknown"] and not result["unprovenanced"]
    return result


def run(records, fingerprint: str, *, db=None, project_id: str = "",
        base_branch: str = "master") -> dict:
    """Plan, queue and gate in one pass. Returns a report; never raises."""
    report = {"fingerprint": fingerprint, "plans": [], "queue": None, "gate": None,
              "complete": False, "error": None}
    if not _enabled():
        report["error"] = "disabled by ORCH_FOLLOWUP_QUEUE_ENABLED"
        return report

    plans = plan_followups(records, fingerprint)
    report["plans"] = plans
    report["queue"] = queue_followups(plans, db=db, project_id=project_id,
                                      base_branch=base_branch)
    report["gate"] = provenance_gate(records, plans)
    report["complete"] = bool(report["gate"]["ok"]) and not report["queue"]["failed"]
    report["stamp"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return report


def main(argv=None) -> int:
    import argparse
    import sys
    ap = argparse.ArgumentParser(
        description="Queue follow-ups for a reconciliation and gate on provenance.")
    ap.add_argument("records_json", help="path to a JSON list of classified records, "
                                         "or - for stdin")
    ap.add_argument("fingerprint")
    ap.add_argument("--project-id", default="")
    ap.add_argument("--base-branch", default="master")
    ap.add_argument("--dry-run", action="store_true",
                    help="plan and gate without writing queue rows")
    args = ap.parse_args(argv)

    try:
        raw = sys.stdin.read() if args.records_json == "-" \
            else open(args.records_json).read()
        records = json.loads(raw)
    except (OSError, ValueError) as exc:
        print(f"could not read records: {exc}")
        return 2

    if args.dry_run:
        plans = plan_followups(records, args.fingerprint)
        report = {"plans": plans, "gate": provenance_gate(records, plans),
                  "queue": None, "complete": False}
    else:
        report = run(records, args.fingerprint, project_id=args.project_id,
                     base_branch=args.base_branch)
    print(json.dumps(report, indent=2, default=str))
    return 0 if report.get("complete") else 1


if __name__ == "__main__":
    raise SystemExit(main())
