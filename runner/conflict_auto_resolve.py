#!/usr/bin/env python3
"""
conflict_auto_resolve.py — built-in mechanisms to resolve merge conflicts
and recover missing branches automatically.

Integrates conflict_predictor's detection with automated resolution strategies:
1. File-scope serialization: requeue conflicting tasks to run after the blocker
2. Branch recovery: recreate missing branches from task prompts
3. Auto-rebase: attempt git rebase for trivially resolvable conflicts

Fail-soft: errors return empty/defaults, never raise.
"""
import os
import sys
import time
import json
import subprocess
import logging
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

log = logging.getLogger("conflict_auto_resolve")

HOME = os.environ.get("CLAUDE_ORCH_HOME", os.path.expanduser("~/.claude-orchestrator"))
ENABLED = os.environ.get("ORCH_CONFLICT_AUTO_RESOLVE", "true").lower() == "true"
MAX_REBASE_ATTEMPTS = int(os.environ.get("ORCH_MAX_REBASE_ATTEMPTS", "2"))
MAX_RECOVER_PER_RUN = int(os.environ.get("ORCH_MAX_RECOVER_PER_RUN", "5"))

_lock = threading.Lock()
_stats = {
    "conflicts_resolved": 0,
    "branches_recovered": 0,
    "rebase_successes": 0,
    "rebase_failures": 0,
    "serializations": 0,
}


def stats():
    return dict(_stats)


def _git(*args, cwd=None, timeout=60):
    """Run a git command, return (returncode, stdout)."""
    try:
        r = subprocess.run(["git"] + list(args), cwd=cwd,
                           capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout.strip()
    except Exception as e:
        return -1, str(e)


def attempt_auto_rebase(branch, base, repo_path):
    """Try to rebase a branch onto its base. Returns True on success.

    Only attempts trivial rebases (no conflict markers). Aborts on any
    conflict and restores the original state.
    """
    if not ENABLED or not repo_path or not os.path.isdir(repo_path):
        return False

    rc, _ = _git("checkout", branch, cwd=repo_path)
    if rc != 0:
        return False

    rc, out = _git("rebase", base, cwd=repo_path)
    if rc != 0:
        _git("rebase", "--abort", cwd=repo_path)
        with _lock:
            _stats["rebase_failures"] += 1
        log.info("auto-rebase failed for %s onto %s: %s", branch, base, out[:200])
        return False

    with _lock:
        _stats["rebase_successes"] += 1
    log.info("auto-rebase succeeded for %s onto %s", branch, base)
    return True


def serialize_conflicting_task(task, blocking_slug):
    """Add a dependency so the conflicting task waits for the blocker to merge.

    Returns True if the serialization was applied.
    """
    if not ENABLED:
        return False
    try:
        import db
        task_id = task.get("id")
        existing_deps = task.get("deps") or []
        if blocking_slug in existing_deps:
            return False

        new_deps = existing_deps + [blocking_slug]
        db.update("tasks", {"id": task_id}, {"deps": new_deps,
                                              "note": f"auto-serialized behind {blocking_slug}"})
        with _lock:
            _stats["serializations"] += 1
        return True
    except Exception as e:
        log.warning("serialize_conflicting_task error: %s", e)
        return False


def recover_missing_branch(task, repo_path):
    """Recover a missing branch by creating it from the base branch.

    If a task is DONE but its branch is missing, create the branch from
    the task's base_branch so downstream work can proceed.

    Returns True if recovery succeeded.
    """
    if not ENABLED or not repo_path or not os.path.isdir(repo_path):
        return False

    slug = task.get("slug", "")
    base = task.get("base_branch") or "master"
    branch = f"agent/{slug}"

    rc, _ = _git("rev-parse", "--verify", branch, cwd=repo_path)
    if rc == 0:
        return False  # branch already exists

    rc, _ = _git("branch", branch, base, cwd=repo_path)
    if rc != 0:
        log.warning("failed to recover branch %s from %s", branch, base)
        return False

    with _lock:
        _stats["branches_recovered"] += 1
    log.info("recovered missing branch %s from %s", branch, base)
    return True


def resolve_conflicts(task, repo_path=""):
    """Main entry point: attempt to auto-resolve conflicts for a task.

    Strategy:
    1. Check for conflicts via conflict_predictor
    2. If conflicts found, try serialization (add dep)
    3. If branch missing, try recovery
    4. If rebase needed, try auto-rebase

    Returns dict with 'resolved': bool, 'strategy': str, 'detail': str
    """
    if not ENABLED:
        return {"resolved": False, "strategy": "disabled", "detail": "auto-resolve disabled"}

    slug = task.get("slug", "unknown")
    result = {"resolved": False, "strategy": "none", "detail": ""}

    # Step 1: Check conflicts
    try:
        import conflict_predictor
        check = conflict_predictor.check_conflicts(task)
        conflicts = check.get("conflicts", [])
        action = check.get("action", "proceed")

        if action == "defer" and conflicts:
            blocking = conflicts[0] if isinstance(conflicts[0], str) else conflicts[0].get("slug", "")
            if blocking and serialize_conflicting_task(task, blocking):
                result = {"resolved": True, "strategy": "serialization",
                          "detail": f"serialized behind {blocking}"}
                with _lock:
                    _stats["conflicts_resolved"] += 1
                return result
    except Exception as e:
        log.debug("conflict check failed for %s: %s", slug, e)

    # Step 2: Check for missing branch
    if repo_path:
        branch = f"agent/{slug}"
        rc, _ = _git("rev-parse", "--verify", branch, cwd=repo_path)
        if rc != 0:
            if recover_missing_branch(task, repo_path):
                result = {"resolved": True, "strategy": "branch_recovery",
                          "detail": f"recovered {branch}"}
                with _lock:
                    _stats["conflicts_resolved"] += 1
                return result

    # Step 3: Try auto-rebase if branch exists but is behind
    if repo_path:
        branch = f"agent/{slug}"
        base = task.get("base_branch") or "master"
        rc, _ = _git("rev-parse", "--verify", branch, cwd=repo_path)
        if rc == 0:
            if attempt_auto_rebase(branch, base, repo_path):
                result = {"resolved": True, "strategy": "auto_rebase",
                          "detail": f"rebased {branch} onto {base}"}
                with _lock:
                    _stats["conflicts_resolved"] += 1
                return result

    return result


def run():
    """Periodic entry point — scan for blocked tasks and attempt resolution."""
    if not ENABLED:
        return
    resolved_count = 0
    try:
        import db
        blocked = db.select("tasks", {
            "select": "id,slug,project_id,base_branch,deps,prompt,note",
            "state": "eq.BLOCKED",
            "order": "updated_at.asc",
            "limit": str(MAX_RECOVER_PER_RUN),
        }) or []

        projects = {p["id"]: p for p in (db.select("projects", {"select": "id,repo_path"}) or [])}

        for task in blocked:
            proj = projects.get(task.get("project_id"), {})
            repo_path = proj.get("repo_path", "")
            try:
                repo_path = db.localize_repo_path(repo_path)
            except Exception:
                pass

            outcome = resolve_conflicts(task, repo_path)
            if outcome.get("resolved"):
                resolved_count += 1
                try:
                    db.update("tasks", {"id": task["id"]}, {
                        "state": "QUEUED",
                        "note": f"auto-resolved: {outcome.get('strategy')} - {outcome.get('detail')}",
                    })
                except Exception:
                    pass

    except Exception as e:
        log.warning("conflict_auto_resolve periodic run error: %s", e)

    return resolved_count
