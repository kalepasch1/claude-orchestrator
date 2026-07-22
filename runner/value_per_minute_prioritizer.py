#!/usr/bin/env python3
"""
value_per_minute_prioritizer.py — VPM-aware queue scoring.

Enhances task claim ordering with two signals the base priority scorer lacks:

1. **Project MRR weight**: tasks in higher-MRR projects get a priority boost
   so the queue naturally routes capacity toward revenue-generating work.

2. **Deploy-readiness boost**: tasks whose project already has DONE items
   awaiting merge are boosted — finishing them unblocks the nearest deploy.

3. **Auto-rebase fast-retry**: DONE tasks with a missing merge base are
   flagged for rebase before new work is claimed, avoiding stale branches.

Periodic job interface: call run() from periodic.py.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

BATCH_SIZE = int(os.environ.get("ORCH_VPM_BATCH", "50"))
SCORE_CAP = int(os.environ.get("ORCH_VPM_SCORE_CAP", "300"))


def _project_mrr_map():
    """Return {project_id: mrr_usd} from app_revenue."""
    try:
        rows = db.select("app_revenue", {"select": "app,mrr_usd"}) or []
        return {str(r.get("app") or ""): float(r.get("mrr_usd") or 0) for r in rows}
    except Exception:
        return {}


def _deploy_ready_projects():
    """Return set of project_ids that have DONE tasks awaiting merge (nearest to deploy)."""
    try:
        rows = db.select("tasks", {
            "select": "project_id",
            "state": "eq.DONE",
            "limit": "200",
        }) or []
        return {str(r.get("project_id") or "") for r in rows}
    except Exception:
        return set()


def vpm_boost(task_row, mrr_map=None, deploy_ready=None):
    """Return a negative priority adjustment (lower = higher priority).

    Boost magnitude:
      - MRR tier:  top-25% MRR projects get -15, top-50% get -8
      - Deploy-ready: project has DONE work awaiting merge -> -10
      - Combined cap: -20 (prevents VPM from overriding kind/slug ordering)
    """
    project_id = str(task_row.get("project_id") or "")
    boost = 0

    # MRR-based boost
    if mrr_map and project_id in mrr_map:
        mrr = mrr_map[project_id]
        if mrr > 0:
            all_mrrs = sorted(mrr_map.values(), reverse=True)
            cutoff_25 = all_mrrs[max(0, len(all_mrrs) // 4 - 1)] if all_mrrs else 0
            cutoff_50 = all_mrrs[max(0, len(all_mrrs) // 2 - 1)] if all_mrrs else 0
            if mrr >= cutoff_25:
                boost -= 15
            elif mrr >= cutoff_50:
                boost -= 8

    # Deploy-readiness boost
    if deploy_ready and project_id in deploy_ready:
        boost -= 10

    return max(boost, -20)


def flag_rebase_candidates():
    """Find DONE tasks whose agent branch is missing or stale and flag for rebase.

    Returns count of tasks flagged. Does not perform the rebase itself —
    conflict_auto_resolve.py handles the actual rebase when the merge train
    picks up the flagged item.
    """
    flagged = 0
    try:
        done_tasks = db.select("tasks", {
            "select": "id,slug,project_id,base_branch,note",
            "state": "eq.DONE",
            "limit": str(SCORE_CAP),
            "order": "updated_at.asc",
        }) or []
    except Exception:
        return 0

    for t in done_tasks:
        note = str(t.get("note") or "")
        if "rebase-flagged" in note:
            continue
        if "missing" in note.lower() or "stale" in note.lower():
            try:
                db.update("tasks", {"id": t["id"]}, {
                    "note": (note + " | rebase-flagged by vpm-prioritizer")[:500],
                    "priority": max(1, 5),
                })
                flagged += 1
            except Exception:
                pass
    return flagged


def apply_vpm_scores():
    """Apply VPM boosts to all QUEUED tasks. Returns {scored, adjusted, rebased}."""
    mrr_map = _project_mrr_map()
    deploy_ready = _deploy_ready_projects()
    scored = 0
    adjusted = 0

    try:
        tasks = db.select("tasks", {
            "select": "id,slug,kind,project_id,priority",
            "state": "eq.QUEUED",
            "order": "created_at.asc",
            "limit": str(SCORE_CAP),
        }) or []
    except Exception as e:
        print(f"[vpm-prioritizer] query failed: {e}")
        return {"scored": 0, "adjusted": 0, "rebased": 0}

    batch = []
    for t in tasks:
        scored += 1
        boost = vpm_boost(t, mrr_map, deploy_ready)
        if boost < 0:
            current = int(t.get("priority") or 1000)
            new_priority = max(1, current + boost)
            if new_priority != current:
                batch.append((t["id"], new_priority))
        if len(batch) >= BATCH_SIZE:
            adjusted += _flush(batch)
            batch = []

    if batch:
        adjusted += _flush(batch)

    rebased = flag_rebase_candidates()
    print(f"[vpm-prioritizer] scored={scored} adjusted={adjusted} rebased={rebased}")
    return {"scored": scored, "adjusted": adjusted, "rebased": rebased}


def _flush(batch):
    count = 0
    for tid, priority in batch:
        try:
            db.update("tasks", {"id": tid}, {"priority": priority})
            count += 1
        except Exception:
            pass
    return count


def run():
    """Periodic job entry point."""
    return apply_vpm_scores()


if __name__ == "__main__":
    print(f"vpm_prioritizer: {run()}")
