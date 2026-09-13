#!/usr/bin/env python3
"""db_deploy_gate.py — database posture as a deployment signal, direct on the project's repo.

WHY. The steering loop knows, continuously and for free, which production databases have open
high-severity gaps or live-vs-repo migration drift. A Vercel deploy of a project with a 56-second
query class or anon-writable client-data tables should not roll out silently. This module turns
that posture into a GitHub commit status (context `db-steering/posture`) on the head commit of
the project's base branch and on the sha of the latest Vercel production deployment — surfaces
that exist DIRECTLY on the project's repo, readable by Vercel's "Ignored Build Step" or GitHub
required-check rules, no orchestrator in the deploy path.

GATE RULES (deliberately narrow — a gate that cries wolf gets un-required):
  FAIL  when the project has any open HIGH finding in a security category, or open
        schema_drift_live_ahead drift (live schema is ahead of the repo — the repo no longer
        describes production).
  WARN  (state=success + description) when only medium/low findings are open. Never blocks.

Nothing here mutates a deployment or blocks Vercel from our side; the veto lives in the
project's own checks configuration, where it can be seen and owned.

Fail-soft: no token, no network, unknown repo -> decision evaluated and returned with
posted=False; the gate never wedges a loop cycle.

KNOBS:
  ORCH_DB_DEPLOY_GATE     "1" posts commit statuses live (default "0": evaluate + report only)
  ORCH_DB_DEPLOY_GATE_MAX projects evaluated per cycle (default "10")
  VERCEL_TOKEN            Vercel API (deployment lookup)
  GITHUB_APP_* / PAT      via gh_auth for commit statuses
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db  # noqa: E402
import db_remediate  # noqa: E402 — shared _http/_gh/repo resolution helpers

ENABLED = os.environ.get("ORCH_DB_DEPLOY_GATE", "0") == "1"
MAX_PROJECTS = int(os.environ.get("ORCH_DB_DEPLOY_GATE_MAX", "10"))
CONTEXT = "db-steering/posture"
SECURITY_CATEGORIES = ("security",)
DRIFT_BLOCKERS = ("schema_drift_live_ahead",)


def evaluate(project):
    """{ok, state, description, reasons[], counts} for one project — pure given db reads."""
    name = str(project.get("name") or "")
    reasons, counts = [], {"high_security": 0, "drift_live_ahead": 0, "medium_open": 0}

    def _count(params):
        try:
            n = db.count("db_findings", params)
            return int(n) if n is not None else 0
        except Exception:
            return 0  # an unreachable control plane must not block deploys

    counts["high_security"] = _count({
        "project": "eq.%s" % name, "status": "eq.open", "severity": "eq.high",
        "category": "in.(%s)" % ",".join(SECURITY_CATEGORIES)})
    counts["drift_live_ahead"] = _count({
        "project": "eq.%s" % name, "status": "eq.open", "probe_id": "eq.schema_drift_live_ahead"})
    counts["medium_open"] = _count({
        "project": "eq.%s" % name, "status": "eq.open", "severity": "in.(medium,low)"})
    if counts["high_security"]:
        reasons.append("%d open high-severity security finding(s)" % counts["high_security"])
    if counts["drift_live_ahead"]:
        reasons.append("live schema ahead of repo migrations (%d)" % counts["drift_live_ahead"])
    ok = not reasons
    desc = ("posture ok (%d medium/low open)" % counts["medium_open"]) if ok \
        else "; ".join(reasons)[:140]
    return {"project": name, "ok": ok, "state": "success" if ok else "failure",
            "description": desc, "reasons": reasons, "counts": counts}


def _vercel_latest_sha(vercel_project):
    """(sha, state, url) of the latest production deployment, fail-soft empties."""
    token = os.environ.get("VERCEL_TOKEN", "")
    if not (vercel_project and token):
        return "", "", ""
    res = db_remediate._http("GET", "%s/v6/deployments?projectId=%s&target=production&limit=1"
                             % (db_remediate.VERCEL_API, vercel_project), token)
    deps = (res or {}).get("deployments") or []
    if not deps:
        return "", "", ""
    d = deps[0]
    meta = d.get("meta") or {}
    sha = str(meta.get("githubCommitSha") or meta.get("commitSha") or "")
    return sha, str(d.get("state") or d.get("readyState") or ""), str(d.get("url") or "")


#: The fallback channel when the GitHub App lacks `Commit statuses: write` (403): one marked
#: commit comment per sha, PATCHed in place on a state change — visibility without spam.
COMMENT_MARKER = "<!-- db-steering/posture -->"


def _comment_upsert(repo, sha, decision, target_url=""):
    comments = db_remediate._gh("GET", "/repos/%s/commits/%s/comments?per_page=100" % (repo, sha))
    mine = [c for c in (comments if isinstance(comments, list) else [])
            if COMMENT_MARKER in str(c.get("body") or "")]
    body = ("%s %s: **%s** — %s\n\nDatabase Steering posture gate (read-only review).%s"
            % (COMMENT_MARKER, CONTEXT, decision["state"], decision["description"],
               " " + target_url if target_url else ""))
    if mine:
        last = mine[-1]
        if str(last.get("body") or "").splitlines()[0] == body.splitlines()[0]:
            return True  # state unchanged since the last word on this sha
        res = db_remediate._gh("PATCH", "/repos/%s/comments/%s" % (repo, last.get("id")), {"body": body})
    else:
        res = db_remediate._gh("POST", "/repos/%s/commits/%s/comments" % (repo, sha), {"body": body})
    return isinstance(res, dict) and not res.get("_http_error")


def post_status(repo, sha, decision, target_url=""):
    """failure|success on db-steering/posture for `sha`; falls back to a marked commit
    comment when the App has contents:write but not statuses:write. Fail-soft False."""
    if not (repo and sha):
        return False
    res = db_remediate._gh("POST", "/repos/%s/statuses/%s" % (repo, sha), {
        "state": decision["state"], "context": CONTEXT,
        "description": decision["description"],
        "target_url": target_url or None})
    if isinstance(res, dict) and not res.get("_http_error"):
        return True
    if isinstance(res, dict) and res.get("_http_error") == 403:
        return _comment_upsert(repo, sha, decision, target_url=target_url)
    return False


def check_project(project_row):
    """Evaluate one project and, when enabled, post the status to its latest deployed sha and
    to the head of its base branch. Returns a summary dict; never raises."""
    name = str(project_row.get("name") or "")
    decision = evaluate(project_row)
    out = dict(decision)
    out.update({"posted": False})
    if not ENABLED:
        out["mode"] = "evaluate-only (ORCH_DB_DEPLOY_GATE=0)"
        return out
    try:
        repo = db_remediate.repo_for_project(project_row)
        sha, vstate, vurl = _vercel_latest_sha(str(project_row.get("vercel_project") or ""))
        posted = []
        if sha:
            posted.append(("deployment", post_status(repo, sha, decision, vurl)))
        base = str(project_row.get("prod_branch") or project_row.get("default_base")
                   or project_row.get("staging_branch") or "")
        if base:
            ref = db_remediate._gh("GET", "/repos/%s/git/ref/heads/%s" % (repo, base)) if repo else {}
            head = str((ref or {}).get("object", {}).get("sha") or "")
            if head:
                posted.append(("base-head", post_status(repo, head, decision, vurl)))
        out["posted"] = bool(posted) and all(p for _w, p in posted)
        out["vercel_state"] = vstate
    except Exception as e:
        out["error"] = "%s: %s" % (type(e).__name__, str(e)[:120])
    return out


def run_cycle(projects=None):
    """Evaluate the Vercel-linked slice of the fleet. Summary dict; never raises."""
    out = {"enabled": ENABLED, "checked": [], "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    try:
        if projects is None:
            projects = db.select("projects", {"select": "name,vercel_project,prod_branch,default_base,"
                                                        "staging_branch,repo_path,superseded_by"}) or []
        eligible = [p for p in projects if p.get("vercel_project") and not p.get("superseded_by")
                    and not db_remediate._is_excluded(p)]
        for p in eligible[:MAX_PROJECTS]:
            try:
                out["checked"].append(check_project(p))
            except Exception as e:
                out["checked"].append({"project": p.get("name"), "ok": None,
                                       "error": "%s: %s" % (type(e).__name__, str(e)[:120])})
    except Exception as e:
        out["error"] = "%s: %s" % (type(e).__name__, str(e)[:120])
    return out


if __name__ == "__main__":
    import json
    print(json.dumps(run_cycle(), indent=2, default=str))
