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
p = ar.repair_patch(task(attempt=1, remediation_count=ar.BLIND_REPAIR_CEILING), "",
                    category="missing-branch")
check("blind ceiling parks a task with no evidence sooner than the global ceiling",
      p["state"] == "QUARANTINED" and ar.BLIND_REPAIR_CEILING < ar.GLOBAL_REPAIR_CEILING)

p = ar.repair_patch(task(attempt=1, remediation_count=ar.BLIND_REPAIR_CEILING,
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
p = ar.repair_patch(task(attempt=1, remediation_count=1), "", category="rework")
check("a blind repair instructs the agent to capture diagnostics first",
      "do NOT guess" in p["prompt"] and "read the real" in p["prompt"])

# 6. is_terminal() is what call sites branch on; it must not be fooled by a normal note.
check("is_terminal is false for an ordinary repair patch",
      not ar.is_terminal({"note": "agentic-repair:rework"}))
check("is_terminal is true for a parked patch",
      ar.is_terminal({"note": ar.TERMINAL_NOTE_PREFIX + " rework after 8 repairs"}))

# 7. A task that has never run has not failed — repairing it is meaningless, and the repair
#    directive it would get ("continue the same implementation, inspect the existing branch")
#    describes work that does not exist. 69% of live repairs were of this kind.
p = ar.repair_patch(task(attempt=0, remediation_count=2), "", category="missing-branch")
check("a never-attempted task is plainly requeued, not 'repaired'",
      p["state"] == "QUEUED" and p["note"] == ar.NEVER_RAN_NOTE and ar.MARKER not in p["prompt"])
check("a plain requeue does not advance the repair count",
      "remediation_count" not in p)

p = ar.repair_patch(task(attempt=3, remediation_count=2), "", category="missing-branch")
check("a task that HAS run still gets a real repair",
      ar.MARKER in p["prompt"] and p["remediation_count"] == 3)

# 8. Repair directives must not stack. in_session_prompt() appends to the prompt it is given,
#    which is the previous repair's output, so prompts accumulated contradictory directives.
p1 = ar.repair_patch(task(attempt=1, remediation_count=1, log_tail="TS2345 type error"),
                     "build failed", category="buildfail")
p2 = ar.repair_patch(task(attempt=2, remediation_count=2, prompt=p1["prompt"],
                          log_tail="TS2345 type error"),
                     "build failed", category="buildfail")
check("a repaired prompt carries exactly one repair directive, not one per repair",
      p2["prompt"].count(ar.MARKER) == 1)
check("repairing preserves the original task text",
      p2["prompt"].startswith("do the thing"))

# 9. A caller that did not select `prompt` must not have the task's specification overwritten
#    with the "Complete the task '<slug>'." stub. periodic.run_unstick did exactly this.
narrow = {"id": "t1", "slug": "qafix-tomorrow-abc123", "note": "blocked: urlopen timeout",
          "remediation_count": 1}
p = ar.repair_patch(narrow, "urlopen timeout", category="transient")
check("a narrow row is repaired without clobbering the unselected prompt",
      "prompt" not in p and p["state"] == "QUEUED")

# 10. A missing `attempt` column must not be read as "never ran".
p = ar.repair_patch({"id": "t1", "slug": "s", "prompt": "real spec", "note": "",
                     "log_tail": "", "remediation_count": 1}, "", category="rework")
check("an unselected attempt column is not mistaken for a never-run task",
      p["note"] != ar.NEVER_RAN_NOTE)

print()
if FAILURES:
    print("%d invariant(s) broken:" % len(FAILURES))
    for f in FAILURES:
        print("  - " + f)
    sys.exit(1)
print("all repair-termination invariants hold")
