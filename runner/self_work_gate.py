#!/usr/bin/env python3
"""
self_work_gate.py — one place that decides whether the orchestrator is allowed to
generate work for ITSELF, and whether synthetic (non-user-facing) task generators
may run at all.

WHY THIS EXISTS
---------------
A capacity audit found the fleet spending ~78.5% of its output on self-directed
work: 879 of 929 improvement_proposals targeted `beethoven` (the orchestrator's own
repo), all 13 proposals ever shipped were orchestrator features, and ZERO user-app
proposals had ever shipped. Synthetic canary / shadow / auto-continuation tasks
added a further constant drip of work that never reaches a user.

The machinery is not the problem — what it is POINTED AT is. So this module keeps
every generator intact and simply gates it. Every gate is a clearly-named env var,
each gate is reversible by flipping one variable, and every suppression is logged
loudly so a suppressed generator is never silently mistaken for a broken one.

ENV FLAGS (all default OFF — self-work is opt-in, not opt-out)
--------------------------------------------------------------
  ORCH_SELF_IMPROVEMENT_ENABLED   allow improvement proposals targeting `beethoven`
  ORCH_CODER_CANARIES             allow synthetic `canary-<coder>-N` routing samples
  ORCH_DEPLOY_CANARIES            allow synthetic `canary-<app>-<date>` heartbeats
  ORCH_SHADOW_TRIALS              allow paired `shadow-*` trial tasks
  ORCH_SESSION_AUTOCONTINUE       allow `cont-*` session auto-continuation tasks

Set any to 1/true/yes/on to restore the previous behaviour.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# The orchestrator's own project name. Work targeting this is "self-work".
SELF_PROJECT = os.environ.get("ORCH_SELF_PROJECT", "beethoven")

# flag name -> (default, human description used in the suppression log line)
GATES = {
    "ORCH_SELF_IMPROVEMENT_ENABLED": ("false", "improvement proposals targeting the orchestrator itself"),
    "ORCH_CODER_CANARIES": ("false", "synthetic coder-canary routing sample tasks"),
    "ORCH_DEPLOY_CANARIES": ("false", "synthetic deploy-canary heartbeat tasks"),
    "ORCH_SHADOW_TRIALS": ("false", "paired shadow trial tasks"),
    "ORCH_SESSION_AUTOCONTINUE": ("false", "session auto-continuation (cont-*) tasks"),
}

_TRUTHY = ("1", "true", "yes", "on")

# de-dupe the loud log so a tight loop doesn't spam the journal
_logged = set()


def enabled(flag):
    """True if `flag` is switched on. Unknown flags default to OFF (fail closed)."""
    default = GATES.get(flag, ("false", ""))[0]
    return os.environ.get(flag, default).strip().lower() in _TRUTHY


def suppressed(flag, detail=""):
    """Log loudly (once per flag+detail) that a generator was gated off, return True.

    Callers use this as `if self_work_gate.suppressed("ORCH_X"): return ...` so the
    suppression is always visible in the job's own stdout.
    """
    desc = GATES.get(flag, ("false", flag))[1]
    key = (flag, detail)
    if key not in _logged:
        _logged.add(key)
        print(f"[self_work_gate] SUPPRESSED: {desc}"
              + (f" ({detail})" if detail else "")
              + f" — gated off by {flag} (default off). Set {flag}=1 to restore.",
              flush=True)
    return True


def allow_generator(flag, detail=""):
    """True if the generator may run; otherwise logs the suppression and returns False."""
    if enabled(flag):
        return True
    suppressed(flag, detail)
    return False


def is_self_project(name):
    return (name or "").strip().lower() == SELF_PROJECT.lower()


def allow_self_target(app, detail=""):
    """True if a proposal/task may target `app`.

    User apps are always allowed. The orchestrator's own repo is allowed only when
    ORCH_SELF_IMPROVEMENT_ENABLED is on.
    """
    if not is_self_project(app):
        return True
    if enabled("ORCH_SELF_IMPROVEMENT_ENABLED"):
        return True
    suppressed("ORCH_SELF_IMPROVEMENT_ENABLED", detail or f"target={app}")
    return False


def status():
    """Snapshot of every gate — used by dashboards and the periodic selfcheck job."""
    return {flag: enabled(flag) for flag in GATES}


if __name__ == "__main__":
    import json
    print(json.dumps({"self_project": SELF_PROJECT, "gates": status()}, indent=2))
