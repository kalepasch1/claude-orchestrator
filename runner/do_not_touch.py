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
}

# Kept separate from DO_NOT_WIRE so that satisfying a prerequisite stays a deliberate,
# reviewable edit. Empty is the correct resting state: an entry whose prerequisite is met
# belongs below, wired — or back on DO_NOT_WIRE with a new reason. Sitting here, satisfied
# and unwired, is what cost five weeks.
PREREQUISITE_SATISFIED = set()

#: Jobs that were on DO_NOT_WIRE, had their prerequisite met, and are NOW SCHEDULED.
#: Recorded rather than deleted, so the next audit that finds remotegc doing
#: `git push --delete` on a schedule learns it was a decision — not the hazard the old
#: entry described. tests/test_do_not_touch.py asserts every name here really is in
#: runner.py's _SCHEDULE; that assertion is the one that would have caught this.
WIRED_AFTER_PREREQUISITE = {
    "remotegc": (
        "Wired 2026-09-09 as remotegc-3600 in runner.py's _SCHEDULE. Its prerequisite — "
        "mirror branch_gc.py's terminal_slugs gate (DONE/MERGED/QUARANTINED only) and fail "
        "safe when that set is unavailable — was satisfied 2026-08-04, alongside a "
        "commits_reachable_elsewhere check and an archive before every delete. It then sat "
        "unwired for five weeks because the note in _SCHEDULE still described the pre-gate "
        "behaviour, while apparently-law accumulated 547 remote refs, 517 of them empty."
    ),
}


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
