#!/usr/bin/env python3
"""unspecified_task_closer.py — close QUEUED tasks that are both unspecified and stale.

THE GAP THIS FILLS. preflight_filter.preflight_check already recognises a prompt with no
implementation spec — a bare "PATCH TEMPLATE <hex>" stub, orchestration boilerplate with
no request in it, a prompt too short to act on. But it only runs at DISPATCH time, on the
batch a dispatcher happens to be holding. A row nobody dispatches is never examined, so
an unspecified task sits in QUEUED forever, gets picked up by whichever executor is next,
produces nothing, is repaired, and comes back.

Measured on this fleet 2026-08-24: tasks reached attempt 9, 12 and 13 carrying prompts
that preflight_check classifies as garbage on attempt 0. Every one of those attempts cost
a claim, a model call and a repair. The filter had the right answer the whole time and was
never asked.

So this sweeps the STANDING queue with the same predicate, and closes only where BOTH
conditions hold:

    unspecified   preflight_check() returns a reason
    stale         attempt >= ORCH_UNSPECIFIED_MIN_ATTEMPTS (default 3)

The attempt floor is the important half. A brand-new task with a thin prompt may still be
salvageable by a repair pass that rewrites it; one that has burned several attempts has
already had those passes and is still unspecified. Closing on the predicate alone would
delete work that never got a chance — the same mistake agentic_repair._never_ran_patch
was written to undo.

Nothing is deleted. Rows move to QUARANTINED with a reason, which is reversible.

Conventions (CLAUDE.md): fail-soft everywhere (a broken sweep must not wedge the runner),
module-level singleton delegation, ORCH_-prefixed env vars so limits are fleet-pushable
via fleet_control.py.
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

#: Attempts a task must have burned before "unspecified" is treated as terminal.
MIN_ATTEMPTS = int(os.environ.get("ORCH_UNSPECIFIED_MIN_ATTEMPTS", "3") or 3)

#: Rows examined per sweep. Bounded so one pass cannot become its own outage.
SWEEP_LIMIT = int(os.environ.get("ORCH_UNSPECIFIED_SWEEP_LIMIT", "200") or 200)

#: Prefix every closure carries, so the population is greppable and reversible.
CLOSE_NOTE_PREFIX = "unspecified-stale: "

#: Substrings identifying the preflight verdicts that mean THE PROMPT IS UNUSABLE.
#:
#: preflight_check returns several kinds of verdict and they are not interchangeable.
#: "exhausted N attempts without success" and the recycled-note verdicts describe the
#: task's HISTORY, not its specification — a perfectly well-written task that has failed
#: on a real bug 13 times returns the exhaustion reason, and closing it here would throw
#: away a genuine, actionable request because the bug was hard. Verified: a fully
#: specified prompt at attempt=99 returns "exhausted 99 attempts", at attempt=0 returns
#: "". Only the spec-quality verdicts below are closable.
UNSPECIFIED_REASON_MARKERS = (
    "PATCH TEMPLATE or garbage prompt",
    "prompt too short/empty to be actionable",
    "metadata-only prompt with no implementation spec",
)


def _is_spec_quality_reason(reason):
    """True when the verdict is about the PROMPT rather than the task's history."""
    return any(marker in reason for marker in UNSPECIFIED_REASON_MARKERS)


def _attempt_of(task):
    """Attempt count as an int. A missing/unreadable value reads as 0 (= never ran)."""
    try:
        return int((task or {}).get("attempt") or 0)
    except (TypeError, ValueError):
        return 0


def unspecified_reason(task):
    """Return preflight_check's reason for *task*, or "" when it is actionable.

    Fail-soft: if preflight_filter cannot be imported or raises, the answer is "" —
    an unavailable classifier must never be read as "close this task".
    """
    if not isinstance(task, dict):
        return ""
    try:
        import preflight_filter
    except ImportError:
        logger.warning("unspecified_task_closer: preflight_filter unavailable; no-op")
        return ""
    try:
        reason = str(preflight_filter.preflight_check(task) or "")
    except Exception as exc:  # noqa: BLE001 - logged, then degraded (fail-soft)
        logger.warning("unspecified_task_closer: preflight_check raised (%s); skipping", exc)
        return ""
    return reason if _is_spec_quality_reason(reason) else ""


def should_close(task, min_attempts=None):
    """(bool, reason) — True only when the task is BOTH unspecified AND stale."""
    floor = MIN_ATTEMPTS if min_attempts is None else min_attempts
    reason = unspecified_reason(task)
    if not reason:
        return False, ""
    attempts = _attempt_of(task)
    if attempts < floor:
        # Still inside the window where a repair pass may yet write a real prompt.
        return False, ""
    return True, f"{CLOSE_NOTE_PREFIX}{reason} (attempt {attempts})"


def close_patch(task, min_attempts=None):
    """db.update patch that closes *task*, or {} when it must be left alone.

    QUARANTINED rather than deleted: the row, its prompt and its history stay
    inspectable, and an operator who disagrees can requeue it.
    """
    close, reason = should_close(task, min_attempts)
    if not close:
        return {}
    return {"state": "QUARANTINED", "account": None, "updated_at": "now()", "note": reason}


def plan(tasks, min_attempts=None):
    """Pure planning pass: [(task, patch)] for every task that should close.

    Separated from the DB so the decision can be tested, reviewed and dry-run without
    touching a row — the sweep below is only the part that applies it.
    """
    out = []
    for task in tasks or []:
        patch = close_patch(task, min_attempts)
        if patch:
            out.append((task, patch))
    return out


def sweep(limit=None, min_attempts=None, dry_run=False):
    """Examine QUEUED tasks and close the unspecified-and-stale ones.

    Returns {"examined", "closed", "dry_run", "slugs"}. Never raises: a DB outage,
    a missing table or a rejected update degrades to a reported zero.
    """
    cap = SWEEP_LIMIT if limit is None else max(0, int(limit or 0))
    result = {"examined": 0, "closed": 0, "dry_run": bool(dry_run), "slugs": []}
    if cap == 0:
        return result
    try:
        import db
    except ImportError:
        logger.warning("unspecified_task_closer: db unavailable; no-op")
        return result
    try:
        rows = db.select("tasks", {
            "select": "id,slug,prompt,attempt,state,note",
            "state": "eq.QUEUED",
            # Deterministic window: without an order the page PostgREST returns is not
            # reproducible, so two runs could examine two different 200-row samples.
            "order": "attempt.desc,id.asc",
            "limit": str(cap),
        }) or []
    except Exception as exc:  # noqa: BLE001 - logged, then degraded (fail-soft)
        logger.warning("unspecified_task_closer: could not read queue (%s)", exc)
        return result

    result["examined"] = len(rows)
    for task, patch in plan(rows, min_attempts):
        slug = str(task.get("slug") or "?")
        if dry_run:
            result["closed"] += 1
            result["slugs"].append(slug)
            continue
        try:
            db.update("tasks", {"id": f"eq.{task.get('id')}"}, patch)
        except Exception as exc:  # noqa: BLE001 - one bad row must not stop the sweep
            logger.warning("unspecified_task_closer: could not close %s (%s)", slug, exc)
            continue
        result["closed"] += 1
        result["slugs"].append(slug)
        logger.info("unspecified_task_closer: closed %s — %s", slug, patch["note"])
    return result


def main(argv=None):
    """CLI: `python runner/unspecified_task_closer.py [--dry-run] [--limit N]`."""
    import sys

    args = sys.argv[1:] if argv is None else list(argv)
    dry_run = "--dry-run" in args
    limit = None
    if "--limit" in args:
        index = args.index("--limit")
        if index + 1 < len(args):
            try:
                limit = int(args[index + 1])
            except ValueError:
                limit = None
    outcome = sweep(limit=limit, dry_run=dry_run)
    print(f"unspecified_task_closer: examined={outcome['examined']} "
          f"closed={outcome['closed']} dry_run={outcome['dry_run']}")
    for slug in outcome["slugs"]:
        print(f"  {slug}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
