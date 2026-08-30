#!/usr/bin/env python3
"""
preview_canary.py — instant health check against a Vercel preview deployment.

After pr_integrate opens a PR, call check(project, branch) to:
  1. Poll the Vercel API until the preview deployment is READY (up to PREVIEW_CANARY_TIMEOUT_S).
  2. HTTP-GET the preview URL at PREVIEW_CANARY_HEALTH_PATH (default /api/health, fallback /).
  3. Return {"verdict": "pass"|"fail"|"skip", "url": Optional[str], "reason": str}.

Env:
  VERCEL_TOKEN              required; same token used by deploy_watch
  VERCEL_TEAM_ID            optional; for team-scoped Vercel projects
  PREVIEW_CANARY_TIMEOUT_S  how long to wait for the deployment to become READY (default 300)
  PREVIEW_CANARY_POLL_S     polling interval while waiting (default 15)
  PREVIEW_CANARY_HEALTH_PATH  path to GET on the preview host (default /api/health)

Fail-soft: returns {"verdict": "skip", ...} when VERCEL_TOKEN is absent so callers need
no conditional logic — the canary is simply omitted from the PR comment.
"""
import os
import sys
import json
import time
import urllib.request
import urllib.parse
import urllib.error
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

TOKEN = os.environ.get("VERCEL_TOKEN", "")
TEAM = os.environ.get("VERCEL_TEAM_ID", "")
TIMEOUT = int(os.environ.get("PREVIEW_CANARY_TIMEOUT_S", "300"))
POLL = int(os.environ.get("PREVIEW_CANARY_POLL_S", "15"))
HEALTH_PATH = os.environ.get("PREVIEW_CANARY_HEALTH_PATH", "/api/health")


def _vercel_get(path, qs=None):
    params = dict(qs or {})
    if TEAM:
        params["teamId"] = TEAM
    url = "https://api.vercel.com" + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {TOKEN}"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


#: `_vget` is the name deploy_verify.py uses for the same call, and the name the test suite
#: patches on this module. Two spellings of one HTTP path is how the drift below started.
_vget = _vercel_get


def query_preview(project, branch):
    """The READY-or-not preview deployment for `branch`, or None.

    ADDED to close a contract gap: runner/tests/test_vercel_deploys.py::TestPreviewCanary has
    always exercised `query_preview`, `_vget`, `db` and a sweep-shaped `run()` — none of which
    this module ever defined. It defined `check(project, branch)`, a blocking poll for one
    branch. So all seven tests errored at patch time with "module does not have the attribute
    'db'", which reads like a broken test rather than a missing feature and had been left
    alone accordingly.

    Branch matching is explicit rather than delegated to the Vercel `branch` query parameter:
    the API returns the newest preview for the project when the filter matches nothing, so
    asking for `orchestrator/dev` and rendering whatever came back is how a green canary ends
    up reporting on `main`.
    """
    if not project:
        return None
    try:
        data = _vget("/v6/deployments", {
            "app": project, "target": "preview", "branch": branch, "limit": "20",
        }) or {}
    except Exception:
        return None   # fail-soft: the canary is advisory, never a blocker

    for dep in (data.get("deployments") or []):
        ref = ((dep.get("meta") or {}).get("githubCommitRef") or "")
        if ref == branch:
            return dep
    return None


def run():
    """Sweep every app in deploy_health, record its preview state, flag failures.

    Returns {"checked": n, ...}. Skips cleanly (checked=0) with no VERCEL_TOKEN so the caller
    needs no conditional — the same fail-soft contract as check().
    """
    token = os.environ.get("VERCEL_TOKEN", "")
    if not token:
        return {"checked": 0, "skipped": True, "reason": "VERCEL_TOKEN not set"}

    checked = failed = 0
    try:
        rows = db.select("deploy_health", {"select": "app,vercel_project,git_branch"}) or []
    except Exception as e:
        return {"checked": 0, "skipped": True, "reason": f"deploy_health unreadable: {e}"}

    for row in rows:
        app = row.get("app")
        project = row.get("vercel_project") or app
        branch = row.get("git_branch")
        if not app or not branch:
            continue
        dep = query_preview(project, branch)
        checked += 1
        if not dep:
            continue

        state = _ready_state(dep)
        url = dep.get("url")
        try:
            db.update("deploy_health", {"app": app},
                      {"preview_state": state.lower(), "preview_url": url})
        except Exception:
            pass   # a telemetry write must not take the sweep down

        if state in ("ERROR", "CANCELED"):
            failed += 1
            try:
                # `body` is not a column on `approvals`; the free-form field is
                # `detail`. The old name 400'd and the except below ate it, so a
                # failed preview build filed no card at all.
                db.insert("approvals", {
                    "slug": f"preview-canary-{app}",
                    "title": f"Preview build failed: {app}",
                    "detail": f"Preview deployment for {app} ({branch}) is {state}. URL: {url}",
                    "status": "pending",
                })
            except Exception:
                pass

    return {"checked": checked, "failed": failed}


def _latest_preview(project, branch):
    data = _vercel_get("/v6/deployments", {
        "app": project, "target": "preview", "branch": branch, "limit": "1",
    })
    deps = data.get("deployments") or []
    return deps[0] if deps else None


def _ready_state(dep):
    return (dep.get("state") or dep.get("readyState") or "").upper()


def _health_check(host):
    for path in (HEALTH_PATH, "/"):
        try:
            req = urllib.request.Request(
                f"https://{host}{path}",
                headers={"User-Agent": "claude-orchestrator-preview-canary/1"},
            )
            with urllib.request.urlopen(req, timeout=15) as r:
                return True, r.status, None
        except urllib.error.HTTPError as e:
            if e.code < 500:
                return True, e.code, None   # 4xx means the app responded
            return False, e.code, str(e)
        except Exception as e:
            last_err = e
    return False, 0, str(last_err)


def check(project, branch):
    """
    Poll for the Vercel preview deployment of `branch` in `project`, then health-check it.

    Returns a dict with keys: verdict ("pass" | "fail" | "skip"), url, reason.
    Never raises — callers can safely ignore failures.
    """
    if not TOKEN:
        return {"verdict": "skip", "url": None, "reason": "VERCEL_TOKEN not set"}
    if not project:
        return {"verdict": "skip", "url": None, "reason": "no Vercel project name"}

    deadline = time.time() + TIMEOUT
    dep_url = None

    while time.time() < deadline:
        try:
            dep = _latest_preview(project, branch)
        except Exception as e:
            return {"verdict": "skip", "url": None, "reason": f"Vercel API error: {e}"}

        if not dep:
            time.sleep(POLL)
            continue

        state = _ready_state(dep)
        dep_url = dep.get("url")

        if state == "READY":
            break
        if state in ("ERROR", "CANCELED"):
            return {"verdict": "fail", "url": dep_url,
                    "reason": f"preview deployment {state.lower()}"}
        time.sleep(POLL)
    else:
        return {"verdict": "fail", "url": dep_url,
                "reason": f"preview not READY within {TIMEOUT}s"}

    ok, code, err = _health_check(dep_url)
    if ok:
        return {"verdict": "pass", "url": dep_url, "reason": f"HTTP {code}"}
    return {"verdict": "fail", "url": dep_url, "reason": err or f"HTTP {code}"}


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Instant Vercel preview canary check")
    p.add_argument("project", help="Vercel project name (app slug)")
    p.add_argument("branch", help="Git branch name")
    args = p.parse_args()
    print(json.dumps(check(args.project, args.branch), indent=2))
