#!/usr/bin/env python3
"""
preview_canary.py — instant canary via Vercel preview deployments.

After a branch is merged to orchestrator/dev, Vercel creates a preview
deployment automatically.  This module queries that preview deployment
immediately and records the result as an early-green/early-red signal —
before the full production release cycle runs — giving the orchestrator
instant feedback on whether the build will succeed.

Env vars (never hardcoded):
  VERCEL_TOKEN    — required; Vercel personal or team API token
  VERCEL_TEAM_ID  — optional; required for team-scoped projects
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

VBASE = "https://api.vercel.com"
READY = {"READY"}
FAILED = {"ERROR", "CANCELED", "FAILED"}


def _vget(path):
    tok = os.environ.get("VERCEL_TOKEN", "").strip()
    if not tok:
        return None
    req = urllib.request.Request(VBASE + path, headers={"Authorization": f"Bearer {tok}"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            print(f"preview_canary: Vercel auth failed ({e.code}); set VERCEL_TOKEN")
            return None
        raise


def query_preview(vercel_project, branch):
    """Return the latest preview deployment dict for *branch*, or None."""
    team = os.environ.get("VERCEL_TEAM_ID", "")
    qs = {"app": vercel_project, "target": "preview", "limit": "10"}
    if team:
        qs["teamId"] = team
    data = _vget("/v6/deployments?" + urllib.parse.urlencode(qs)) or {}
    deps = data.get("deployments") or []
    for dep in deps:
        meta = dep.get("meta") or {}
        ref = meta.get("githubCommitRef") or meta.get("gitBranch") or ""
        if ref == branch or ref.endswith(f"/{branch}"):
            return dep
    return None


def _preview_state(dep):
    if not dep:
        return None
    return dep.get("state") or dep.get("readyState")


def run():
    """Poll preview deployments for recently-merged dev branches; record results."""
    if not os.environ.get("VERCEL_TOKEN", "").strip():
        print("preview_canary: VERCEL_TOKEN unset; skipping")
        return {"checked": 0}

    health_rows = db.select("deploy_health", {"select": "app,vercel_project,git_branch"}) or []
    checked = 0
    for row in health_rows:
        vproj = row.get("vercel_project")
        branch = row.get("git_branch") or "orchestrator/dev"
        app = row.get("app")
        if not vproj or not app:
            continue
        dep = query_preview(vproj, branch)
        state = _preview_state(dep)
        if not state:
            continue
        checked += 1
        if state in READY:
            print(f"preview_canary: {app} preview READY ({dep.get('url')})")
            try:
                db.update("deploy_health", {"app": app},
                          {"preview_state": "ready", "preview_url": dep.get("url")})
            except Exception:
                pass
        elif state in FAILED:
            print(f"preview_canary: {app} preview {state} — flagging for review")
            try:
                title = f"Preview build failed: {app}"
                ex = db.select("approvals", {"select": "id", "project": f"eq.{app}",
                                             "status": "eq.pending",
                                             "title": f"eq.{title}"}) or []
                if not ex:
                    db.insert("approvals", {
                        "project": app, "kind": "proposal", "title": title,
                        "why": (f"Vercel preview deployment for branch `{branch}` "
                                f"returned state `{state}`. Fix the build before "
                                "the production release train runs."),
                        "value": "Catch build failures early — before the production release cycle.",
                        "risk": "Low; production is unaffected. Preview deployment only.",
                        "command": f"Check Vercel project `{vproj}` preview logs.",
                    })
                db.update("deploy_health", {"app": app},
                          {"preview_state": state.lower()})
            except Exception:
                pass

    print(f"preview_canary: checked {checked} preview deployments")
    return {"checked": checked}


if __name__ == "__main__":
    print(run())
