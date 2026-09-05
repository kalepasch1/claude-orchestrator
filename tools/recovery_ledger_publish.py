#!/usr/bin/env python3
"""Publish a recovery ledger to coordination_tasks, one record per evidence item.

The reconcilers (tools/reconcile_rescue_refs.py, tools/reconcile_local_branches.py,
tools/reconcile_agent_branches.py, tools/reconcile_worktree_evidence.py) emit a
ledger JSON. The recovery contract additionally requires a durable
`coordination_tasks` record per evidence item carrying source, classification,
disposition and the resulting task/branch provenance.

Doing that by hand means pasting the whole ledger into a SQL statement, which is
both error-prone and wasteful. This publisher reads the ledger locally, connects
with the credentials already present in runner/.env, and writes the records
itself. Credentials are read from disk and never printed.

Idempotent: an item is keyed by (audit_fingerprint, source). Re-running after a
crash tops up only the missing records, so a partially published ledger is safe
to resume.

Usage:
    python3 tools/recovery_ledger_publish.py \
        --ledger .orch/recovery-ledger-<short>-local-branches.json \
        --task-slug chatgpt-local-reconcile-beethoven-<short> \
        --branch agent/chatgpt-local-reconcile-beethoven-<short>
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

TASK_TYPE = "recovery_ledger"
ENV_CANDIDATES = ("runner/.env", ".env")


def load_env(repo_root: str) -> "tuple[str, str]":
    """Read SUPABASE_URL / service key from the runner env files.

    Values are returned to the caller only; nothing is echoed to stdout.
    """
    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    for rel in ENV_CANDIDATES:
        path = os.path.join(repo_root, rel)
        if not os.path.isfile(path):
            continue
        for line in open(path, errors="replace"):
            m = re.match(r"\s*(?:export\s+)?([A-Z0-9_]+)\s*=\s*(.*)\s*$", line)
            if not m:
                continue
            name, val = m.group(1), m.group(2).strip().strip("'\"")
            if not val:
                continue
            if name in ("SUPABASE_URL", "ORCH_SUPABASE_URL") and not url:
                url = val
            elif name in (
                "SUPABASE_SERVICE_KEY",
                "ORCHESTRATOR_SUPABASE_SERVICE_KEY",
                "ORCH_SUPABASE_KEY",
                "SUPABASE_SERVICE_ROLE_KEY",
            ) and not key:
                key = val
        if url and key:
            break
    if not url or not key:
        raise SystemExit(
            "no Supabase credentials found in runner/.env or the environment"
        )
    return url, key


def rest(url: str, key: str, method: str, path: str, body=None):
    """Minimal PostgREST call over the stdlib.

    supabase-py is not a dependency of this repo, and importing it opportunistically
    is unsafe here: a stray ``supabase/`` directory in the repo root resolves as an
    empty namespace package, so ``import supabase`` succeeds and then fails at use.
    urllib is always present and the two calls we need are trivial.
    """
    import urllib.error
    import urllib.request

    headers = {
        "apikey": key,
        "Authorization": "Bearer " + key,
        "Content-Type": "application/json",
    }
    if method == "POST":
        # Only on writes: on a GET this would suppress the rows we need to read.
        headers["Prefer"] = "return=minimal"
    req = urllib.request.Request(
        url.rstrip("/") + "/rest/v1/" + path,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers=headers,
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode(errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:400]
        raise SystemExit(f"PostgREST {method} {path.split('?')[0]} -> "
                         f"{exc.code}: {detail}")
    if not raw.strip():
        return []
    try:
        return json.loads(raw)
    except Exception:
        return []


def fingerprint_of(ledger: dict) -> str:
    """The audit fingerprint, whichever key the emitting reconciler used.

    reconcile_all_evidence.py writes `audit_fingerprint`; the single-kind
    reconcilers (reconcile_local_branch_tips.py and friends) write
    `fingerprint`. Accepting both is what keeps a ledger from being silently
    unpublishable just because it came from the narrower tool — the failure
    mode that leaves a fully classified ledger with zero durable records.
    """
    return ledger.get("audit_fingerprint") or ledger.get("fingerprint") or ""


def evidence_kind_of(ledger: dict) -> str:
    """Evidence kind, tolerating the single-kind reconcilers' `kind` key."""
    return ledger.get("evidence_kind") or ledger.get("kind") or "unspecified"


def record_for(item: dict, ledger: dict, task_slug: str, branch: str,
               commit: str) -> dict:
    files = item.get("files") or []
    return {
        "audit_fingerprint": fingerprint_of(ledger),
        "evidence_kind": evidence_kind_of(ledger),
        "base": ledger.get("base", ""),
        "source": item.get("ref") or item.get("source") or item.get("path", ""),
        "sha": item.get("sha", ""),
        "classification": item.get("classification", "UNKNOWN"),
        "disposition": item.get("disposition", ""),
        "evidence": item.get("evidence", ""),
        "file_count": item.get("file_count", len(files)),
        "task_slug": task_slug,
        "branch": branch,
        "commit": commit,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger", required=True)
    ap.add_argument("--task-slug", required=True)
    ap.add_argument("--branch", required=True)
    ap.add_argument("--commit", default="")
    ap.add_argument("--repo-root", default=".")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    with open(args.ledger) as fh:
        ledger = json.load(fh)
    items = ledger.get("items", [])
    fingerprint = fingerprint_of(ledger)
    if not fingerprint:
        raise SystemExit(
            "ledger has no audit_fingerprint (nor fingerprint); refusing to publish")

    records = [
        record_for(i, ledger, args.task_slug, args.branch, args.commit)
        for i in items
    ]

    if args.dry_run:
        print(json.dumps({"would_publish": len(records),
                          "fingerprint": fingerprint}, indent=2))
        return 0

    url, key = load_env(args.repo_root)

    # Idempotency: skip sources already recorded under this fingerprint.
    existing: set[str] = set()
    for row in rest(url, key, "GET",
                    "coordination_tasks?select=payload&task_type=eq." + TASK_TYPE
                    + "&payload=like.*" + fingerprint + "*"):
        payload = row.get("payload")
        if not payload:
            continue
        try:
            obj = json.loads(payload)
        except Exception:
            continue
        if obj.get("audit_fingerprint") == fingerprint:
            existing.add(obj.get("source", ""))

    pending = [r for r in records if r["source"] not in existing]
    inserted = 0
    for start in range(0, len(pending), 100):
        chunk = pending[start : start + 100]
        rest(url, key, "POST", "coordination_tasks", [
            {
                "task_type": TASK_TYPE,
                "payload": json.dumps(r, sort_keys=True),
                "status": "recorded",
            }
            for r in chunk
        ])
        inserted += len(chunk)

    print(
        json.dumps(
            {
                "fingerprint": fingerprint,
                "items": len(records),
                "already_recorded": len(records) - len(pending),
                "inserted": inserted,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
