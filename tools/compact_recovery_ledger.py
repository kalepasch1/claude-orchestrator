#!/usr/bin/env python3
"""Shrink a recovery ledger for git without dropping a single evidence item.

Why this exists
---------------
A full-fleet reconciliation of this repo classifies ~966 evidence items whose
`files` arrays hold ~149,000 path strings between them — 7.6 MB of the 8.5 MB
ledger, and a 6.8 MB markdown render on top. Committing that per audit
fingerprint puts tens of megabytes of machine-generated text into a repo that
already carries 35 ledgers, and the file list is the one part of an item that is
trivially reproducible: `git show --name-only <sha>` regenerates it exactly.

What is NOT dropped
-------------------
Every item survives, with its ref, sha, classification, disposition and
evidence. That is the recovery contract: durable provenance for every item, and
`unknown == 0` verifiable from the committed artefact. Compaction only touches
the `files` array, replacing the tail with a count.

An item is therefore still fully auditable: the classification and the reason
for it are intact, and the exact file list is one git command away from the sha
recorded next to it. `filesTruncated` marks any item whose list was clipped so
nobody mistakes a sample for the whole, and `files_total` preserves the number
that the disposition text refers to ("all N touched files modified in base").

Usage
-----
    python3 tools/compact_recovery_ledger.py \\
        --in .orch/recovery-ledger-all.json \\
        --out docs/recovery-ledger/<short>.json [--max-files 12]

Read-only with respect to evidence: reads JSON, writes JSON. Exit 0 on success,
2 on unreadable or malformed input.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

DEFAULT_MAX_FILES = 12


def compact_item(item: dict, max_files: int) -> dict:
    """Return a copy of `item` with its `files` array clipped.

    `files_total` is added whenever a list is present — not only when it is
    clipped — so a reader never has to guess whether the absence of the field
    means "not clipped" or "field not written by this version".
    """
    out = dict(item)
    files = out.get("files")
    if not isinstance(files, list):
        return out
    out["files_total"] = len(files)
    if max_files >= 0 and len(files) > max_files:
        out["files"] = files[:max_files]
        out["filesTruncated"] = True
    else:
        out["filesTruncated"] = False
    return out


def compact_ledger(ledger: dict, max_files: int = DEFAULT_MAX_FILES) -> dict:
    """Compact every item. Counts and totals are recomputed, never copied.

    Recomputing rather than trusting the input's own `counts`/`unknown` means a
    compacted ledger cannot inherit a stale or wrong summary from the source: if
    the two ever disagreed, the committed artefact would be the one telling the
    truth about itself.
    """
    out = dict(ledger)
    items = ledger.get("items")
    if not isinstance(items, list):
        return out

    compacted = [compact_item(i, max_files) for i in items
                 if isinstance(i, dict)]
    out["items"] = compacted

    counts: dict = {}
    for it in compacted:
        key = it.get("classification") or "UNKNOWN"
        counts[key] = counts.get(key, 0) + 1
    out["counts"] = counts
    out["total"] = len(compacted)
    out["unknown"] = counts.get("UNKNOWN", 0)
    out["compacted"] = {
        "maxFilesPerItem": max_files,
        "itemsTruncated": sum(1 for i in compacted if i.get("filesTruncated")),
        "note": "file lists clipped; regenerate in full with "
                "`git show --pretty=format: --name-only <sha>`",
    }
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-files", type=int, default=DEFAULT_MAX_FILES,
                    help="paths kept per item; -1 keeps all (no compaction)")
    args = ap.parse_args()

    try:
        with open(args.src) as fh:
            ledger = json.load(fh)
    except (OSError, ValueError) as exc:
        print("cannot read ledger %s: %s" % (args.src, exc), file=sys.stderr)
        return 2
    if not isinstance(ledger, dict):
        print("ledger is not an object: %s" % args.src, file=sys.stderr)
        return 2

    out = compact_ledger(ledger, args.max_files)

    out_dir = os.path.dirname(args.out)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(args.out, "w") as fh:
        json.dump(out, fh, indent=2, sort_keys=True)

    before = os.path.getsize(args.src)
    after = os.path.getsize(args.out)
    print(json.dumps({
        "items": out.get("total"),
        "unknown": out.get("unknown"),
        "bytes_before": before,
        "bytes_after": after,
        "items_truncated": out["compacted"]["itemsTruncated"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
