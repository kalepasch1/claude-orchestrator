"""Execution-liveness and approval controls for the task queue.

This module is intentionally dependency-light so it can run from the scheduler,
the janitor, and tests without importing the executor.
"""
from __future__ import annotations

import datetime as dt
import os


TERMINAL_STATES = {"DONE", "MERGED", "BLOCKED", "QUARANTINED", "TESTFAIL", "BUILDFAIL", "CONFLICT"}


def normalize_deps(value):
    """Return a stable, non-null dependency list for task inserts."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value if str(item).strip()]
    raise ValueError("task deps must be a list or null")


def is_counsel_gated(task):
    """True only for explicit design/spec work; ordinary speculative execution remains unaffected."""
    kind = str(task.get("kind") or "").lower()
    prompt = str(task.get("prompt") or "").lower()
    return kind == "speculative" and ("design-spec" in prompt or "counsel" in prompt)


def counsel_gate_satisfied(task):
    """Require explicitly stored operator and counsel approvals before code execution."""
    if not is_counsel_gated(task):
        return True
    return bool(
        task.get("operator_approved_at") and task.get("operator_approved_by")
        and task.get("counsel_approved_at") and task.get("counsel_approved_by")
    )


def parse_timestamp(value):
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def dispatch_sla_breaches(tasks, runs, now=None, minutes=None):
    """Return DECOMPOSED tasks that have not produced an execution record within the SLA."""
    now = now or dt.datetime.now(dt.timezone.utc)
    minutes = minutes if minutes is not None else int(os.environ.get("ORCH_DECOMPOSED_RUN_SLA_MIN", "10"))
    run_task_ids = {str(run.get("task_id")) for run in runs or [] if run.get("task_id")}
    # A DECOMPOSED parent is intentionally not executed itself: its children
    # reference the parent slug in their dependency list. Likewise, a task
    # waiting on its own dependencies or carrying an explicit hold is not a
    # dispatch failure. These are valid state-invariant exceptions.
    parent_slugs = {
        str(dependency)
        for candidate in tasks or []
        for dependency in (candidate.get("deps") or [])
        if dependency
    }
    breached = []
    for task in tasks or []:
        if task.get("state") != "DECOMPOSED" or str(task.get("id")) in run_task_ids:
            continue
        note = str(task.get("note") or "").lower()
        if task.get("deps") or str(task.get("slug") or "") in parent_slugs or note.startswith("held:"):
            continue
        updated = parse_timestamp(task.get("updated_at") or task.get("created_at"))
        if updated and (now - updated).total_seconds() >= minutes * 60:
            breached.append(task)
    return breached


def state_invariant_violations(tasks, runs, now=None):
    """Describe queue rows that violate the decomposed-work execution contract."""
    return [{"task": task, "reason": "decomposed_without_run"}
            for task in dispatch_sla_breaches(tasks, runs, now=now)]
