#!/usr/bin/env python3
"""Compact a recovery ledger and render a human-readable markdown report.

The raw ledger produced by tools/reconcile_rescue_refs.py embeds the full
changed-file list for every rescue ref, which can run to several megabytes.
That is useful locally but should not be committed verbatim. This script caps
the per-item file list, keeps every item and its classification, and writes a
markdown summary alongside.
"""

from __future__ import annotations

import argparse
import json
import os

MAX_FILES = 15
ORDER = [
    "RECOVERABLE_VALUE",
    "CONFLICTED_NEEDS_FOCUSED_TASK",
    "ACTIVE_IN_ANOTHER_TASK",
    "SUPERSEDED_BY_NEWER",
    "ALREADY_PRESENT",
    "UNKNOWN",
]


def compact(ledger: dict) -> dict:
    for item in ledger.get("items", []):
        files = item.get("files") or []
        item["file_count"] = len(files)
        if len(files) > MAX_FILES:
            item["files"] = files[:MAX_FILES]
            item["files_truncated"] = True
    return ledger


def render(ledger: dict, project: str) -> str:
    counts = ledger.get("counts", {})
    total = ledger.get("total", 0)
    lines = [
        "# Recovery ledger — %s" % project,
        "",
        "- audit fingerprint: `%s`" % ledger.get("audit_fingerprint", ""),
        "- base: `%s`" % ledger.get("base", ""),
        "- evidence items classified: **%d**" % total,
        "- UNKNOWN remaining: **%d**" % counts.get("UNKNOWN", 0),
        "",
        "Every rescue ref was treated as read-only. No ref, stash or worktree",
        "was deleted, reset, cleaned, popped or moved by this reconciliation.",
        "",
        "## Classification summary",
        "",
        "| classification | count |",
        "| --- | ---: |",
    ]
    for key in ORDER:
        if key in counts:
            lines.append("| %s | %d |" % (key, counts[key]))
    lines += ["", "## Items needing follow-up", ""]

    actionable = [
        i
        for i in ledger.get("items", [])
        if i.get("classification")
        in ("RECOVERABLE_VALUE", "CONFLICTED_NEEDS_FOCUSED_TASK")
    ]
    if not actionable:
        lines.append("_None — all evidence is already present or superseded._")
    else:
        lines += ["| ref | sha | class | files | disposition |", "| --- | --- | --- | ---: | --- |"]
        for i in actionable:
            lines.append(
                "| `%s` | `%s` | %s | %d | %s |"
                % (
                    i["ref"].replace("refs/", ""),
                    i["sha"][:10],
                    i["classification"],
                    i.get("file_count", len(i.get("files", []))),
                    i.get("disposition", "").replace("|", "/"),
                )
            )
    lines += [
        "",
        "## Disposition rules applied",
        "",
        "- `ALREADY_PRESENT` — reachable from base, patch-identical to base, or an",
        "  empty sweep commit. No action.",
        "- `SUPERSEDED_BY_NEWER` — every touched path was rewritten in base after the",
        "  ref was cut. Newest implementation wins; no action.",
        "- `ACTIVE_IN_ANOTHER_TASK` — the commit is contained in a live `agent/*`",
        "  branch. Left to that task; not duplicated here.",
        "- `RECOVERABLE_VALUE` — diff still applies. Recover through an isolated",
        "  worktree and the normal agent-branch + merge-train path.",
        "- `CONFLICTED_NEEDS_FOCUSED_TASK` — diff no longer applies. A focused",
        "  follow-up is queued instead of forcing an overwrite.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger", required=True)
    ap.add_argument("--project", required=True)
    ap.add_argument("--out-json", required=True)
    ap.add_argument("--out-md", required=True)
    args = ap.parse_args()

    with open(args.ledger) as fh:
        ledger = json.load(fh)

    ledger = compact(ledger)

    for path in (args.out_json, args.out_md):
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)

    with open(args.out_json, "w") as fh:
        json.dump(ledger, fh, indent=1, sort_keys=True)
    with open(args.out_md, "w") as fh:
        fh.write(render(ledger, args.project))

    print("compacted %d items -> %s" % (ledger.get("total", 0), args.out_json))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
