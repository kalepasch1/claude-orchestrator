#!/usr/bin/env python3
"""Generate a recovery ledger: one record per evidence item, deterministically.

WHERE THIS SITS
---------------
    reconcilers  ->  [THIS]  ->  tools/recovery_ledger_publish.py  ->  coordination_tasks

`recovery_ledger_publish.py` already writes one `coordination_tasks` row per ledger
item, and the reconcilers already classify evidence. What sat between them was done by
hand: turning classified evidence into ledger records carrying the audit fingerprint,
a disposition, and provenance. Done by hand it drifts — records go missing, dispositions
get worded differently each run, and the commonest failure is the worst one: an item
with no recoverable diff gets a *plausible-looking* commit attached so the row appears
complete.

So the rule this module enforces is: **provenance is recorded, never invented.**
An item that cannot point at a real branch/task/commit gets disposition
`QUEUED_FOCUSED_FOLLOW_UP` and an explicit planned follow-up task name, and its
commit/branch fields stay empty. A reader can then tell "recovered" from "still owed"
without reading a summary that claims either.

DETERMINISM
-----------
No clock, no RNG, no dict-iteration order in the output. The same evidence and the same
fingerprint produce byte-identical JSON, so two runs can be diffed and a re-run after a
crash is a no-op rather than a second set of records. Follow-up task names are derived
from the source ref, not from a counter, for the same reason.

Public API
----------
    build_record(item, fingerprint, **ctx)   -> dict
    build_ledger(items, fingerprint, **ctx)  -> dict
    write_ledger(ledger, path)               -> path

CLI
---
    python3 tools/recovery_ledger_generate.py \
        --evidence evidence.json \
        --fingerprint 939f3db3... \
        --out .orch/recovery-ledger-939f3db3.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

# The five labels the reconcilers emit. Kept in sync with
# runner/local_evidence_reconciler.CLASSIFICATIONS; anything else becomes UNKNOWN, which
# the provenance gate treats as a failure rather than quietly accepting.
CLASSIFICATIONS = (
    "ALREADY_PRESENT",
    "SUPERSEDED_BY_NEWER",
    "ACTIVE_IN_ANOTHER_TASK",
    "RECOVERABLE_VALUE",
    "CONFLICTED_NEEDS_FOCUSED_TASK",
)
UNKNOWN = "UNKNOWN"

# Classifications that still owe work. Everything else is settled: the work shipped, is
# owned elsewhere, or lost to a newer implementation.
NEEDS_FOLLOW_UP = ("RECOVERABLE_VALUE", "CONFLICTED_NEEDS_FOCUSED_TASK")

DISPOSITION_FOLLOW_UP = "QUEUED_FOCUSED_FOLLOW_UP"
DISPOSITION_RECOVERED = "RECOVERED_IN_BRANCH"
DISPOSITION_SETTLED = "NO_ACTION_REQUIRED"
DISPOSITION_UNKNOWN = "UNCLASSIFIED_NEEDS_TRIAGE"

FINGERPRINT_RE = re.compile(r"^[0-9a-f]{64}$", re.I)
_SLUG_UNSAFE = re.compile(r"[^a-z0-9-]+")

# Prefixes stripped when deriving a follow-up slug, so refs/heads/agent/foo and
# agent/foo produce the same name.
_REF_PREFIXES = ("refs/heads/", "refs/remotes/origin/", "refs/orch-rescue/",
                 "refs/recovery/", "refs/quarantine/", "refs/")


def slugify(value: str, prefix: str = "", limit: int = 90) -> str:
    base = _SLUG_UNSAFE.sub("-", (value or "").strip().lower()).strip("-")
    base = re.sub(r"-{2,}", "-", base)
    slug = f"{prefix}{base}" if prefix else base
    return slug[:limit].strip("-") or f"{prefix}unnamed"


def source_of(item: dict) -> str:
    """The evidence item's source, verbatim, from whichever field carries it."""
    for key in ("ref", "source", "name", "path", "branch"):
        value = (item or {}).get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _short_source(source: str) -> str:
    for prefix in _REF_PREFIXES:
        if source.startswith(prefix):
            return source[len(prefix):]
    return source


def followup_task_name(source: str, classification: str) -> str:
    """A stable, explicit follow-up task name. Derived from the ref, never a counter.

    Two runs over the same evidence must propose the SAME task name, or re-running a
    reconciliation fans out duplicate tasks instead of converging on the existing one.
    """
    kind = "conflict" if classification == "CONFLICTED_NEEDS_FOCUSED_TASK" else "recover"
    return slugify(_short_source(source), prefix=f"reconcile-{kind}-")


def normalize_classification(value) -> str:
    label = str(value or "").strip().upper()
    return label if label in CLASSIFICATIONS else UNKNOWN


def build_record(item: dict, fingerprint: str, *, evidence_kind: str = "unspecified",
                 base: str = "", task_slug: str = "", branch: str = "") -> dict:
    """One ledger record. Pure: no clock, no RNG, no I/O.

    `task_slug` / `branch` are the provenance of an ACTUAL recovery. They are only
    attached to items that carry a real commit; otherwise the record says the work is
    still owed rather than implying it landed somewhere.
    """
    item = item or {}
    source = source_of(item)
    classification = normalize_classification(item.get("classification"))

    # A commit is only ever copied from the evidence. Never synthesized, never inferred
    # from the branch — an invented sha is indistinguishable from a real one to every
    # later reader, which is exactly how unrecovered work gets marked recovered.
    commit = str(item.get("commit") or item.get("sha") or "").strip()

    record = {
        "audit_fingerprint": fingerprint,
        "evidence_kind": evidence_kind,
        "base": base,
        "source": source,
        "sha": commit,
        "classification": classification,
        "evidence": str(item.get("evidence") or item.get("detail") or "").strip(),
        "file_count": int(item.get("file_count") or len(item.get("files") or [])),
        "task_slug": "",
        "branch": "",
        "commit": "",
        "planned_followup_task": "",
    }

    if classification == UNKNOWN:
        record["disposition"] = DISPOSITION_UNKNOWN
        record["planned_followup_task"] = slugify(
            _short_source(source), prefix="reconcile-triage-")
        return record

    if classification not in NEEDS_FOLLOW_UP:
        record["disposition"] = DISPOSITION_SETTLED
        return record

    if commit:
        record["disposition"] = DISPOSITION_RECOVERED
        record["task_slug"] = task_slug
        record["branch"] = branch
        record["commit"] = commit
        return record

    # Insufficient evidence for a real recovery diff. Say so, name the follow-up, and
    # leave commit/branch/task empty.
    record["disposition"] = DISPOSITION_FOLLOW_UP
    record["planned_followup_task"] = followup_task_name(source, classification)
    return record


def build_ledger(items, fingerprint: str, *, evidence_kind: str = "unspecified",
                 base: str = "", task_slug: str = "", branch: str = "") -> dict:
    """Exactly one record per evidence item, in input order."""
    if not FINGERPRINT_RE.match(str(fingerprint or "")):
        raise ValueError(
            f"audit fingerprint must be 64 hex chars, got {fingerprint!r}")

    records = [
        build_record(item, fingerprint, evidence_kind=evidence_kind, base=base,
                     task_slug=task_slug, branch=branch)
        for item in (items or [])
    ]

    counts = {}
    for record in records:
        counts[record["classification"]] = counts.get(record["classification"], 0) + 1

    return {
        "audit_fingerprint": fingerprint,
        "evidence_kind": evidence_kind,
        "base": base,
        "item_count": len(records),
        "counts": {k: counts[k] for k in sorted(counts)},
        "items": records,
    }


def write_ledger(ledger: dict, path: str) -> str:
    """Write one JSON file. Deterministic: sorted keys, fixed indent, trailing newline."""
    directory = os.path.dirname(os.path.abspath(path))
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(ledger, handle, indent=2, sort_keys=True, default=str)
        handle.write("\n")
    return path


def provenance_gate(ledger: dict) -> dict:
    """Every item is accounted for: no UNKNOWN, and nothing owed without a named plan."""
    items = (ledger or {}).get("items") or []
    unknown = [r["source"] for r in items if r["classification"] == UNKNOWN]
    unprovenanced = [
        r["source"] for r in items
        if r["classification"] in NEEDS_FOLLOW_UP
        and not (r.get("commit") or r.get("planned_followup_task"))
    ]
    return {
        "ok": not unknown and not unprovenanced,
        "unknown": unknown,
        "unprovenanced": unprovenanced,
        "total": len(items),
    }


def _load_items(path: str):
    raw = sys.stdin.read() if path == "-" else open(path, encoding="utf-8").read()
    data = json.loads(raw)
    if isinstance(data, dict):
        return data.get("items") or data.get("evidence") or data.get("records") or []
    return data


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Generate a recovery ledger from classified evidence.")
    ap.add_argument("--evidence", required=True,
                    help="JSON list of evidence items, or - for stdin")
    ap.add_argument("--fingerprint", required=True, help="64-hex audit fingerprint")
    ap.add_argument("--out", required=True, help="path to write the ledger JSON")
    ap.add_argument("--evidence-kind", default="unspecified")
    ap.add_argument("--base", default="")
    ap.add_argument("--task-slug", default="",
                    help="task that owns any ACTUAL recovery in this ledger")
    ap.add_argument("--branch", default="",
                    help="branch that carries any ACTUAL recovery in this ledger")
    args = ap.parse_args(argv)

    try:
        items = _load_items(args.evidence)
    except (OSError, ValueError) as exc:
        print(f"could not read evidence: {exc}", file=sys.stderr)
        return 2

    try:
        ledger = build_ledger(items, args.fingerprint,
                              evidence_kind=args.evidence_kind, base=args.base,
                              task_slug=args.task_slug, branch=args.branch)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    write_ledger(ledger, args.out)
    gate = provenance_gate(ledger)
    print(json.dumps({"out": args.out, "item_count": ledger["item_count"],
                      "counts": ledger["counts"], "gate": gate}, indent=2))
    return 0 if gate["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
