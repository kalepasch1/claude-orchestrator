#!/usr/bin/env python3
"""
soft_dep_spec.py — soft-dependency speculation for the orchestrator.

Most task deps in the planner DAG are "soft" — the LLM *thinks* they might
conflict, but >80% of the time they touch disjoint files. This module lets
those tasks start early by comparing file scopes.

A task with unfinished deps can run speculatively if:
  1. Its file_scope doesn't overlap with any unfinished dep's file_scope
  2. Speculation is enabled (ORCH_SOFT_DEP_SPEC_ENABLED)
  3. The task is not material/sensitive
  4. The task has a declared file_scope (we can't verify safety without one)

When the dep finishes, runner.py calls validate() to check if the dep actually
modified files in the speculative task's scope. If so, the task is re-queued.
If not, the work stands.

Integration:
  - db.py claim_task: if deps aren't all done, check soft_dep_spec.can_speculate(task)
  - runner.py set_state(DONE): call soft_dep_spec.on_dep_done(completed_task)
  - runner.py run_task: wrap worktree in checkpoint/confirm flow

Environment:
    ORCH_SOFT_DEP_SPEC_ENABLED       Kill switch (default: true)
    ORCH_SOFT_DEP_SPEC_MAX_PENDING   Max unfinished deps to tolerate (default: 2)
"""
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import db as _db
except Exception:
    _db = None

try:
    import log as _log_mod
    _log = _log_mod.get("soft_dep_spec")
except Exception:
    import logging
    _log = logging.getLogger("soft_dep_spec")

ENABLED = os.environ.get("ORCH_SOFT_DEP_SPEC_ENABLED", "true").lower() in (
    "true", "1", "yes", "on"
)
MAX_PENDING = int(os.environ.get("ORCH_SOFT_DEP_SPEC_MAX_PENDING", "2"))

_lock = threading.Lock()
_speculating: dict[str, dict] = {}  # task_id -> {slug, file_scope, pending_deps}


def _file_scope_set(task: dict) -> set[str]:
    """Extract file scope as a set of paths."""
    scope_str = task.get("file_scope", "")
    return {f.strip() for f in scope_str.split(",") if f.strip()}


def _get_dep_scopes(deps: list[str], done_slugs: set[str]) -> dict[str, set[str]]:
    """For unfinished deps, look up their file scopes from the DB."""
    if not _db:
        return {}
    pending = [d for d in deps if d not in done_slugs]
    if not pending:
        return {}
    scopes = {}
    for slug in pending:
        try:
            rows = _db.select("tasks", {"slug": f"eq.{slug}", "select": "slug,file_scope", "limit": "1"})
            if rows:
                scopes[slug] = _file_scope_set(rows[0])
        except Exception:
            pass
    return scopes


def can_speculate(task: dict, done_slugs: set[str]) -> tuple[bool, str]:
    """Check if a task with unfinished deps can run speculatively.

    Args:
        task: The candidate task dict (needs deps, file_scope)
        done_slugs: Set of slugs that are in DONE/MERGED state

    Returns:
        (can_run: bool, reason: str)
    """
    if not ENABLED:
        return False, "disabled"

    deps = task.get("deps") or []
    if not deps:
        return True, "no deps"

    # All done — no speculation needed
    pending = [d for d in deps if d not in done_slugs]
    if not pending:
        return True, "all deps done"

    if len(pending) > MAX_PENDING:
        return False, f"too many pending deps ({len(pending)} > {MAX_PENDING})"

    # Must have a declared file scope
    my_scope = _file_scope_set(task)
    if not my_scope:
        return False, "no file_scope declared"

    # Never speculate on sensitive tasks
    prompt = (task.get("prompt") or "").lower()
    for s in ("security", "migration", "schema", "payment", "credential"):
        if s in prompt:
            return False, f"sensitive: {s}"

    # Check overlap with each pending dep's file scope
    dep_scopes = _get_dep_scopes(pending, done_slugs)
    for dep_slug, dep_scope in dep_scopes.items():
        overlap = my_scope & dep_scope
        if overlap:
            return False, f"overlaps with {dep_slug}: {sorted(overlap)[:3]}"

    # No dep has a declared scope? Can't verify safety
    if not dep_scopes:
        return False, "pending deps have no file_scope"

    return True, f"disjoint scopes ({len(pending)} pending deps)"


def register(task: dict, pending_deps: list[str]):
    """Register a task as running speculatively."""
    task_id = str(task.get("id", ""))
    with _lock:
        _speculating[task_id] = {
            "slug": task.get("slug", ""),
            "file_scope": _file_scope_set(task),
            "pending_deps": set(pending_deps),
        }
    _log.info("soft_dep_spec: %s running speculatively (pending: %s)",
              task.get("slug"), ", ".join(pending_deps))


def on_dep_done(completed_task: dict) -> list[str]:
    """Called when a dependency finishes. Returns task IDs that must be invalidated.

    Checks if the completed dep modified files in any speculating task's scope.
    """
    if not ENABLED:
        return []

    dep_slug = completed_task.get("slug", "")
    dep_scope = _file_scope_set(completed_task)
    invalidated = []

    with _lock:
        for task_id, info in list(_speculating.items()):
            if dep_slug not in info["pending_deps"]:
                continue
            # Remove from pending
            info["pending_deps"].discard(dep_slug)

            # Check if the dep actually touched overlapping files
            overlap = info["file_scope"] & dep_scope
            if overlap:
                _log.warning("soft_dep_spec: invalidating %s — dep %s modified %s",
                             info["slug"], dep_slug, sorted(overlap)[:3])
                invalidated.append(task_id)
                del _speculating[task_id]
            elif not info["pending_deps"]:
                # All deps done, no conflicts — confirm
                _log.info("soft_dep_spec: confirmed %s — all deps done, no conflicts",
                          info["slug"])
                del _speculating[task_id]

    return invalidated


def confirm(task: dict):
    """Confirm speculation was valid — remove from tracking."""
    task_id = str(task.get("id", ""))
    with _lock:
        _speculating.pop(task_id, None)


def stats() -> dict:
    """Current speculation statistics."""
    with _lock:
        return {
            "active": len(_speculating),
            "tasks": {tid: info["slug"] for tid, info in _speculating.items()},
        }


# ── Standalone ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import json
    print(json.dumps(stats(), indent=2))
