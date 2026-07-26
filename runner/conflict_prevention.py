"""Conflict-free coordination for multiple agents, swarms, and vibe-coders
working on the same repos, branches, and worktrees simultaneously.

Implements:
1. File-level locking (exclusive for writes, shared for reads)
2. Worktree isolation enforcement
3. Branch conflict prediction
4. Real-time conflict broadcasting via discovery bus
5. Automatic conflict resolution strategies
"""

import os
import re
import logging
import subprocess
import time
import threading
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Any, Optional

log = logging.getLogger(__name__)

try:
    import db
except ImportError:
    db = None

TABLE = "file_locks"
_lock = threading.Lock()


def acquire_lock(project_id: str, file_path: str, locked_by: str,
                 lock_type: str = "exclusive", task_slug: Optional[str] = None,
                 duration_minutes: int = 30) -> Tuple[bool, Dict[str, Any]]:
    """Acquire a file lock. Returns (success: bool, lock_or_conflict: dict).

    Args:
        project_id: Project identifier
        file_path: File path to lock
        locked_by: DAG ID or agent identifier
        lock_type: 'exclusive' or 'shared'
        task_slug: Task slug (optional)
        duration_minutes: Lock duration in minutes

    Returns:
        Tuple of (success, lock_dict_or_conflict_info)
    """
    if not db:
        return True, {"fallback": "no db, proceeding unlocked"}

    expires_at = (datetime.utcnow() + timedelta(minutes=duration_minutes)).isoformat()

    # Clean expired locks first
    try:
        db.execute_rpc("release_expired_file_locks", {})
    except Exception:
        pass  # RPC may not exist yet, fail-soft

    # Check for existing exclusive lock
    try:
        existing = db.select(TABLE, {
            "project_id": project_id,
            "file_path": file_path,
            "released_at": None,
            "lock_type": "exclusive",
        }, limit=1) or []
    except Exception as e:
        log.warning("file_locks query failed, proceeding unlocked: %s", e)
        return True, {"fallback": str(e)}

    if existing and existing[0].get("locked_by") != locked_by:
        return False, {
            "conflict": True,
            "held_by": existing[0]["locked_by"],
            "task_slug": existing[0].get("task_slug"),
            "acquired_at": existing[0]["acquired_at"],
            "expires_at": existing[0]["expires_at"],
        }

    # Acquire
    try:
        lock = db.insert(TABLE, {
            "project_id": project_id,
            "file_path": file_path,
            "locked_by": locked_by,
            "lock_type": lock_type,
            "task_slug": task_slug,
            "expires_at": expires_at,
        })
        return True, lock or {}
    except Exception as e:
        # Unique constraint violation means someone else got it first
        if "uq_active_exclusive" in str(e) or "unique" in str(e).lower():
            return False, {"conflict": True, "reason": "concurrent acquisition"}
        log.error("file_locks insert failed: %s", e)
        return True, {"fallback": str(e)}


def release_lock(project_id: str, file_path: str, locked_by: str) -> int:
    """Release a file lock.

    Args:
        project_id: Project identifier
        file_path: File path to release
        locked_by: Lock holder identifier

    Returns:
        Number of locks released
    """
    if not db:
        return 0
    try:
        locks = db.select(TABLE, {
            "project_id": project_id,
            "file_path": file_path,
            "locked_by": locked_by,
            "released_at": None,
        }) or []
        released = 0
        for lock in locks:
            db.update(TABLE, lock["id"], {"released_at": "now()"})
            released += 1
        return released
    except Exception as e:
        log.error("file_locks release failed: %s", e)
        return 0


def release_all_locks(locked_by: str) -> int:
    """Release all locks held by an agent/DAG.

    Args:
        locked_by: Lock holder identifier

    Returns:
        Number of locks released
    """
    if not db:
        return 0
    try:
        locks = db.select(TABLE, {"locked_by": locked_by, "released_at": None}) or []
        released = 0
        for lock in locks:
            db.update(TABLE, lock["id"], {"released_at": "now()"})
            released += 1
        return released
    except Exception as e:
        log.error("file_locks release_all failed: %s", e)
        return 0


def predict_conflicts(dag_tasks: List[Dict[str, Any]], project_id: str) -> List[Dict[str, Any]]:
    """Predict which files concurrent DAGs will touch and warn.

    Uses file_scope (already in the codebase) to predict file scope,
    then checks against active locks.

    Args:
        dag_tasks: List of task dicts with slug, file_scope
        project_id: Project identifier

    Returns:
        List of predicted conflict dicts
    """
    conflicts = []
    for task in dag_tasks:
        predicted_files = task.get("file_scope", [])
        for fp in predicted_files:
            ok, info = acquire_lock(
                project_id, fp, f"prediction-{task.get('slug', '?')}",
                lock_type="shared", duration_minutes=5
            )
            if not ok:
                conflicts.append({
                    "task_slug": task.get("slug", "?"),
                    "file_path": fp,
                    "held_by": info.get("held_by"),
                    "resolution": "reorder_or_wait",
                })
    return conflicts


def broadcast_conflicts(conflicts: List[Dict[str, Any]], bus: Any) -> None:
    """Publish predicted conflicts to the discovery bus.

    Args:
        conflicts: List of conflict dicts from predict_conflicts()
        bus: SharedDiscoveryBus instance (or None to skip)
    """
    if not bus:
        return
    for conflict in conflicts:
        bus.publish({
            "slug": "conflict-prevention",
            "kind": "conflict_predicted",
            "summary": f"⚠️ File conflict: {conflict['file_path']} also being edited by {conflict['held_by']}",
            "tags": ["conflict", "warning", conflict["file_path"].split("/")[0]],
            "content": f"Task {conflict['task_slug']} wants to edit {conflict['file_path']} "
                       f"but it's locked by {conflict['held_by']}. "
                       f"Resolution: {conflict['resolution']}",
            "confidence": 1.0,
            "ts": time.time(),
        })


def worktree_guard(repo_path: str, slug: str) -> bool:
    """Ensure this task is running in an isolated worktree, not the main checkout.

    Complements sentinel.py's existing nested_worktree_guard().

    Args:
        repo_path: Repository path
        slug: Task slug for logging

    Returns:
        True if in worktree or unknown, False if in main checkout
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, cwd=repo_path
        )
        toplevel = result.stdout.strip()
        # If we're in the main repo (not a worktree), warn
        if not ("-wt/" in toplevel or "-wt\\" in toplevel):
            log.warning("conflict_prevention: task %s running in main checkout, not worktree!", slug)
            return False
        return True
    except Exception as e:
        log.warning("worktree_guard check failed: %s", e)
        return True  # fail-soft


def merge_safety_check(source_branch: str, target_branch: str, repo_path: str) -> Tuple[bool, str]:
    """Pre-merge conflict check using git merge-tree.

    Args:
        source_branch: Source branch name
        target_branch: Target branch name
        repo_path: Repository path

    Returns:
        Tuple of (is_safe: bool, conflict_summary: str)
    """
    try:
        result = subprocess.run(
            ["git", "merge-tree", "--write-tree", target_branch, source_branch],
            capture_output=True, text=True, cwd=repo_path
        )
        has_conflicts = "CONFLICT" in result.stdout or result.returncode != 0
        summary = result.stdout[:1000] if has_conflicts else ""
        return not has_conflicts, summary
    except Exception as e:
        log.warning("merge_safety_check failed: %s", e)
        return True, ""  # fail-soft


def stats() -> Dict[str, Any]:
    """Get current file lock statistics.

    Returns:
        Dict with active_locks count
    """
    if not db:
        return {}
    try:
        active = db.count(TABLE, {"released_at": None}) or 0
        return {"active_locks": active}
    except Exception as e:
        log.error("stats failed: %s", e)
        return {}


def active_locks(project_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Get all active file locks.

    Args:
        project_id: Filter by project (optional)

    Returns:
        List of active lock dicts
    """
    if not db:
        return []
    try:
        filters = {"released_at": None}
        if project_id:
            filters["project_id"] = project_id
        return db.select(TABLE, filters, order="acquired_at.asc", limit=1000) or []
    except Exception as e:
        log.error("active_locks query failed: %s", e)
        return []


def lock_status(file_path: str, project_id: str) -> Optional[Dict[str, Any]]:
    """Get lock status for a specific file.

    Args:
        file_path: File to check
        project_id: Project identifier

    Returns:
        Lock dict if locked, None otherwise
    """
    if not db:
        return None
    try:
        locks = db.select(TABLE, {
            "file_path": file_path,
            "project_id": project_id,
            "released_at": None,
        }, limit=1) or []
        return locks[0] if locks else None
    except Exception as e:
        log.error("lock_status query failed: %s", e)
        return None
