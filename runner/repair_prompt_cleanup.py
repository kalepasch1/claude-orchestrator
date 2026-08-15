#!/usr/bin/env python3
"""One-time cleanup of prompts damaged by the stacked-repair-directive bug.

Live tasks accumulated one AGENTIC-REPAIR DIRECTIVE block per repair — up to 28 — each
contradicting the last, with the real specification buried at the top. agentic_repair now strips
prior directives before appending, but rows already in the queue still carry the stack. This
rewrites them to their original text so the next run sees a clean spec.

Also reports (but cannot recover) prompts destroyed by the narrow-select bug, where the whole
specification was replaced with "Complete the task '<slug>'." — those need regeneration.

    python3 runner/repair_prompt_cleanup.py            # report only
    python3 runner/repair_prompt_cleanup.py --apply    # write
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import agentic_repair as ar

APPLY = "--apply" in sys.argv
LIVE = "in.(QUEUED,RETRY,BLOCKED,CONFLICT,TESTFAIL,SHELVED)"
_STUB = re.compile(r"^Complete the task '[^']+'\.\s*$")


def main():
    rows = []
    page = 0
    while True:
        chunk = db.select("tasks", {"select": "id,slug,prompt", "state": LIVE,
                                    "order": "id.asc", "limit": "1000",
                                    "offset": str(page * 1000)}) or []
        rows.extend(chunk)
        if len(chunk) < 1000:
            break
        page += 1
        if page > 20:
            break
    print("live tasks scanned: %d" % len(rows))

    stacked, stub, fixed, failed = [], [], 0, 0
    for r in rows:
        prompt = str(r.get("prompt") or "")
        n = prompt.count(ar.MARKER)
        original = ar.original_prompt(r)
        if _STUB.match(original):
            stub.append(r)
        if n >= 1 and original and not _STUB.match(original):
            stacked.append((r, n, original))

    print("prompts carrying at least one stale repair directive: %d" % len(stacked))
    if stacked:
        worst = sorted(stacked, key=lambda x: -x[1])[:8]
        print("  worst offenders (directive blocks stacked, chars reclaimed):")
        for r, n, original in worst:
            print("    %2d blocks  %6d -> %5d chars  %s"
                  % (n, len(r.get("prompt") or ""), len(original), (r.get("slug") or "")[:46]))
        reclaimed = sum(len(r.get("prompt") or "") - len(o) for r, _, o in stacked)
        print("  total prompt text to reclaim: %d chars" % reclaimed)

    print("prompts destroyed by the narrow-select stub (unrecoverable, need regeneration): %d"
          % len(stub))
    for r in stub[:8]:
        print("    %s" % (r.get("slug") or "")[:70])

    if not APPLY:
        print("\nreport only — rerun with --apply to write")
        return 0

    for r, n, original in stacked:
        try:
            db.update("tasks", {"id": r["id"]}, {"prompt": original})
            fixed += 1
        except Exception as e:
            failed += 1
            print("  failed %s: %s" % ((r.get("slug") or "")[:40], str(e)[:80]))
    print("\nrewrote %d prompts to their original text (%d failed)" % (fixed, failed))
    return 0


if __name__ == "__main__":
    sys.exit(main())
