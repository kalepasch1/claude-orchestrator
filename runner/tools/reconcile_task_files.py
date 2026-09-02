#!/usr/bin/env python3
"""
Reconcile tasks/*.task.json against public.tasks.

Why this exists
---------------
The task files carried no status field at all. Whether an improvement had
actually shipped was unanswerable from the repo — you had to read the queue by
hand, and the queue has 24k rows. "Is the backlog done?" had no mechanical
answer, so it kept being answered optimistically.

It is worth knowing what the first full run found, because it is the reason the
optimistic answer was wrong: of 21 task files, none were DEPLOYED_AND_VERIFIED,
two were still QUEUED, four were QUARANTINED, six SUPERSEDED, and three had no
row in the queue at all. Two slugs matched more than one row.

What it does
------------
Reads every tasks/*.task.json, looks its slug up in public.tasks, and writes the
answer back into the file:

    "reconciliation": {
      "db_state":      "MERGED",              # or MISSING / AMBIGUOUS
      "status":        "shipped_unverified",  # the rollup, see STATUS_BY_STATE
      "completed_at":  "2026-08-12T21:16:02Z",
      "reconciled_at": "...",
      "duplicate_rows": 2                     # only when > 1
    }

Exit codes: 0 clean, 1 if any file is MISSING or AMBIGUOUS. It is meant to be
run in CI, so a task file that drifts away from its queue row fails the build
instead of sitting there looking finished.

    python3 runner/tools/reconcile_task_files.py            # write + report
    python3 runner/tools/reconcile_task_files.py --check    # report only
"""
from __future__ import annotations

import argparse
import datetime as _dt
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import db  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TASK_GLOB = os.path.join(REPO, "tasks", "*.task.json")

# The queue's own state enum, rolled up into the only three answers a human
# actually wants. The distinction that matters is the middle one: MERGED means
# the code landed, NOT that anyone confirmed it works in production. Treating
# those as the same thing is what produced 8,078 PHANTOM_UNVERIFIED rows.
STATUS_BY_STATE = {
    "DEPLOYED_AND_VERIFIED": "verified",
    "DONE":                  "verified",
    "MERGED":                "shipped_unverified",
    "PHANTOM_UNVERIFIED":    "shipped_unverified",
    "CLOSED":                "closed",
    "SUPERSEDED":            "closed",
    "QUEUED":                "open",
    "DECOMPOSED":            "open",
    "QUARANTINED":           "blocked",
}

TERMINAL_OK = {"verified"}


def _iso(value) -> str | None:
    if not value:
        return None
    return str(value).replace(" ", "T").split("+")[0] + "Z"


def lookup(slug: str) -> tuple[str, list[dict]]:
    """Return (db_state, rows). db_state is MISSING or AMBIGUOUS when unusable."""
    try:
        rows = db.select("tasks", {
            "select": "slug,state,updated_at,note",
            "slug": f"eq.{slug}",
            "order": "updated_at.desc",
        }) or []
    except Exception as exc:  # pragma: no cover - network shape varies
        print(f"  ! queue lookup failed for {slug}: {exc}", file=sys.stderr)
        return "LOOKUP_FAILED", []

    if not rows:
        return "MISSING", []
    states = {r.get("state") for r in rows}
    if len(rows) > 1 and len(states) > 1:
        # Same slug, different states. Nobody can say which one is the truth,
        # and picking the newest would paper over a real duplicate.
        return "AMBIGUOUS", rows
    return rows[0].get("state") or "UNKNOWN", rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="report only; do not write reconciliation back into the files")
    args = ap.parse_args()

    files = sorted(glob.glob(TASK_GLOB))
    if not files:
        print(f"no task files matched {TASK_GLOB}", file=sys.stderr)
        return 1

    now = _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()
    counts: dict[str, int] = {}
    problems: list[str] = []

    print(f"{'task file':<52} {'queue state':<22} status")
    print("-" * 92)

    for path in files:
        name = os.path.basename(path)
        try:
            doc = json.load(open(path))
        except Exception as exc:
            problems.append(f"{name}: unreadable ({exc})")
            continue

        slug = doc.get("slug") or name.replace(".task.json", "")
        state, rows = lookup(slug)
        status = STATUS_BY_STATE.get(state, "unknown")
        counts[status] = counts.get(status, 0) + 1

        if state in ("MISSING", "AMBIGUOUS", "LOOKUP_FAILED"):
            problems.append(f"{name}: {state} (slug '{slug}')")

        completed = None
        if status in TERMINAL_OK and rows:
            completed = _iso(rows[0].get("updated_at"))

        recon = {
            "db_state": state,
            "status": status,
            "completed_at": completed,
            "reconciled_at": now,
        }
        if len(rows) > 1:
            recon["duplicate_rows"] = len(rows)

        print(f"{name[:51]:<52} {state:<22} {status}")

        if not args.check:
            doc["reconciliation"] = recon
            with open(path, "w") as fh:
                json.dump(doc, fh, indent=2)
                fh.write("\n")

    print("-" * 92)
    print("rollup: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))

    if problems:
        print("\nUnreconciled — a task file with no single queue row is a task file "
              "nobody can answer for:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
