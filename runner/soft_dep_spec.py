#!/usr/bin/env python3
"""
soft_dep_spec.py — soft-dependency speculation with rollback.

Allows tasks whose dependencies haven't finished yet to start speculatively
when their file scopes are disjoint from the pending deps' scopes. If a dep
later modifies files in the speculating task's scope, the speculating task
is invalidated and re-queued.

This is different from speculative_exec.py (build-gate bypass). This module
handles *dependency* speculation — running a task before its deps finish,
not skipping the build gate.

Environment:
    ORCH_SOFT_DEP_SPEC_ENABLED   Kill switch (default: true)
    ORCH_SOFT_DEP_SPEC_MAX_PENDING  Max pending deps allowed for speculation (default: 2)

Usage from db.py claim_task():
    import soft_dep_spec
    can, reason = soft_dep_spec.can_speculate(task, done_slugs)
    if can:
        soft_dep_spec.register(task, pending_deps)
    # ... later, when a dep finishes:
    invalidated = soft_dep_spec.on_dep_done(completed_task)
"""
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ENABLED = os.environ.get("ORCH_SOFT_DEP_SPEC_ENABLED", "true").lower() in (
    "true", "1", "yes", "on"
)
MAX_PENDING = int(os.environ.get("ORCH_SOFT_DEP_SPEC_MAX_PENDING", "2"))

# Registry: task_id -> {"task": dict, "pending_deps": [slug], "file_scope": set}
_registry: dict[str, dict] = {}
_lock = threading.Lock()

# Sensitive slugs that should never be speculated
_SENSITIVE_SLUGS = {"contracts", "migrations", "schema", "deploy", "release"}


def _file_scope(task: dict) -> set:
    """Extract file scope as a set of file paths from a task dict."""
    scope_str = task.get("file_scope", "") or ""
    if not scope_str:
        return set()
    return {f.strip() for f in scope_str.split(",") if f.strip()}


def _is_sensitive(task: dict) -> bool:
    """Check if a task is too sensitive for speculation."""
    slug = task.get("slug", "")
    for s in _SENSITIVE_SLUGS:
        if s in slug:
            return True
    return False


def can_speculate(task: dict, done_slugs) -> tuple:
    """Check if a task can run speculatively despite unfinished deps.

    Returns:
        (can_run, reason) — True if speculation is safe, with explanation.
    """
    if not ENABLED:
        return False, "soft-dep-spec disabled"

    if _is_sensitive(task):
        return False, "sensitive task"

    deps = task.get("deps") or []
    if isinstance(done_slugs, list):
        done_slugs = set(done_slugs)

    pending = [d for d in deps if d not in done_slugs]
    if not pending:
        return True, "all deps done"  # Not really speculation

    if len(pending) > MAX_PENDING:
        return False, f"too many pending deps ({len(pending)} > {MAX_PENDING})"

    # Check file scope disjointness
    task_scope = _file_scope(task)
    if not task_scope:
        return False, "no file_scope declared — cannot verify disjointness"

    # Look up pending dep scopes from registry or DB
    try:
        import db as _db
        for dep_slug in pending:
            dep_rows = _db.select("tasks", {"slug": f"eq.{dep_slug}"})
            if dep_rows:
                dep_scope = _file_scope(dep_rows[0])
                if dep_scope and task_scope & dep_scope:
                    overlap = task_scope & dep_scope
                    return False, f"file overlap with {dep_slug}: {overlap}"
    except Exception:
        # If we can't look up dep scopes, check registry
        pass

    # Also check against already-registered speculating tasks
    with _lock:
        for reg_id, reg in _registry.items():
            reg_scope = reg.get("file_scope", set())
            if reg_scope and task_scope & reg_scope:
                return False, f"file overlap with speculating task {reg_id}"

    return True, f"disjoint scopes, {len(pending)} pending deps"


def register(task: dict, pending_deps: list):
    """Register a task as running speculatively."""
    if not ENABLED:
        return

    task_id = task.get("id", "")
    if not task_id:
        return

    with _lock:
        _registry[task_id] = {
            "task": task,
            "pending_deps": list(pending_deps),
            "file_scope": _file_scope(task),
            "slug": task.get("slug", ""),
        }


def on_dep_done(completed_task: dict) -> list:
    """Called when a dependency completes. Check if any speculating tasks
    need to be invalidated because the completed dep modified files in
    their scope.

    Returns:
        List of task IDs that should be re-queued (invalidated).
    """
    if not ENABLED:
        return []

    completed_slug = completed_task.get("slug", "")
    completed_scope = _file_scope(completed_task)

    # Also check the task's actual output/modified files if available
    modified_files = set()
    if completed_task.get("modified_files"):
        if isinstance(completed_task["modified_files"], str):
            modified_files = {f.strip() for f in completed_task["modified_files"].split(",") if f.strip()}
        elif isinstance(completed_task["modified_files"], list):
            modified_files = set(completed_task["modified_files"])
    modified_files |= completed_scope

    invalidated = []
    with _lock:
        to_remove = []
        for task_id, reg in _registry.items():
            # Is this completed task one of the pending deps?
            if completed_slug not in reg["pending_deps"]:
                continue

            # Remove from pending
            reg["pending_deps"] = [d for d in reg["pending_deps"] if d != completed_slug]

            # Check if completed task modified files in our scope
            if modified_files and reg["file_scope"] and modified_files & reg["file_scope"]:
                invalidated.append(task_id)
                to_remove.append(task_id)

            # If no more pending deps, speculation confirmed — remove from registry
            if not reg["pending_deps"]:
                to_remove.append(task_id)

        for tid in set(to_remove):
            _registry.pop(tid, None)

    return invalidated


def confirm(task: dict):
    """Confirm speculation succeeded — remove from registry."""
    task_id = task.get("id", "")
    with _lock:
        _registry.pop(task_id, None)


def stats() -> dict:
    """Return current speculation statistics."""
    with _lock:
        return {
            "enabled": ENABLED,
            "max_pending": MAX_PENDING,
            "active_speculations": len(_registry),
            "tasks": {tid: reg["slug"] for tid, reg in _registry.items()},
        }
