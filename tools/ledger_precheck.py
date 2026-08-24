#!/usr/bin/env python3
"""Decide whether a reconcile task's ledger already exists before scanning.

Why this exists
---------------
`reconcile_all_evidence.py` takes many minutes on this repo, and the fleet queues
reconcile tasks in batches that frequently include fingerprints whose ledger a
previous run already wrote to `coordination_tasks`. Discovering that AFTER the
scan wastes the whole scan; discovering it after the commit is worse, because the
executor then pushes a duplicate ledger over work that was already complete.

Observed cost of not having this check: two queued tasks
(`chatgpt-local-reconcile-beethoven-c648ef526fa6` and `...-69cb4d6354da`) each
already had a complete 1289-item ledger with zero UNKNOWN items recorded under
the correct `task_slug`. Both were re-claimed and would have been re-scanned.

What "already complete" means
-----------------------------
A ledger counts as complete for a fingerprint only when ALL of:
  * at least `--min-items` records carry that fingerprint or task slug, and
  * zero of them are UNKNOWN, and
  * every record with remaining value has a durable disposition (a queued
    follow-up, a branch, or a commit) — an item classified RECOVERABLE_VALUE
    with no provenance at all is not durable, so the task is NOT complete.

Anything short of that returns "scan" rather than "superseded": a partial ledger
must never be able to mark a task done.

This module holds pure decision logic so it is unit-testable without a database.
The caller supplies records as JSON (a list of objects, or objects with a
`payload` string holding the JSON, which is how `coordination_tasks` stores them).

Usage
-----
    # records.json is whatever your DB query returned
    python3 tools/ledger_precheck.py --records records.json \
        --fingerprint <audit-sha> [--slug <task-slug>] [--min-items 1]

Prints a JSON verdict on stdout. Exit 0 = already complete (supersede),
exit 1 = scan needed, exit 2 = bad input.
"""

from __future__ import annotations

import argparse
import json
import sys

KNOWN_CLASSIFICATIONS = frozenset({
    "ALREADY_PRESENT",
    "SUPERSEDED_BY_NEWER",
    "ACTIVE_IN_ANOTHER_TASK",
    "RECOVERABLE_VALUE",
    "CONFLICTED_NEEDS_FOCUSED_TASK",
})

# Classifications that leave work behind and therefore demand durable provenance.
NEEDS_PROVENANCE = frozenset({"RECOVERABLE_VALUE", "CONFLICTED_NEEDS_FOCUSED_TASK"})

# Any one of these fields, non-empty, makes an item's disposition durable.
PROVENANCE_FIELDS = ("result_task", "result_branch", "result_commit", "disposition")


def coerce_record(raw) -> dict:
    """Normalise one DB row into a ledger record dict. Returns {} if unusable.

    Accepts either the record itself or a row wrapping it in a `payload` string,
    which is how `coordination_tasks` persists these.
    """
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return {}
    if not isinstance(raw, dict):
        return {}
    payload = raw.get("payload")
    if isinstance(payload, str):
        try:
            inner = json.loads(payload)
        except ValueError:
            return {}
        if isinstance(inner, dict):
            # Row-level status is useful context; payload keys win on conflict.
            merged = {"status": raw.get("status")} if raw.get("status") else {}
            merged.update(inner)
            return merged
        return {}
    if isinstance(payload, dict):
        return payload
    return raw


def load_records(path: str) -> list:
    """Read a JSON list of records. Returns [] on any failure rather than raising."""
    try:
        with open(path, "r", errors="replace") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return []
    if isinstance(data, dict):
        data = data.get("records") or data.get("items") or []
    if not isinstance(data, list):
        return []
    out = []
    for raw in data:
        rec = coerce_record(raw)
        if rec:
            out.append(rec)
    return out


def matches(record: dict, fingerprint: str, slug: str) -> bool:
    """Does this record belong to the fingerprint (or slug) under test?

    Fingerprints are compared on a shared prefix so an abbreviated stamp still
    matches, but a prefix shorter than 8 chars is rejected as too weak to
    identify a ledger.
    """
    if not isinstance(record, dict):
        return False
    if slug:
        for key in ("task_slug", "result_task", "slug"):
            if (record.get(key) or "") == slug:
                return True
    if fingerprint:
        got = (record.get("audit_fingerprint") or record.get("fingerprint") or "")
        n = min(len(got), len(fingerprint))
        if n >= 8 and got[:n] == fingerprint[:n]:
            return True
    return False


def classification_of(record: dict) -> str:
    label = (record or {}).get("classification") or "UNKNOWN"
    return label if label in KNOWN_CLASSIFICATIONS else "UNKNOWN"


def has_provenance(record: dict) -> bool:
    """True when the record records a durable disposition for remaining work."""
    for field in PROVENANCE_FIELDS:
        if str((record or {}).get(field) or "").strip():
            return True
    return False


def evaluate(records, fingerprint: str, slug: str = "", min_items: int = 1) -> dict:
    """Pure verdict: should the caller supersede the task or run the scan?"""
    mine = [r for r in (records or []) if matches(r, fingerprint, slug)]
    counts: dict = {}
    for r in mine:
        label = classification_of(r)
        counts[label] = counts.get(label, 0) + 1
    unknown = counts.get("UNKNOWN", 0)
    undurable = [r for r in mine
                 if classification_of(r) in NEEDS_PROVENANCE and not has_provenance(r)]

    if len(mine) < max(1, min_items):
        verdict, reason = "scan", (
            "only %d matching ledger record(s); need at least %d"
            % (len(mine), max(1, min_items)))
    elif unknown:
        verdict, reason = "scan", (
            "%d UNKNOWN item(s) in the existing ledger; completion bar is zero" % unknown)
    elif undurable:
        verdict, reason = "scan", (
            "%d item(s) with remaining value carry no durable disposition" % len(undurable))
    else:
        verdict, reason = "supersede", (
            "%d ledger record(s) already recorded, 0 UNKNOWN, every item with "
            "remaining value durably queued" % len(mine))

    return {"verdict": verdict, "reason": reason, "matched": len(mine),
            "counts": counts, "unknown": unknown,
            "undurable": len(undurable),
            "fingerprint": fingerprint, "slug": slug}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--records", required=True,
                    help="JSON file of coordination_tasks rows")
    ap.add_argument("--fingerprint", default="")
    ap.add_argument("--slug", default="")
    ap.add_argument("--min-items", type=int, default=1)
    args = ap.parse_args(argv)

    if not args.fingerprint and not args.slug:
        sys.stderr.write("refused: pass --fingerprint and/or --slug\n")
        return 2

    verdict = evaluate(load_records(args.records), args.fingerprint,
                       args.slug, args.min_items)
    print(json.dumps(verdict, indent=1, sort_keys=True))
    return 0 if verdict["verdict"] == "supersede" else 1


if __name__ == "__main__":
    raise SystemExit(main())
