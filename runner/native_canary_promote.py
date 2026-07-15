#!/usr/bin/env python3
"""Promote one proven native canary without scanning unrelated integration cards."""
from __future__ import annotations
import json,os
import db,merge_train,repo_lock
def run(task_id):
    rows=db.select("tasks",{"select":"*","id":f"eq.{task_id}","limit":"1"}) or []
    if not rows:return {"ok":False,"reason":"task missing"}
    task=rows[0]; projects=db.select("projects",{"select":"*","id":f"eq.{task['project_id']}","limit":"1"}) or []
    cards=db.select("approvals",{"select":"*","slug":f"eq.{task['slug']}","kind":"eq.integrate","status":"eq.approved","order":"created_at.desc","limit":"1"}) or []
    if not projects or not cards:return {"ok":False,"reason":"project or integration card missing"}
    repo=db.localize_repo_path(projects[0].get("repo_path",""))
    with repo_lock.hold(repo,timeout=1) as locked:
        if not locked:return {"ok":False,"reason":"repo busy; retry safely"}
        outcome=merge_train._integrate_card(cards[0],task["slug"],task,projects[0])
    return {"ok":outcome=="merged","outcome":outcome,"task_id":task_id}
if __name__=="__main__":
    print(json.dumps(run(os.environ.get("ORCH_NATIVE_CANARY_TASK","")),default=str))
