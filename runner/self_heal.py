#!/usr/bin/env python3
"""
self_heal.py - turn production incidents into fixes automatically. Reads the `incidents` feed (any app
posts error/uptime/latency/cost signals) and, for unfixed ones, files a TOP-PRIORITY fix task that flows
through the same gated+judged pipeline (so a regression auto-repairs itself, gated by tests + AI review).
Crit incidents also ping you via approval_push. Schedule every few minutes.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db


def run():
    """Scan unfixed incidents and file top-priority fix tasks for each."""
    inc = db.select("incidents", {"select": "*", "fixed": "eq.false", "limit": "50"}) or []
    projs = {p["name"]: p for p in (db.select("projects", {"select": "id,name"}) or [])}
    filed = 0
    for i in inc:
        app = i.get("app"); p = projs.get(app)
        if not p:
            continue
        slug = f"heal-{i['signal']}-{str(i['id'])[:8]}"
        # top priority: prepend so claim_task picks it first (priority band handled by project)
        db.insert("tasks", {"project_id": p["id"], "slug": slug, "state": "QUEUED", "kind": "fix",
            "prompt": f"PRODUCTION INCIDENT ({i.get('severity')}/{i.get('signal')}): {i.get('detail')}. "
                      f"Diagnose and fix with a minimal, well-tested change. Add a regression test.",
            "deps": [], "base_branch": "main", "material": False,
            "note": f"auto-filed from incident {i['id']}"})
        db.update("incidents", {"id": i["id"]}, {"fix_task": None, "fixed": None})  # mark in-progress
        db.update("incidents", {"id": i["id"]}, {"detail": (i.get("detail") or "") + " [fix queued]"})
        if i.get("severity") == "crit":
            db.insert("approvals", {"project": app, "kind": "self",
                "title": f"CRIT incident auto-fix queued: {app}/{i.get('signal')}",
                "why": (i.get("detail") or "")[:240], "value": "Self-healing fix is in the pipeline.",
                "risk": "Monitor — fix ships through tests + AI review.", "command": ""})
        filed += 1
    print(f"self_heal: filed {filed} incident fix task(s)")
    return filed


if __name__ == "__main__":
    run()
