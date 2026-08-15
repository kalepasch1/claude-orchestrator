#!/usr/bin/env python3
"""Triage tasks whose specification was destroyed by the narrow-select repair bug.

periodic.run_unstick() selected a column set without `prompt`, so agentic_repair's fallback —
"Complete the task '<slug>'." — was written back over the real specification. The content is not
recoverable from the task row. Running such a task wastes a lane and produces nothing usable, and
its no-diff outcome feeds the repair loop, so these are parked with an explicit note instead.

    python3 runner/stub_prompt_triage.py            # report only
    python3 runner/stub_prompt_triage.py --apply    # park them
"""
import os
import re
import sys
import collections

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import agentic_repair as ar

APPLY = "--apply" in sys.argv
LIVE = "in.(QUEUED,RETRY,BLOCKED,CONFLICT,TESTFAIL,SHELVED)"
_STUB = re.compile(r"^Complete the task '[^']+'\.\s*$")
NOTE = ("spec-lost: the task prompt was overwritten with the \"Complete the task '<slug>'.\" stub "
        "by the narrow-select repair bug (fixed 2026-08-03). The original specification is not "
        "recoverable from this row. Regenerate the spec from its source (batch//parent task) and "
        "requeue, or close it — running it as-is cannot produce the intended change.")


def main():
    rows, page = [], 0
    while True:
        chunk = db.select("tasks", {"select": "id,slug,prompt,state,kind", "state": LIVE,
                                    "order": "id.asc", "limit": "1000",
                                    "offset": str(page * 1000)}) or []
        rows.extend(chunk)
        if len(chunk) < 1000:
            break
        page += 1
        if page > 20:
            break

    stubs = [r for r in rows if _STUB.match(ar.original_prompt(r))]
    print("live tasks: %d   with a destroyed spec: %d" % (len(rows), len(stubs)))

    fams = collections.Counter(str(r.get("slug") or "").split("-")[0] for r in stubs)
    print("\nby family:")
    for k, n in fams.most_common(12):
        print("  %4d  %s" % (n, k))

    if not APPLY:
        print("\nreport only — rerun with --apply to park them")
        return 0

    parked = failed = 0
    for r in stubs:
        try:
            db.update("tasks", {"id": r["id"]}, {"state": "QUARANTINED", "note": NOTE,
                                                 "updated_at": "now()"})
            parked += 1
        except Exception as e:
            failed += 1
            print("  failed %s: %s" % ((r.get("slug") or "")[:40], str(e)[:80]))
    print("\nparked %d tasks with unrecoverable specs (%d failed)" % (parked, failed))
    return 0


if __name__ == "__main__":
    sys.exit(main())
