#!/usr/bin/env python3
"""Insert the claimability preflight into every cowork-executor skill copy.

A zero-row claim means one of two opposite things — nothing left to do, or
everything left to do is blocked — and the skills mapped both to "queue empty,
stop". This inserts the wording that forces an executor to tell them apart. See
runner/cowork_skill_invariants.py for why, and QUEUE-DEADLOCK-2026-08-25.md for
the six weeks of clean-looking runs that motivated it.

Idempotent: re-running finds the marker and leaves the file alone. Usage:

    python3 tools/patch_skill_claimability_preflight.py [--check]
"""

import os
import re
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL_DIR = os.path.join(REPO_ROOT, "cowork-skills")

MARKER = "### Claimability preflight"

BLOCK = """
### Claimability preflight — a zero-row claim is NOT proof of an empty queue

Before treating zero claimed rows as "queue empty", count them separately:

```sql
SELECT count(*) FILTER (WHERE state='QUEUED') AS queued,
       count(*) FILTER (WHERE state='QUEUED' AND (deps IS NULL
             OR array_length(deps,1) IS NULL)) AS trivially_claimable
FROM tasks;
```

- `queued = 0` → the queue really is empty. Heartbeat, write `<run-summary>`, stop.
- `queued > 0` and nothing claimable → **STALL, not an empty queue.** This is never
  a reason to stop and must never be reported as a clean run. Report the blocker
  states and stop with the stall named.

Do NOT "fix" a stall by widening the dependency gate. A dep sitting in DECOMPOSED,
QUARANTINED, SUPERSEDED or CLOSED is terminal, and waving it through launches work
whose stated prerequisite never happened — the most expensive failure mode this
fleet has (see CLAUDE.md). Diagnose and report; unblocking is an operator decision.

Why this exists: from 2026-07-15 to 2026-08-27 sixteen executors reported clean
runs against a queue that never moved, because a deadlocked queue and a finished
one produced the identical zero-row signal.
"""


def patch_text(text):
    """Return (new_text, changed). Pure — no I/O."""
    if MARKER in text:
        return text, False

    # Layout A: an explicit "If 0 rows ..." exit line. Put the preflight
    # immediately before it, so it is read first.
    m = re.search(r"^If 0 rows.*$", text, flags=re.MULTILINE)
    if m:
        return text[: m.start()] + BLOCK.strip() + "\n\n" + text[m.start() :], True

    # Layout B: no such line. Append to the end of the claim step, i.e. just
    # before the next top-level section.
    m = re.search(r"^## Step 2\b", text, flags=re.MULTILINE)
    if m:
        return text[: m.start()] + BLOCK.strip() + "\n\n---\n\n" + text[m.start() :], True

    return text.rstrip() + "\n\n" + BLOCK.strip() + "\n", True


def main(argv):
    check_only = "--check" in argv
    if not os.path.isdir(SKILL_DIR):
        print("no cowork-skills/ directory at %s" % SKILL_DIR)
        return 1
    changed = []
    for name in sorted(os.listdir(SKILL_DIR)):
        if not name.endswith(".SKILL.md"):
            continue
        path = os.path.join(SKILL_DIR, name)
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
        new_text, did = patch_text(text)
        if not did:
            continue
        changed.append(name)
        if not check_only:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(new_text)
    verb = "would patch" if check_only else "patched"
    print("%s %d skill file(s)%s" % (verb, len(changed),
                                     (": " + ", ".join(changed)) if changed else ""))
    return 1 if (check_only and changed) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
