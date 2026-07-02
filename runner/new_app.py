#!/usr/bin/env python3
"""
new_app.py - one-command new product. Given a name + one-paragraph goal (row in app_requests, or CLI),
it registers a project and seeds a contracts-first plan so the swarm scaffolds repo/schema/deploy/SPEC
and the first tasks — spinning up app #11 becomes a sentence. Repo creation + deploy are operator steps
(filed as action items with drafts); everything else the swarm builds through the gated pipeline.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db


def create(name, goal, repo_path=None):
    existing = db.select("projects", {"select": "id", "name": f"eq.{name}"}) or []
    if existing:
        return {"ok": False, "error": "project exists"}
    p = db.insert("projects", {"name": name, "priority": 5, "auto_merge": True,
                               "confidence_threshold": 0.5, "concurrency_weight": 1,
                               "repo_path": repo_path or ""})
    pid = p[0]["id"] if isinstance(p, list) else p["id"]
    # contracts-first seed task
    db.insert("tasks", {"project_id": pid, "slug": "contracts", "state": "QUEUED", "kind": "build",
        "prompt": f"Scaffold the new product '{name}'. GOAL: {goal}\nDefine the shared contracts: data "
                  f"model, key API signatures, and the SPEC.md invariants. Implementation comes in later "
                  f"tasks that depend on this one.", "deps": [], "base_branch": "main"})
    # operator action items for the parts only the owner can do
    for title, why in [
        (f"[operator] Create the git repo + Vercel project for '{name}'",
         f"New product '{name}'. Create the repo and link a Vercel project, then set its repo_path in projects."),
        (f"[operator] Provision '{name}' Supabase/DB + env",
         f"Create the database/env for '{name}' and add its keys to the deploy env."),
    ]:
        db.insert("approvals", {"project": name, "kind": "operator", "title": title, "why": why,
                  "value": "Stand up infra for the new product.", "risk": "Operator step.", "command": ""})
    print(f"new_app: registered '{name}' + seeded contracts plan + 2 operator items")
    return {"ok": True, "project": name, "project_id": pid}


def run():
    """Process any queued app_requests rows."""
    reqs = db.select("app_requests", {"select": "*", "status": "eq.requested", "limit": "10"}) or []
    made = 0
    for r in reqs:
        res = create(r.get("name"), r.get("goal"))
        db.update("app_requests", {"id": r["id"]},
                  {"status": "created" if res.get("ok") else "error"})
        if res.get("ok"):
            made += 1
    if not reqs:
        print("new_app: no pending app requests")
    return made


if __name__ == "__main__":
    if len(sys.argv) >= 3:
        print(create(sys.argv[1], " ".join(sys.argv[2:])))
    else:
        run()
