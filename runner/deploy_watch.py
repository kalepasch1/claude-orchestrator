#!/usr/bin/env python3
"""
deploy_watch.py — closes the observability loop the orchestrator was missing.

Registered as the 'deploy_watch' loop. For every app with a Vercel project, it polls the latest
PRODUCTION deployment via the Vercel API, records the state in deploy_health, then refreshes the
"merged-but-not-deployed" alarms. This is what confirms the orchestrator's whole point end-to-end:
improved -> merged -> pushed -> DEPLOYED. If a merge lands but no deploy follows (e.g. push disabled,
build red), the alarm fires and a review card is created instead of failing silently.

Env: VERCEL_TOKEN (required), VERCEL_TEAM_ID (for team-scoped projects). Fail-soft without them.
"""
import os, sys, json, urllib.request, urllib.parse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

TOKEN = os.environ.get("VERCEL_TOKEN")
TEAM = os.environ.get("VERCEL_TEAM_ID")


def _latest_prod(project):
    qs = {"app": project, "target": "production", "limit": "1"}
    if TEAM:
        qs["teamId"] = TEAM
    url = "https://api.vercel.com/v6/deployments?" + urllib.parse.urlencode(qs)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {TOKEN}"})
    data = json.loads(urllib.request.urlopen(req, timeout=20).read())
    deps = data.get("deployments") or []
    if not deps:
        return None
    d = deps[0]
    return {"state": d.get("state") or d.get("readyState"),
            "at": d.get("created"), "sha": (d.get("meta") or {}).get("githubCommitSha")}


def run():
    if not TOKEN:
        print("deploy_watch: VERCEL_TOKEN unset; skipping"); return
    rows = db.select("deploy_health", {"select": "app,vercel_project"}) or []
    seen = 0
    for r in rows:
        proj = r.get("vercel_project")
        if not proj:
            continue
        try:
            d = _latest_prod(proj)
            if d:
                # created is epoch ms; store as ISO via SQL now-ish fallback handled server-side
                db.rpc("record_deploy", {"p_app": r["app"], "p_state": d["state"], "p_sha": d.get("sha")})
                seen += 1
        except Exception as e:
            print(f"deploy_watch {r['app']}: {e}")
    try:
        db.rpc("refresh_deploy_alarms", {})
        alarms = db.select("deploy_health", {"select": "app", "alarm": "eq.true"}) or []
        for a in alarms:
            # one review card per alarmed app (idempotent-ish: skip if a recent open one exists)
            ex = db.select("approvals", {"select": "id", "project": f"eq.{a['app']}",
                                        "status": "eq.pending", "title": "ilike.*deploy alarm*"}) or []
            if not ex:
                db.insert("approvals", {"project": a["app"], "kind": "proposal",
                    "title": f"Deploy alarm: {a['app']} merged but not deployed",
                    "why": "A merge landed but Vercel has no matching successful production deploy. Check push + build."})
    except Exception as e:
        print(f"deploy_watch alarms: {e}")
    print(f"deploy_watch: polled {seen} projects")


if __name__ == "__main__":
    run()
