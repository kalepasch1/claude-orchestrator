#!/usr/bin/env python3
"""Invariants for repair termination.

These encode the 2026-08-03 failure: every repair path funnels through
agentic_repair.repair_patch(), no path bounded the TOTAL repair count, and 81% of repairs ran
with no failure evidence at all. Live tasks reached remediation_count 28 with attempt=0 —
repaired two dozen times without ever running once.

Run standalone; exits non-zero on the first broken invariant. fleet_healthcheck.py runs it.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("ORCH_AGENTIC_REPAIR_DEFAULT_CODER", "test-coder")
import agentic_repair as ar

FAILURES = []


def check(name, cond):
    print(("  ok   " if cond else "  FAIL ") + name)
    if not cond:
        FAILURES.append(name)


def task(**kw):
    base = {"id": "t1", "slug": "qafix-tomorrow-abc123", "prompt": "do the thing",
            "note": "", "log_tail": "", "remediation_count": 0, "attempt": 0}
    base.update(kw)
    return base


print("repair termination invariants")

# 1. The ordinary case still re-queues.
p = ar.repair_patch(task(remediation_count=1, log_tail="npm run build exited 1: TS2345"),
                    "build failed", category="buildfail")
check("a repair below both ceilings re-queues the task",
      p["state"] == "QUEUED" and p["remediation_count"] == 2 and not ar.is_terminal(p))

# 2. The global ceiling binds no matter how good the evidence is.
p = ar.repair_patch(task(remediation_count=ar.GLOBAL_REPAIR_CEILING,
                         log_tail="npm run build exited 1: TS2345 argument type mismatch"),
                    "build failed", category="buildfail")
check("global ceiling parks the task instead of re-queueing",
      p["state"] == "QUARANTINED" and ar.is_terminal(p))
check("a parked task does not have its repair count advanced",
      p["remediation_count"] == ar.GLOBAL_REPAIR_CEILING)

# 3. Blind repairs get a lower ceiling — guessing repeatedly cannot converge.
p = ar.repair_patch(task(remediation_count=ar.BLIND_REPAIR_CEILING), "", category="missing-branch")
check("blind ceiling parks a task with no evidence sooner than the global ceiling",
      p["state"] == "QUARANTINED" and ar.BLIND_REPAIR_CEILING < ar.GLOBAL_REPAIR_CEILING)

p = ar.repair_patch(task(remediation_count=ar.BLIND_REPAIR_CEILING,
                         log_tail="FileNotFoundError: [Errno 2] No such file or directory: 'claude'"),
                    "", category="missing-branch")
check("the same count with real evidence still re-queues",
      p["state"] == "QUEUED")

# 4. A repair's own bookkeeping is not evidence. This is the trap the whole loop lived in:
#    the note left by the last repair is "agentic-repair:missing-branch", which looks like text
#    about a missing branch but says nothing about why anything failed.
check("a prior repair's own note is not counted as evidence",
      not ar.has_evidence(task(note="agentic-repair:missing-branch")))
check("the task's own slug is not counted as evidence",
      not ar.has_evidence(task(note="qafix-tomorrow-abc123 qafix-tomorrow-abc123")))
check("a real traceback IS counted as evidence",
      ar.has_evidence(task(log_tail="NameError: name 'emit_task_log' is not defined")))

# 5. A blind repair must tell the agent to go find the failure rather than guess at a fix.
p = ar.repair_patch(task(remediation_count=1), "", category="rework")
check("a blind repair instructs the agent to capture diagnostics first",
      "do NOT guess" in p["prompt"] and "read the real" in p["prompt"])

# 6. is_terminal() is what call sites branch on; it must not be fooled by a normal note.
check("is_terminal is false for an ordinary repair patch",
      not ar.is_terminal({"note": "agentic-repair:rework"}))
check("is_terminal is true for a parked patch",
      ar.is_terminal({"note": ar.TERMINAL_NOTE_PREFIX + " rework after 8 repairs"}))

print()
if FAILURES:
    print("%d invariant(s) broken:" % len(FAILURES))
    for f in FAILURES:
        print("  - " + f)
    sys.exit(1)
print("all repair-termination invariants hold")
