#!/usr/bin/env python3
"""
deploy_canary.py — synthetic end-to-end heartbeat that PROVES the orchestrator's whole point daily.

For each app with a Vercel project, if there's no canary in flight, it files a trivial, safe
"build-stamp bump" task. That task flows through the exact real pipeline — build -> verify -> merge ->
push -> Vercel deploy — and deploy_watch then confirms the deploy went green. If the canary doesn't
reach a green deploy, the deploy alarm fires. So every day, every app's full improve->deploy loop is
exercised and verified automatically. Registered as the 'deploy_canary' loop (daily).
"""
import os, sys, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

STAMP = datetime.datetime.utcnow().strftime("%Y%m%d")


def _pending_canary(app):
    rows = db.select("tasks", {"select": "id", "slug": f"eq.canary-{app}-{STAMP}"}) or []
    if rows:
        return True
    active = db.select("tasks", {"select": "id", "slug": f"like.canary-{app}-%",
                                "state": "in.(QUEUED,RUNNING,WAITING,RETRY)"}) or []
    return len(active) > 0


def run():
    apps = db.select("deploy_health", {"select": "app,vercel_project"}) or []
    filed = 0
    for a in apps:
        app = a["app"]
        if not a.get("vercel_project") or app in ("beethoven",):  # skip infra/CLI-deployed
            continue
        if _pending_canary(app):
            continue
        proj = (db.select("projects", {"select": "id", "name": f"eq.{app}"}) or [{}])[0].get("id")
        if not proj:
            continue
        db.insert("tasks", {"project_id": proj, "slug": f"canary-{app}-{STAMP}", "kind": "bugfix",
            "state": "QUEUED", "note": "deploy canary — pipeline heartbeat",
            "prompt": ("PIPELINE HEARTBEAT (canary): make a single trivial, safe change — create or update "
                       "a file `.deploy-canary` at the repo root containing the current UTC timestamp and a "
                       "one-line comment. Commit it. This exists only to exercise the full "
                       "build->verify->merge->push->Vercel-deploy loop end to end. Do NOT touch app code, "
                       "config, pricing, auth, or RLS. Must build green.")})
        db.update("deploy_health", {"app": app}, {"last_canary_at": datetime.datetime.utcnow().isoformat()})
        filed += 1
    print(f"deploy_canary: filed {filed} canary heartbeats")


if __name__ == "__main__":
    run()
