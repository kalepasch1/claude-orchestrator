#!/usr/bin/env python3
"""do_not_touch.py — machine-readable DO-NOT-TOUCH manifest (audit addendum §A).

A JOBS-dict-vs-`runner.py _SCHEDULE` audit found several jobs defined but never scheduled.
Four of them are unscheduled ON PURPOSE. Left as bare absences, every future "subtraction"
or "wire up the dead code" pass rediscovers them and helpfully "fixes" them — one of which
(`remotegc`) irreversibly deletes remote branches belonging to live tasks.

So the intent is recorded as CODE, not prose: audits import `is_deliberately_unscheduled()`
and skip these instead of filing them as gaps. Removing an entry requires satisfying its
`prerequisite` first, which is asserted by tests/test_do_not_touch.py.

Fail-soft per CLAUDE.md: unknown job -> False (i.e. "not protected"), never an exception.
"""

# job name -> (reason, prerequisite-before-wiring or "")
DO_NOT_WIRE = {
    "mergetrain": (
        "train-60 (merge_train.py) already covers it; running both caused duplicate retries.",
        "",
    ),
    "actionexec": (
        "strict subset of `autoexec`, which is scheduled every 60s and calls the same "
        "function plus more.",
        "",
    ),
    "editorial": (
        "optional guarded-import module, unrelated to queue health.",
        "",
    ),
    "remotegc": (
        "workflow_guardrails.gc_remote_branches() deleted origin/agent/* by AGE ONLY "
        "(`git push origin --delete`, ORCH_REMOTE_BRANCH_GC_DRY_RUN=false in .env) and — unlike "
        "local branch_gc.py — did not check task state, so it could delete the branch of a "
        "QUEUED/RUNNING/BLOCKED task. Irreversible external deletion = material.",
        "gc_remote_branches must mirror branch_gc.py's terminal_slugs gate "
        "(DONE/MERGED/QUARANTINED only) and fail safe when that set is unavailable.",
    ),
}

# The one entry whose prerequisite this change set satisfies. Kept separate from DO_NOT_WIRE
# so that satisfying a prerequisite is a deliberate, reviewable edit rather than a silent one:
# the gate now exists, but wiring the job is still an operator decision.
PREREQUISITE_SATISFIED = {"remotegc"}


def is_deliberately_unscheduled(job):
    """True when `job` is unscheduled on purpose. Never raises."""
    try:
        return str(job) in DO_NOT_WIRE
    except Exception:
        return False


def reason(job):
    """Why `job` is unscheduled, or "" when it isn't on the list. Never raises."""
    try:
        return DO_NOT_WIRE.get(str(job), ("", ""))[0]
    except Exception:
        return ""


def prerequisite(job):
    """What must be true before `job` may be wired, or "" when there is no blocker."""
    try:
        return DO_NOT_WIRE.get(str(job), ("", ""))[1]
    except Exception:
        return ""


def blocked_jobs():
    """Jobs that may NOT be wired until their prerequisite is met. Never raises."""
    try:
        return sorted(j for j, (_, pre) in DO_NOT_WIRE.items()
                      if pre and j not in PREREQUISITE_SATISFIED)
    except Exception:
        return []


def filter_unscheduled(jobs):
    """Given job names an audit flagged as unscheduled, return only the genuine gaps."""
    try:
        return [j for j in (jobs or []) if not is_deliberately_unscheduled(j)]
    except Exception:
        return list(jobs or [])


def render():
    """Operator-readable manifest. Never raises."""
    try:
        lines = ["DO NOT WIRE (unscheduled on purpose — audit addendum §A)", "=" * 56]
        for job in sorted(DO_NOT_WIRE):
            why, pre = DO_NOT_WIRE[job]
            lines.append(f"\n  {job}\n    why: {why}")
            if pre:
                state = "SATISFIED" if job in PREREQUISITE_SATISFIED else "NOT SATISFIED"
                lines.append(f"    prerequisite ({state}): {pre}")
        return "\n".join(lines)
    except Exception:
        return "DO NOT WIRE manifest unavailable"


if __name__ == "__main__":
    print(render())
