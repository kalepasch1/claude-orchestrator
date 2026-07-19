#!/usr/bin/env python3
"""
improvement_measure.py - closes the loop on the 20-500X miner: it doesn't just GENERATE ideas, it learns
which KINDS actually pay off, and biases future mining toward them.

  1. mark shipped: any improvement_proposal whose task merged -> status='shipped'.
  2. attribute: link shipped improvements to the app's revenue/usage movement (merge_revenue).
  3. surface returns: avg realized delta per SURFACE (feature/ux/api/backend/orchestration/swarm/...),
     written to surface_returns so improvement_miner can weight high-return surfaces higher next cycle.
Schedule daily. Read-only except status + the returns table.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db


def mark_shipped():
    """Distinguish merged engineering output from verified production deployment."""
    tasks = {t["slug"]: t for t in (db.select("tasks", {
        "select": "slug,state,project_id,updated_at", "state": "eq.MERGED"}) or [])}
    projects = {p["id"]: p["name"] for p in (db.select("projects", {"select": "id,name"}) or [])}
    releases = db.select("releases", {"select": "project,deploy_status,deployed_at,created_at",
                                      "deploy_status": "eq.success", "order": "created_at.desc"}) or []
    latest = {}
    for release in releases:
        latest.setdefault(release.get("project"), release)
    n = 0
    for p in db.select("improvement_proposals", {"select": "id,task_slug,status",
                                                  "status": "in.(queued,merged)"}) or []:
        task = tasks.get(p.get("task_slug"))
        if not task:
            continue
        project = projects.get(task.get("project_id"))
        release = latest.get(project) or {}
        deployed_at = str(release.get("deployed_at") or release.get("created_at") or "")
        if release and deployed_at >= str(task.get("updated_at") or ""):
            db.update("improvement_proposals", {"id": p["id"]}, {"status": "shipped"})
            n += 1
        elif p.get("status") != "merged":
            db.update("improvement_proposals", {"id": p["id"]}, {"status": "merged"})
    return n


def surface_returns():
    """avg realized revenue delta per surface (from merge_revenue joined by slug)."""
    shipped = db.select("improvement_proposals", {"select": "surface,task_slug", "status": "eq.shipped"}) or []
    rev = {r["slug"]: float(r.get("revenue_delta") or 0)
           for r in (db.select("merge_revenue", {"select": "slug,revenue_delta"}) or [])}
    agg = {}
    for p in shipped:
        d = rev.get(p.get("task_slug"))
        if d is None:
            continue
        a = agg.setdefault(p["surface"], [0.0, 0]); a[0] += d; a[1] += 1
    out = {}
    for surface, (tot, cnt) in agg.items():
        if cnt:
            avg = round(tot / cnt, 2)
            out[surface] = avg
            db.insert("surface_returns", {"surface": surface, "avg_delta": avg, "n": cnt,
                      "updated_at": "now()"}, upsert=True)
    return out


def run():
    shipped = mark_shipped()
    returns = surface_returns()
    print(f"improvement_measure: marked {shipped} shipped; surface returns -> {returns}")
    return {"shipped": shipped, "returns": returns}


if __name__ == "__main__":
    import json
    print(json.dumps(run(), indent=2, default=str))
