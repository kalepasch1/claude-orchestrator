#!/usr/bin/env python3
"""
speculative_premerge.py — Build the next dependent task against a judge-passed
(not-yet-merged) parent branch so the critical path never waits on integration.

When task B depends on task A, the normal flow is:
  A runs -> A judged -> A merged -> B starts (on merged base)

With speculative premerge:
  A runs -> A judged (PASS) -> B starts against A's branch (speculative base)
  -> A merges -> B reconciles (rebase onto actual merge commit)

If A fails merge or gets reworked, B is rebased onto the new A or aborted.
"""
import os, sys, json, datetime
from typing import Optional
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

ENABLED = os.environ.get("ORCH_SPECULATIVE_PREMERGE", "true").lower() in ("1", "true", "yes")
MAX_DEPTH = int(os.environ.get("ORCH_PREMERGE_MAX_DEPTH", "3"))


def _get_task(slug, project_id):
    """Fetch a single task by slug and project."""
    rows = db.select("tasks", {
        "select": "id,slug,state,base_branch,deps,kind,project_id",
        "slug": f"eq.{slug}",
        "project_id": f"eq.{project_id}",
        "limit": "1",
    }) or []
    return rows[0] if rows else None


def find_speculative_base(task):
    """Find the best base branch for a task whose deps are judge-passed but not merged.

    Returns {"base": branch, "speculative": bool, "parent_slug": Optional[str], "reason": str}
    """
    if not ENABLED:
        return {"base": task.get("base_branch", "master"), "speculative": False,
                "parent_slug": None, "reason": "speculative premerge disabled"}

    deps = task.get("deps") or []
    if not deps:
        return {"base": task.get("base_branch", "master"), "speculative": False,
                "parent_slug": None, "reason": "no dependencies"}

    project_id = task.get("project_id")
    if not project_id:
        return {"base": task.get("base_branch", "master"), "speculative": False,
                "parent_slug": None, "reason": "no project_id"}

    # Check each dep: find ones DONE (judge-passed) but not yet MERGED
    for dep_slug in deps:
        parent = _get_task(dep_slug, project_id)
        if not parent:
            continue
        state = (parent.get("state") or "").upper()
        if state == "MERGED":
            continue  # already merged, use normal base
        if state == "DONE":
            parent_branch = f"agent/{dep_slug}"
            return {"base": parent_branch, "speculative": True,
                    "parent_slug": dep_slug,
                    "reason": f"dep {dep_slug} is DONE (judge-passed), building speculatively"}
        if state in ("RUNNING", "QUEUED"):
            return {"base": task.get("base_branch", "master"), "speculative": False,
                    "parent_slug": None,
                    "reason": f"dep {dep_slug} still {state}, cannot start"}

    return {"base": task.get("base_branch", "master"), "speculative": False,
            "parent_slug": None, "reason": "all deps merged, normal base"}


def reconcile(task, repo_path=None):
    """After the parent merges, rebase speculative work onto the real merge.

    Returns {"ok": bool, "action": str, "detail": str}
    """
    deps = task.get("deps") or []
    project_id = task.get("project_id")
    if not deps or not project_id:
        return {"ok": True, "action": "noop", "detail": "no deps to reconcile"}

    for dep_slug in deps:
        parent = _get_task(dep_slug, project_id)
        if not parent:
            continue
        state = (parent.get("state") or "").upper()
        if state == "MERGED":
            return {"ok": True, "action": "rebase",
                    "detail": f"parent {dep_slug} merged, rebase onto updated base"}
        if state in ("FAILED", "BLOCKED", "CANCELLED"):
            return {"ok": False, "action": "abort",
                    "detail": f"parent {dep_slug} is {state}, speculative work invalid"}

    return {"ok": True, "action": "wait", "detail": "parent not yet merged"}


def track_speculative(task_id, parent_slug, speculative_base):
    """Record that a task is running speculatively against a parent branch."""
    try:
        db.upsert("task_artifacts", {
            "task_id": task_id,
            "key": "speculative_premerge",
            "value": json.dumps({
                "parent_slug": parent_slug,
                "speculative_base": speculative_base,
                "started_at": datetime.datetime.utcnow().isoformat(),
            }),
        }, on_conflict="task_id,key")
    except Exception:
        pass  # fail-soft


def pending_reconciliations(project_id):
    """List tasks built speculatively that may need reconciliation."""
    try:
        rows = db.select("task_artifacts", {
            "select": "task_id,value",
            "key": "eq.speculative_premerge",
        }) or []
    except Exception:
        return []

    results = []
    for r in rows:
        try:
            meta = json.loads(r.get("value") or "{}")
        except Exception:
            meta = {}
        parent_slug = meta.get("parent_slug")
        if not parent_slug:
            continue
        parent = _get_task(parent_slug, project_id)
        parent_state = (parent.get("state") or "").upper() if parent else "UNKNOWN"
        results.append({
            "task_id": r["task_id"],
            "parent_slug": parent_slug,
            "parent_state": parent_state,
            "needs_reconcile": parent_state in ("MERGED", "FAILED", "BLOCKED"),
        })
    return results
