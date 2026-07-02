#!/usr/bin/env python3
"""
kill_switch.py - stop all (or one project's) usage/cost with one flag. The dashboard's STOP
button writes controls.paused=true; the runner checks is_paused() before claiming a task and
before any external API call, so spend halts immediately. resume() lifts it.
"""
import os, sys, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db


def is_paused(project=None):
    # LATEST decision wins per scope (rows can duplicate; old paused rows must not win).
    rows = db.select("controls", {"select": "scope,project,paused,updated_at",
                                  "order": "updated_at.desc"}) or []
    for r in rows:                       # first global row = most recent global decision
        if r["scope"] == "global":
            if r.get("paused"):
                return True
            break
    if project:
        for r in rows:
            if r["scope"] == "project" and r.get("project") == project:
                return bool(r.get("paused"))
    return False


def pause(scope="global", project=None, reason="manual stop", by="dashboard"):
    db.insert("controls", {"scope": scope, "project": project, "paused": True,
                           "reason": reason, "updated_by": by,
                           "updated_at": datetime.datetime.utcnow().isoformat()}, upsert=True)
    return f"PAUSED {scope}{'/' + project if project else ''}"


def resume(scope="global", project=None, by="dashboard"):
    db.insert("controls", {"scope": scope, "project": project, "paused": False,
                           "updated_by": by, "updated_at": datetime.datetime.utcnow().isoformat()},
              upsert=True)
    return f"RESUMED {scope}{'/' + project if project else ''}"


if __name__ == "__main__":
    import sys
    a = sys.argv[1] if len(sys.argv) > 1 else "status"
    if a == "stop":
        print(pause())
    elif a == "resume":
        print(resume())
    else:
        print("global paused:", is_paused())
