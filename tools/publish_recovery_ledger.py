#!/usr/bin/env python3
"""Publish a recovery ledger to `coordination_tasks`, one record per evidence item.

The recovery contract requires durable queue provenance for every classified item,
not just the ones that still hold value: a ledger that lives only in a git blob is
not queryable, and "we looked at 600 refs" is worth nothing if nobody can ask which
ref ended up where.

Read-only with respect to the evidence. The only writes are INSERTs into
`coordination_tasks`, and the run is idempotent: an item already published under
the same audit fingerprint and source is skipped, so a re-run after a partial
failure does not duplicate the ledger.

Status mapping mirrors the classification vocabulary:
  RECOVERABLE_VALUE, CONFLICTED_NEEDS_FOCUSED_TASK -> open   (still owes someone work)
  everything else                                  -> closed (resolved by the pass)

Usage:
    python3 tools/publish_recovery_ledger.py \
        --ledger .orch/recovery-ledger-<short>.json \
        --task-slug chatgpt-local-reconcile-beethoven-<short> \
        --project beethoven --branch agent/<slug> --commit <sha> [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os
import sys

def _runner_dir() -> str:
    """Directory to import `db` from.

    An agent worktree carries tracked files only, so its `runner/.env` — which is
    gitignored — does not exist and `db` would refuse to talk to Supabase. Prefer
    a runner that actually has credentials, falling back to the local one so the
    main checkout keeps working unchanged.
    """
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidates = [
        os.environ.get("ORCH_RUNNER_DIR", ""),
        os.path.join(here, "runner"),
        os.path.expanduser(
            "~/Documents/beethoven/claude-orchestrator/runner"),
    ]
    for cand in candidates:
        if cand and os.path.isfile(os.path.join(cand, ".env")):
            return cand
    return os.path.join(here, "runner")


sys.path.insert(0, _runner_dir())

OPEN_CLASSIFICATIONS = {"RECOVERABLE_VALUE", "CONFLICTED_NEEDS_FOCUSED_TASK"}
TASK_TYPE = "chatgpt_local_reconcile_ledger"
# Ledgers of a few hundred items are normal; the cap only stops a runaway input
# from writing an unbounded number of rows in one pass.
MAX_ROWS = int(os.environ.get("ORCH_RECOVERY_LEDGER_MAX_ROWS", "2000"))


def status_for(classification: str) -> str:
    return "open" if classification in OPEN_CLASSIFICATIONS else "closed"


def build_payload(item: dict, ledger: dict, args) -> dict:
    """One flat, queryable record. Files are capped so a 900-path diff does not
    become the row: the ledger blob on the branch stays the full record."""
    files = item.get("files") or item.get("recover_files") or []
    return {
        "audit_fingerprint": ledger.get("audit_fingerprint", ""),
        "task_slug": args.task_slug,
        "project": args.project,
        "source": item.get("ref", ""),
        "source_kind": item.get("kind", ledger.get("evidence_kind", "")),
        "classification": item.get("classification", "UNKNOWN"),
        "disposition": item.get("disposition", ""),
        "evidence": item.get("evidence", ""),
        "files": sorted(set(files))[:20],
        "file_count": len(set(files)),
        "branch": args.branch,
        "commit": args.commit,
    }


def already_published(fingerprint: str, db) -> "set[str]":
    """Sources already carrying a record for this fingerprint.

    Fail-soft: if the lookup fails we return an empty set and let the insert
    path decide. A failed dedupe read must not stop the ledger from landing —
    an unpublished item is a worse outcome than a duplicate one.
    """
    try:
        # Filter server-side on the fingerprint. An unfiltered scan of
        # coordination_tasks returns exactly the 1000-row page cap, which means
        # the far end of the table is invisible and the dedupe silently misses
        # earlier records for this same pass.
        rows = db.select_all("coordination_tasks", params={
            "task_type": "eq." + TASK_TYPE,
            "payload": "like.*%s*" % fingerprint,
            "select": "payload",
        })
    except Exception as exc:  # noqa: BLE001 - fail-soft, see docstring
        print("dedupe lookup failed (%s); continuing without it" % exc,
              file=sys.stderr)
        return set()
    seen = set()
    for row in rows or []:
        raw = row.get("payload")
        try:
            data = json.loads(raw) if isinstance(raw, str) else (raw or {})
        except (TypeError, ValueError):
            continue
        if data.get("audit_fingerprint") == fingerprint:
            seen.add(data.get("source", ""))
    return seen


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger", required=True)
    ap.add_argument("--task-slug", required=True)
    ap.add_argument("--project", default="beethoven")
    ap.add_argument("--branch", default="")
    ap.add_argument("--commit", default="")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    with open(args.ledger) as fh:
        ledger = json.load(fh)
    items = ledger.get("items", [])
    fingerprint = ledger.get("audit_fingerprint", "")
    if not fingerprint:
        print("ledger has no audit_fingerprint; refusing to publish untraceable "
              "records", file=sys.stderr)
        return 2

    unknown = [i for i in items
               if i.get("classification", "UNKNOWN") == "UNKNOWN"]
    if unknown:
        print("%d UNKNOWN item(s); completion requires zero" % len(unknown),
              file=sys.stderr)

    if args.dry_run:
        print(json.dumps({
            "ledger": args.ledger, "items": len(items),
            "unknown": len(unknown), "fingerprint": fingerprint,
            "sample": build_payload(items[0], ledger, args) if items else {},
        }, indent=1))
        return 0

    import db  # noqa: E402 - deferred so --dry-run needs no credentials

    seen = already_published(fingerprint, db)
    written = skipped = failed = 0
    for item in items[:MAX_ROWS]:
        payload = build_payload(item, ledger, args)
        if payload["source"] in seen:
            skipped += 1
            continue
        try:
            db.insert("coordination_tasks", {
                "task_type": TASK_TYPE,
                "payload": json.dumps(payload, ensure_ascii=False),
                "status": status_for(payload["classification"]),
            })
            written += 1
        except Exception as exc:  # noqa: BLE001 - one bad row must not lose the rest
            failed += 1
            print("insert failed for %s: %s" % (payload["source"], exc),
                  file=sys.stderr)

    print(json.dumps({
        "fingerprint": fingerprint, "total": len(items),
        "written": written, "skipped_already_published": skipped,
        "failed": failed, "unknown": len(unknown),
    }, indent=1))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
