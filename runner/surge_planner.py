#!/usr/bin/env python3
"""
surge_planner.py — Maximize value on account reset (200X).

When subscription accounts reset their weekly token budget, we have a
brief window where all capacity is available. This module plans which
tasks to run first to maximize merged output per token spent.

Combines:
  - thermal_queue value scoring (priority × age × domain match)
  - capacity-aware batch sizing (fit within remaining budget)
  - Model portfolio cost estimates (cheap tasks first to warm up)

On each reset, produces a ranked surge plan that the runner consumes
instead of the default FIFO queue.

Usage:
    import surge_planner
    plan = surge_planner.plan_surge()  # returns ordered task IDs
    # Runner checks surge_planner.get_surge_queue() before default poll
"""
import os, sys, json, time, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

SURGE_ENABLED = os.environ.get("ORCH_SURGE_PLANNER", "true").lower() in ("true", "1", "yes")
SURGE_MAX_TASKS = int(os.environ.get("ORCH_SURGE_MAX_TASKS", "20"))
SURGE_WINDOW_H = int(os.environ.get("ORCH_SURGE_WINDOW_H", "4"))
EST_TOKENS_PER_TASK = int(os.environ.get("ORCH_EST_TOKENS_PER_TASK", "5000"))
_STATE_DIR = os.path.join(os.environ.get("CLAUDE_ORCH_HOME",
    os.path.expanduser("~/.claude-orchestrator")), "module_state")


def _score_task(task, now=None):
    """Score a task for surge priority.

    Higher = run first. Factors:
      - priority (P0=100, P1=50, P2=20, P3=10)
      - age bonus (older tasks get +1/hour, capped at +48)
      - kind bonus (fix=20, feature=10, chore=5)
      - dependency bonus (tasks with dependents get +15)
    """
    now = now or time.time()
    score = 0

    # Priority
    prio = task.get("priority", 2)
    prio_map = {0: 100, 1: 50, 2: 20, 3: 10}
    score += prio_map.get(prio, 20)

    # Age bonus
    created = task.get("created_at", "")
    if created:
        try:
            from datetime import datetime
            if isinstance(created, str):
                dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                age_h = (now - dt.timestamp()) / 3600
            else:
                age_h = (now - float(created)) / 3600
            score += min(age_h, 48)
        except Exception:
            pass

    # Kind bonus
    kind = task.get("kind", "feature")
    kind_map = {"fix": 20, "bug": 20, "feature": 10, "chore": 5, "test": 5}
    score += kind_map.get(kind, 10)

    # Dependency bonus: tasks that unblock others
    deps_count = task.get("_dependents_count", 0)
    if deps_count > 0:
        score += 15

    return round(score, 1)


def plan_surge(budget_tokens=None):
    """Create a surge plan: ordered list of tasks to run on account reset.

    Returns: list of {id, slug, score, est_tokens} ordered by score desc
    """
    if not SURGE_ENABLED:
        return []

    # Get queued tasks
    try:
        tasks = db.select("tasks", {
            "select": "id,slug,prompt,kind,created_at,deps",
            "state": "eq.QUEUED",
            "order": "created_at.asc",
            "limit": str(SURGE_MAX_TASKS * 3),  # overfetch to filter
        }) or []
    except Exception:
        return []

    if not tasks:
        return []

    # Score all tasks
    now = time.time()
    scored = []
    for t in tasks:
        s = _score_task(t, now)
        scored.append({
            "id": t["id"],
            "slug": t.get("slug", ""),
            "score": s,
            "priority": t.get("priority", 2),
            "kind": t.get("kind", "feature"),
            "est_tokens": EST_TOKENS_PER_TASK,
        })

    # Sort by score descending
    scored.sort(key=lambda x: x["score"], reverse=True)

    # Trim to budget
    if budget_tokens:
        trimmed = []
        running_tokens = 0
        for s in scored:
            if running_tokens + s["est_tokens"] <= budget_tokens:
                trimmed.append(s)
                running_tokens += s["est_tokens"]
        scored = trimmed
    else:
        scored = scored[:SURGE_MAX_TASKS]

    return scored


def save_surge_plan(plan=None):
    """Save the surge plan to DB for runner consumption."""
    if plan is None:
        plan = plan_surge()

    if not plan:
        return {"saved": False, "reason": "empty plan"}

    payload = {
        "plan": plan,
        "created_at": time.time(),
        "task_count": len(plan),
        "total_est_tokens": sum(t["est_tokens"] for t in plan),
    }

    try:
        os.makedirs(_STATE_DIR, exist_ok=True)
        json.dump(payload, open(os.path.join(_STATE_DIR, "surge_plan.json"), "w"), default=str)
        return {"saved": True, "tasks": len(plan)}
    except Exception as e:
        return {"saved": False, "error": str(e)[:100]}


def get_surge_queue():
    """Get the current surge plan's task IDs in priority order.

    Runner calls this before default polling. If a surge plan exists
    and is <SURGE_WINDOW_H old, return task IDs in surge order.
    Otherwise return empty list (use default queue).
    """
    try:
        payload = json.load(open(os.path.join(_STATE_DIR, "surge_plan.json")))
        created = payload.get("created_at", 0)
        if time.time() - created > SURGE_WINDOW_H * 3600:
            return []  # plan expired
        return [t["id"] for t in payload.get("plan", [])]
    except Exception:
        return []


def run():
    """Periodic: refresh surge plan and report."""
    plan = plan_surge()
    if plan:
        result = save_surge_plan(plan)
        total_tokens = sum(t["est_tokens"] for t in plan)
        top3 = ", ".join(t.get("slug", t["id"][:8]) for t in plan[:3])
        print(f"[surge] planned {len(plan)} tasks ({total_tokens} est tokens), "
              f"top: {top3}")
    else:
        print("[surge] no queued tasks for surge planning")


if __name__ == "__main__":
    run()
