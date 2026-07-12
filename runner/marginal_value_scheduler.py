#!/usr/bin/env python3
"""
marginal_value_scheduler.py - Diminishing-returns task prioritization.

Applies marginal value scoring to prevent any single project from monopolizing
the fleet. Each additional RUNNING/QUEUED task for a project is worth less than
the last, pushing the queue toward a balanced portfolio of work.

score_marginal(task, ctx) = ev_score / (1 + active_count_for_project)^decay

Environment / fleet_config knobs:
  ORCH_MARGINAL_ENABLED   - enable marginal re-ranking (default true)
  ORCH_MARGINAL_DECAY     - decay exponent (default 0.5)
  ORCH_MARGINAL_DONE_WINDOW_H - hours of recent DONE tasks to count (default 4)
"""
import os, sys, math, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import thermal_map

DECAY = float(os.environ.get("ORCH_MARGINAL_DECAY", "0.5"))
DONE_WINDOW_H = int(os.environ.get("ORCH_MARGINAL_DONE_WINDOW_H", "4"))
TOP_N = 50


def _is_enabled():
    val = os.environ.get("ORCH_MARGINAL_ENABLED", "true").lower()
    if val in ("false", "0", "no", "off"):
        return False
    try:
        rows = db.select("fleet_config", {"select": "value", "key": "eq.ORCH_MARGINAL_ENABLED"}) or []
        if rows:
            return str(rows[0].get("value", "true")).lower() in ("true", "1", "yes", "on")
    except Exception:
        pass
    return True


def _active_counts():
    counts = {}
    try:
        running = db.select("tasks", {"select": "project_id", "state": "eq.RUNNING"}) or []
        for r in running:
            pid = r.get("project_id") or "unknown"
            counts[pid] = counts.get(pid, 0) + 1
    except Exception:
        pass
    try:
        rows = db.select("tasks", {"select": "project_id", "state": "eq.DONE",
                                    "order": "updated_at.desc", "limit": "200"}) or []
        for r in rows:
            pid = r.get("project_id") or "unknown"
            counts[pid] = counts.get(pid, 0) + 0.5
    except Exception:
        pass
    return counts


def score_marginal(task, ctx, active_counts=None):
    ev = thermal_map.score(task, ctx)
    if active_counts is None:
        active_counts = {}
    pid = task.get("project_id") or task.get("project") or "unknown"
    active = active_counts.get(pid, 0)
    decay = float(os.environ.get("ORCH_MARGINAL_DECAY", str(DECAY)))
    return ev / math.pow(1 + active, decay)


def rank(ctx=None):
    if not _is_enabled():
        return {"enabled": False, "ranked": 0}
    if ctx is None:
        ctx = {}
    try:
        tasks = db.select("tasks", {
            "select": "id,slug,project_id,kind,prompt,deps,attempt,transient_retries,note,remediation_count",
            "state": "eq.QUEUED", "order": "created_at.asc", "limit": "200"}) or []
    except Exception as e:
        return {"ranked": 0, "error": str(e)}
    if not tasks:
        return {"ranked": 0}
    active = _active_counts()
    scored = [(score_marginal(t, ctx, active), t) for t in tasks]
    scored.sort(key=lambda x: -x[0])
    n = 0
    for idx, (s, t) in enumerate(scored[:TOP_N]):
        try:
            db.update("tasks", {"id": t["id"]}, {"priority": idx + 1})
            n += 1
        except Exception:
            pass
    return {"ranked": len(scored), "written": n}


def run():
    try:
        result = rank()
        print(f"marginal_value_scheduler: {result}")
        return result
    except Exception as e:
        print(f"marginal_value_scheduler: skipped ({e})")
        return {"ranked": 0, "error": str(e)}


if __name__ == "__main__":
    run()
