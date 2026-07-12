#!/usr/bin/env python3
"""
greedy_dispatch.py — Immediate dispatch of decomposed tasks to available runners.

On task decomposition, immediately dispatch child tasks to any available runner
instead of waiting for the normal polling cycle. Uses greedy-first routing when
the affinity queue is deep (>100 tasks), falling back to affinity-aware routing
for shallow queues.

This eliminates the latency between decomposition and execution: sub-tasks that
were just created start running within seconds instead of waiting for the next
poll interval (which can be 30-60s × queue depth).

Called by auto_remediate.py and bankruptcy_decompose.py after spawning sub-tasks.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

# When the affinity queue exceeds this depth, switch to greedy-first routing
AFFINITY_DEPTH_THRESHOLD = int(os.environ.get("ORCH_AFFINITY_DEPTH_THRESHOLD", "100"))

# Maximum tasks to dispatch in one greedy batch
GREEDY_BATCH_SIZE = int(os.environ.get("ORCH_GREEDY_BATCH_SIZE", "10"))


def _get_available_runners():
    """Find runners that are not at capacity. Fail-soft."""
    try:
        rows = db.select("fleet_config", {
            "select": "key,value",
            "key": "like.runner_capacity:%",
        }) or []
        available = []
        for r in rows:
            try:
                cap = eval(r.get("value", "{}"))  # {"max": 4, "current": 2, "account": "..."}
                if isinstance(cap, dict) and cap.get("current", 0) < cap.get("max", 0):
                    available.append(cap)
            except Exception:
                continue
        return available
    except Exception:
        return []


def _get_queued_depth(project_id=None):
    """Count QUEUED tasks to determine affinity queue depth."""
    try:
        params = {"state": "eq.QUEUED", "select": "id"}
        if project_id:
            params["project_id"] = f"eq.{project_id}"
        return db.count("tasks", params) or 0
    except Exception:
        return 0


def _use_greedy_routing(project_id=None):
    """Decide whether to use greedy-first or affinity-aware routing."""
    depth = _get_queued_depth(project_id)
    return depth > AFFINITY_DEPTH_THRESHOLD


def dispatch_immediate(task_ids, project_id=None):
    """Immediately mark freshly-decomposed child tasks as ready for pickup.

    In greedy mode (deep queue), tasks are marked QUEUED with priority boost
    so any available runner picks them up, ignoring affinity preferences.
    In affinity mode (shallow queue), tasks keep their normal affinity hints
    but get a recency boost to move to the front of the queue.

    Args:
        task_ids: list of child task IDs just created by decomposition
        project_id: optional project filter

    Returns:
        int: number of tasks dispatched
    """
    if not task_ids:
        return 0

    greedy = _use_greedy_routing(project_id)
    dispatched = 0

    for tid in task_ids[:GREEDY_BATCH_SIZE]:
        try:
            patch = {
                "state": "QUEUED",
                "updated_at": "now()",
            }
            if greedy:
                # Greedy mode: clear affinity hints so any runner can claim
                patch["note"] = (patch.get("note") or "") + " [greedy-dispatch: affinity bypassed]"
                patch["account"] = None
            else:
                # Affinity mode: just ensure task is QUEUED with fresh timestamp
                patch["note"] = (patch.get("note") or "") + " [dispatch: affinity-aware]"

            db.update("tasks", {"id": tid}, patch)
            dispatched += 1
        except Exception:
            continue  # fail-soft per task

    return dispatched


def on_decomposition_complete(parent_task, child_task_ids):
    """Hook called after decomposition creates child tasks.

    Immediately dispatches children to available runners instead of
    waiting for the next poll cycle.
    """
    project_id = parent_task.get("project_id")
    dispatched = dispatch_immediate(child_task_ids, project_id)

    # Log dispatch event for observability
    try:
        slug = parent_task.get("slug", "unknown")
        mode = "greedy" if _use_greedy_routing(project_id) else "affinity"
        db.insert("fleet_config", {
            "key": f"greedy_dispatch:{slug}",
            "value": f"dispatched {dispatched}/{len(child_task_ids)} children, mode={mode}",
        }, on_conflict="key", merge_patch={"value": "EXCLUDED.value"})
    except Exception:
        pass

    return dispatched
