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


# ── Improvement window ──────────────────────────────────────────────────────
# Improvement generators are confined to a nightly window (default 01:00-05:00 local).
# Two reasons, both operator directives from 2026-09-01:
#   1. Work generated in the window merges to the shared dev branch overnight, so the
#      fleet is not racing a human editing the same repos during the day.
#   2. Improvements then build on current dev rather than on live prod code.
# Wrap-around windows (e.g. 22->6) are supported, same semantics as
# nightly_cheap_sweep.is_off_peak.
IMPROVE_WINDOW_START = int(os.environ.get("ORCH_IMPROVE_WINDOW_START", "1"))
IMPROVE_WINDOW_END = int(os.environ.get("ORCH_IMPROVE_WINDOW_END", "5"))
IMPROVE_WINDOW_TZ = os.environ.get("ORCH_IMPROVE_WINDOW_TZ", "America/New_York")


def improvement_window_enforced():
    """True unless the operator has explicitly turned the window off."""
    return os.environ.get(
        "ORCH_IMPROVE_WINDOW_ENABLED", "true").strip().lower() in _TRUTHY


def _window_now():
    """Current time in the window's timezone.

    Every scheduler in this codebase uses naive datetime.now(), which silently shifts
    the window by 4-5h if the runner is ever launched with TZ=UTC. Resolve explicitly.
    """
    from datetime import datetime
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(IMPROVE_WINDOW_TZ))
    except Exception:
        return datetime.now()


def in_improvement_window(now=None):
    """True if `now` falls inside the improvement window."""
    if not improvement_window_enforced():
        return True
    h = (now or _window_now()).hour
    start, end = IMPROVE_WINDOW_START, IMPROVE_WINDOW_END
    if start == end:
        return True
    if start > end:
        return h >= start or h < end
    return start <= h < end


def allow_improvement_now(detail=""):
    """True if improvement generators may run right now; logs once and returns False otherwise."""
    if in_improvement_window():
        return True
    key = ("ORCH_IMPROVE_WINDOW_ENABLED", detail)
    if key not in _logged:
        _logged.add(key)
        print(f"[self_work_gate] OUTSIDE IMPROVEMENT WINDOW: "
              f"{detail or 'improvement generator'} skipped — window is "
              f"{IMPROVE_WINDOW_START:02d}:00-{IMPROVE_WINDOW_END:02d}:00 {IMPROVE_WINDOW_TZ}, "
              f"now {_window_now():%H:%M}. Set ORCH_IMPROVE_WINDOW_ENABLED=false to disable "
              f"the window.", flush=True)
    return False


def status():
    """Snapshot of every gate — used by dashboards and the periodic selfcheck job."""
    snap = {flag: enabled(flag) for flag in GATES}
    snap["improvement_window"] = {
        "enforced": improvement_window_enforced(),
        "start_hour": IMPROVE_WINDOW_START,
        "end_hour": IMPROVE_WINDOW_END,
        "tz": IMPROVE_WINDOW_TZ,
        "open_now": in_improvement_window(),
    }
    return snap


if __name__ == "__main__":
    import json
    print(json.dumps({"self_project": SELF_PROJECT, "gates": status()}, indent=2))
