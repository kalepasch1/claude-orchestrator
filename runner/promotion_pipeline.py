#!/usr/bin/env python3
"""
promotion_pipeline.py — promote a preview deployment to prod, or roll back.

Wires into Vercel deployments: promotes a preview URL to the production alias,
or rolls back to a known-good revision.

Env vars (never hardcoded):
  VERCEL_TOKEN       — required; Vercel API token
  VERCEL_TEAM_ID     — optional; required for team-scoped projects
  VERCEL_PROJECT_ID  — optional; looked up from project name if not set
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

VBASE = "https://api.vercel.com"


def _vreq(method, path, body=None):
    """Make a Vercel API request. Returns parsed JSON or None."""
    tok = os.environ.get("VERCEL_TOKEN", "").strip()
    if not tok:
        return None
    headers = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}
    data = json.dumps(body).encode() if body else None
    team = os.environ.get("VERCEL_TEAM_ID", "").strip()
    sep = "&" if "?" in path else "?"
    if team and "teamId" not in path:
        path = f"{path}{sep}teamId={team}"
    req = urllib.request.Request(VBASE + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        body_txt = e.read().decode() if e.fp else ""
        print(f"promotion_pipeline: Vercel {method} {path} → {e.code}: {body_txt[:300]}")
        return None
    except Exception as e:
        print(f"promotion_pipeline: Vercel request error: {e}")
        return None


def _find_deployment(preview_url):
    """Resolve a preview URL to a Vercel deployment dict."""
    # Strip protocol, extract deployment host
    host = preview_url.replace("https://", "").replace("http://", "").split("/")[0]
    data = _vreq("GET", f"/v13/deployments?url={urllib.parse.quote(host)}&limit=1")
    if not data:
        return None
    deps = data.get("deployments") or []
    return deps[0] if deps else None


def promote_to_prod(preview_url, prod_url=None):
    """Promote a preview deployment to production.

    Args:
        preview_url: URL of the preview deployment.
        prod_url: production URL (informational; promotion uses Vercel's promote API).

    Returns:
        {"success": bool, "error"?: str, "deployment_id"?: str}
    """
    if not preview_url:
        return {"success": False, "error": "no preview_url provided"}

    dep = _find_deployment(preview_url)
    if not dep:
        return {"success": False, "error": f"deployment not found for {preview_url}"}

    dep_id = dep.get("uid") or dep.get("id")
    project_id = dep.get("projectId", "")
    if not dep_id:
        return {"success": False, "error": "deployment has no uid"}

    # Vercel promote: create an alias-based promotion
    result = _vreq("POST", f"/v10/projects/{project_id}/promote/{dep_id}")
    if result is None:
        return {"success": False, "error": "Vercel promote API call failed",
                "deployment_id": dep_id}

    return {"success": True, "deployment_id": dep_id,
            "project_id": project_id}


def rollback_prod(revision_id):
    """Roll back production to a previous deployment.

    Args:
        revision_id: Vercel deployment ID to roll back to.

    Returns:
        {"success": bool, "error"?: str}
    """
    if not revision_id:
        return {"success": False, "error": "no revision_id provided"}

    # Find the deployment to get project ID
    dep = _vreq("GET", f"/v13/deployments/{revision_id}")
    if not dep:
        return {"success": False, "error": f"deployment {revision_id} not found"}

    project_id = dep.get("projectId", "")
    if not project_id:
        return {"success": False, "error": "deployment has no projectId"}

    result = _vreq("POST", f"/v10/projects/{project_id}/promote/{revision_id}")
    if result is None:
        return {"success": False, "error": "Vercel rollback API call failed"}

    return {"success": True, "rolled_back_to": revision_id}


def get_prod_deployment(vercel_project):
    """Get the current production deployment for a project (for rollback reference)."""
    data = _vreq("GET", f"/v6/deployments?app={urllib.parse.quote(vercel_project)}"
                 f"&target=production&limit=1")
    if not data:
        return None
    deps = data.get("deployments") or []
    return deps[0] if deps else None
