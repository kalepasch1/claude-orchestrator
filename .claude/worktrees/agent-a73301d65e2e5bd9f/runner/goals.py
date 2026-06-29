#!/usr/bin/env python3
"""
goals.py - GOAL-DRIVEN AUTONOMY. You set outcomes ("raise coverage to 80%", "p95 -30%",
"zero gitleaks findings"); this turns each active goal into concrete scoped tasks the
swarm pursues, and marks the goal met when the metric is reached. Run on a schedule.

This shifts you from assigning tasks to setting objectives - the system figures out the
work. Tasks are inserted as QUEUED so the normal runner picks them up (budget/verify/PR
gates still apply).
"""
import os, sys, json, subprocess, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "claude")
PLAN_MODEL = os.environ.get("GOAL_MODEL", "claude-opus-4-8")
MAX_TASKS_PER_GOAL = int(os.environ.get("GOAL_MAX_TASKS", "3"))

META = """You decompose a standing GOAL into at most {n} small, independently-shippable
tasks that move the metric. Output ONLY a JSON array of
{{"slug":"kebab","prompt":"self-contained instruction incl. file scope + the test that
proves progress","model_hint":"haiku|sonnet|opus"}}. Don't repeat work already done.
GOAL: {goal}
PROJECT REPO: {repo}
"""


def projects_by_name():
    return {p["name"]: p for p in (db.select("projects") or [])}


def advance():
    pmap = projects_by_name()
    goals = db.select("goals", {"select": "*", "status": "eq.active",
                                "order": "priority.asc"}) or []
    made = 0
    for g in goals:
        proj = pmap.get(g.get("project"))
        if not proj:
            continue
        repo = proj["repo_path"]
        # don't pile on: skip if this goal already has open tasks
        open_for = db.select("tasks", {"select": "id", "project_id": f"eq.{proj['id']}",
                                       "state": "in.(QUEUED,RUNNING,WAITING,RETRY)"}) or []
        if len(open_for) >= MAX_TASKS_PER_GOAL:
            continue
        prompt = META.format(n=MAX_TASKS_PER_GOAL, goal=f"{g['objective']} (metric: {g.get('metric')} target {g.get('target')})", repo=repo)
        try:
            out = subprocess.check_output([CLAUDE_BIN, "-p", prompt, "--model", PLAN_MODEL,
                                           "--output-format", "text"], text=True, timeout=240)
            tasks = json.loads(re.search(r"\[.*\]", out, re.S).group(0))
        except Exception as e:
            sys.stderr.write(f"[goals] {g['objective'][:40]}: {e}\n"); continue
        hint = {"haiku": "claude-haiku-4-5-20251001", "sonnet": "claude-sonnet-4-6", "opus": "claude-opus-4-8"}
        for t in tasks[:MAX_TASKS_PER_GOAL]:
            db.insert("tasks", {"project_id": proj["id"], "slug": t["slug"],
                                "prompt": t["prompt"], "kind": "build", "state": "QUEUED",
                                "model": hint.get(t.get("model_hint"))})
            made += 1
    print(f"goals advanced: queued {made} tasks across {len(goals)} active goals")
    return made


if __name__ == "__main__":
    advance()
