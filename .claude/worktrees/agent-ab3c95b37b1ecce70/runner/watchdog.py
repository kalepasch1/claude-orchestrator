#!/usr/bin/env python3
"""
watchdog.py - prod watchdog -> auto-fix. Polls each project's health endpoint (and,
optionally, error signals) and when something is unhealthy, files a REMEDIATION task so
the swarm turns the failure into a fix (overnight deploy window applies it). Only pings
you if it can't self-fix. This is the "issues self-remedy automatically" loop.

Config: projects table can carry a health_url via a `.orchestrator-deploy` file, or set
WATCH_HEALTH_<PROJECT>=https://... env vars. Schedule every few minutes.
"""
import os, sys, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db


def _healthy(url):
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return r.status == 200
    except Exception:
        return False


def check():
    made = 0
    for p in db.select("projects", {"select": "id,name"}) or []:
        url = os.environ.get(f"WATCH_HEALTH_{p['name'].upper().replace('-', '_')}")
        if not url:
            continue
        if _healthy(url):
            continue
        # already remediating? don't pile on
        open_fix = db.select("tasks", {"select": "id", "project_id": f"eq.{p['id']}",
                                       "slug": "eq.auto-remediate",
                                       "state": "in.(QUEUED,RUNNING,WAITING)"}) or []
        if open_fix:
            continue
        db.insert("tasks", {"project_id": p["id"], "slug": "auto-remediate", "kind": "build",
                            "state": "QUEUED",
                            "prompt": f"PRODUCTION health check failing at {url}. Diagnose from logs/recent "
                                      f"commits, write a failing reproduction test, fix until green, and prepare "
                                      f"a deploy. If you cannot fix it confidently, file an approval explaining why."})
        db.insert("approvals", {"project": p["name"], "kind": "self",
                                "title": f"Auto-remediation started for {p['name']}",
                                "why": f"Health check failing at {url}.",
                                "value": "Swarm is attempting a fix; you'll only be paged if it can't.",
                                "risk": "Watch the remediation task.", "command": ""})
        made += 1
    print(f"watchdog: queued {made} remediation task(s)")
    return made


if __name__ == "__main__":
    check()
