#!/usr/bin/env python3
"""
deploy_verify.py - confirms Vercel production deploys and rolls back bad ones.

After release_train pushes a production branch, this polls the matching Vercel
deployment for that release commit:
  * READY -> mark release deployed and record the commit as last-good.
  * ERROR/CANCELED/stuck-unconfirmed -> queue a deploy-fix task, restore git to
    last-good when possible, and file an approvals card.

Vercel keeps the previous successful deployment serving until a new one is
READY, so rollback mainly restores git to the known-good state for the next
release attempt.
"""
import datetime
import json
import os
import subprocess
import sys
import urllib.parse
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

VBASE = "https://api.vercel.com"
TERMINAL_GOOD = {"READY"}
TERMINAL_BAD = {"ERROR", "CANCELED", "FAILED"}


def _ignored_build_cancel(deployment):
    """Vercel uses CANCELED for a successful Ignored Build Step decision."""
    deployment = deployment or {}
    state = deployment.get("state") or deployment.get("readyState")
    message = " ".join(str(deployment.get(key) or "")
                       for key in ("errorCode", "errorMessage"))
    return state == "CANCELED" and "ignored build step" in message.lower()


class VercelAuthError(RuntimeError):
    pass


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
            raise VercelAuthError(f"Vercel API auth failed ({e.code})")
        raise


def _deploy_health_map():
    out = {}
    try:
        for row in db.select("deploy_health", {"select": "app,vercel_project,git_branch"}) or []:
            if row.get("app"):
                out[row["app"]] = row
    except Exception:
        pass
    return out


def _vercel_project(project, project_row=None, health=None):
    """Resolve Vercel project slug/id from canonical deploy_health first."""
    project_row = project_row or {}
    health = health if health is not None else _deploy_health_map()
    h = health.get(project) or {}
    return h.get("vercel_project") or project_row.get("vercel_project") or project


def _latest_deploy(vercel_project, sha=None):
    """Return matching production deployment, preferring the release commit SHA."""
    try:
        team = os.environ.get("VERCEL_TEAM_ID", "")
        qs = {"app": vercel_project, "target": "production", "limit": "12"}
        if team:
            qs["teamId"] = team
        data = _vget("/v6/deployments?" + urllib.parse.urlencode(qs)) or {}
        deps = data.get("deployments") or []
        if not deps:
            return None
        if sha:
            short = str(sha)[:12]
            for dep in deps:
                meta = dep.get("meta") or {}
                dsha = meta.get("githubCommitSha") or meta.get("githubCommitRef")
                if dsha and (str(dsha) == str(sha) or str(dsha).startswith(short)):
                    return dep
        return deps[0]
    except VercelAuthError as e:
        return {"_auth_error": str(e), "state": "AUTH_ERROR"}
    except Exception as e:
        print(f"deploy_verify: vercel query failed ({e})")
        return None


def _latest_deploy_state(vercel_project, sha=None):
    """Compatibility helper: return (state, url)."""
    dep = _latest_deploy(vercel_project, sha=sha)
    if not dep:
        return None, None
    return dep.get("state") or dep.get("readyState"), dep.get("url")


def _deployment_events(deployment_id):
    if not deployment_id:
        return ""
    try:
        team = os.environ.get("VERCEL_TEAM_ID", "")
        path = f"/v2/deployments/{deployment_id}/events" + (f"?teamId={team}" if team else "")
        data = _vget(path) or {}
        events = data.get("events") or data.get("logs") or []
        lines = []
        for event in events[-80:]:
            payload = event.get("payload") if isinstance(event, dict) else None
            msg = payload.get("text") if isinstance(payload, dict) else None
            msg = msg or event.get("text") or event.get("message") or event.get("type")
            if msg:
                lines.append(str(msg))
        return "\n".join(lines)[-3000:]
    except Exception:
        return ""


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)


def _rollback(project, repo, prod, last_good):
    branch = _git(repo, "branch", "-f", prod, last_good)
    if branch.returncode != 0:
        print(f"deploy_verify: rollback branch update FAILED for {project}: {branch.stderr.strip()[:240]}")
        return False
    push_rollback = os.environ.get(
        "ORCH_PUSH_ON_ROLLBACK",
        os.environ.get("ORCH_PUSH_ON_RELEASE", "true"),
    ).lower() in ("1", "true", "yes", "on")
    if push_rollback:
        pushed = _git(repo, "push", "--force-with-lease", "origin", prod)
        if pushed.returncode != 0:
            print(f"deploy_verify: rollback push FAILED for {project}: {pushed.stderr.strip()[:240]}")
            return False
    print(f"deploy_verify: ROLLED BACK {project} {prod} -> {last_good[:8]}")
    return True


def _queue_deploy_fix(project_row, release, state, vercel_project, log_tail=""):
    try:
        if not project_row.get("id"):
            return
        existing = db.select("tasks", {"select": "slug", "project_id": f"eq.{project_row.get('id')}",
                                       "state": "in.(QUEUED,RUNNING,RETRY,BLOCKED)"}) or []
        if any(str(e.get("slug") or "").startswith("deployfix-") for e in existing):
            return
        slug = f"deployfix-{release['project']}-{datetime.datetime.utcnow().strftime('%m%d%H%M')}"
        prompt = (
            "The Vercel production deploy for this app failed or could not be confirmed. "
            "Fix the smallest build/deploy issue and make the production build pass. "
            "Do not add product features. Preserve existing behavior.\n\n"
            f"Vercel project: {vercel_project}\n"
            f"Release status: {state or 'unconfirmed'}\n"
            f"Release commit: {release.get('to_sha') or ''}\n\n"
            "# Vercel/build log tail:\n" + (log_tail or release.get("note") or "")[-3000:]
        )
        try:
            import pipeline_contract
            prompt = pipeline_contract.wrap_prompt(prompt, project=release["project"], kind="bugfix",
                                                   source="vercel-deploy-verify", slug=slug, material=False)
        except Exception:
            pass
        db.insert("tasks", {"project_id": project_row.get("id"), "slug": slug, "prompt": prompt,
                  "base_branch": project_row.get("default_base") or project_row.get("prod_branch") or "main",
                  "kind": "bugfix", "state": "QUEUED", "deps": [], "material": False,
                  "note": "auto-queued by deploy_verify Vercel failure"})
    except Exception as e:
        print(f"deploy_verify: queue deploy-fix failed for {release.get('project')}: {e}")


def _file_auth_issue(project, vercel_project, error):
    try:
        title = "Vercel auth blocked deploy verification"
        ex = db.select("approvals", {"select": "id", "project": f"eq.{project}",
                                    "status": "eq.pending", "title": f"eq.{title}"}) or []
        if ex:
            return
        db.insert("approvals", {"project": project, "kind": "operator", "title": title,
                  "why": f"Vercel project `{vercel_project}` cannot be queried: {error}. "
                         "The current VERCEL_TOKEN is rejected before project lookup.",
                  "value": "Set a valid Vercel token, and VERCEL_TEAM_ID if these projects live under a team, so deploy verification and rollback can operate.",
                  "risk": "Deploy status is unknown; no rollback was attempted because this is an auth failure, not a confirmed bad deploy.",
                  "command": "Set VERCEL_TOKEN in runner/.env; optionally set VERCEL_TEAM_ID, then rerun deploy_watch/deploy_verify."})
    except Exception:
        pass


def _age_minutes(row):
    try:
        created = datetime.datetime.fromisoformat(str(row["created_at"]).replace("Z", "+00:00"))
        return (datetime.datetime.now(datetime.timezone.utc) - created).total_seconds() / 60
    except Exception:
        return 0


def _attribute_deploy_to_outcomes(project):
    """Mark integrated outcomes for this project as deployed after a confirmed prod deploy.

    Fail-soft: if the columns don't exist yet (migration pending) the update
    will raise and we silently skip — the columns being NULL is the pre-migration state.
    """
    try:
        rows = db.select("outcomes", {
            "select": "slug",
            "project": f"eq.{project}",
            "integrated": "eq.true",
            "deployed": "is.false",
            "limit": "500",
        }) or []
        for r in rows:
            slug = r.get("slug")
            if not slug:
                continue
            try:
                db.update("outcomes", {"slug": slug, "project": project},
                          {"deployed": True, "deploy_status": "success"})
            except Exception:
                pass
    except Exception:
        pass


def run():
    pend = db.select("releases", {"select": "*", "deploy_status": "in.(building,pending,verification_blocked)",
                                  "order": "created_at.desc", "limit": "20"}) or []
    projs = {p["name"]: p for p in (db.select("projects", {"select": "*"}) or [])}
    health = _deploy_health_map()
    stuck_min = int(os.environ.get("DEPLOY_STUCK_MIN", "15"))
    for release in pend:
        project = release["project"]
        p = projs.get(project, {})
        vproj = _vercel_project(project, p, health)
        dep = _latest_deploy(vproj, sha=release.get("to_sha"))
        if (dep or {}).get("_auth_error"):
            _file_auth_issue(project, vproj, dep["_auth_error"])
            db.update("releases", {"id": release["id"]},
                      {"deploy_status": "verification_blocked",
                       "note": f"vercel auth blocked verification; no rollback attempted: {dep['_auth_error']}"})
            continue
        state = (dep or {}).get("state") or (dep or {}).get("readyState")
        url = (dep or {}).get("url")

        ignored_build = _ignored_build_cancel(dep)
        if state in TERMINAL_GOOD or ignored_build:
            note = ("provider ignored build: release contains no deployable-root changes"
                    if ignored_build else release.get("note") or "")
            db.update("releases", {"id": release["id"]},
                      {"deploy_status": "success", "vercel_url": url,
                       "deployed_at": "now()", "note": note})
            db.update("projects", {"name": project}, {"last_good_sha": release["to_sha"],
                      "vercel_project": vproj})
            _attribute_deploy_to_outcomes(project)
            print(f"deploy_verify: {project} deploy OK ({url})")
            continue

        age_min = _age_minutes(release)
        if state in TERMINAL_BAD or (state is None and age_min > stuck_min):
            log_tail = _deployment_events((dep or {}).get("uid") or (dep or {}).get("id"))
            _queue_deploy_fix(p, release, state, vproj, log_tail=log_tail)
            repo = p.get("repo_path") or ""
            last_good = p.get("last_good_sha") or release.get("from_sha")
            rollback_ok = False
            if repo and last_good and os.path.isdir(repo):
                rollback_ok = _rollback(project, repo, p.get("prod_branch") or "main", last_good)
            rollback_status = "rolled_back" if rollback_ok else "verification_blocked"
            rollback_note = "auto-rollback" if rollback_ok else "auto-rollback failed"
            db.update("releases", {"id": release["id"]}, {"deploy_status": rollback_status,
                      "note": f"{rollback_note}: state={state or 'unconfirmed'} age={age_min:.0f}m -> {(last_good or '')[:8]}"})
            db.insert("approvals", {"project": project, "kind": "self",
                      "title": f"Prod deploy {'reverted' if rollback_ok else 'rollback blocked'}: {project}",
                      "why": f"Deploy {state or 'unconfirmed'} after {age_min:.0f}m; "
                             f"{'restored last-good' if rollback_ok else 'the last-good push did not complete'}.",
                      "value": "Failing change is out of prod; a deploy-fix task was queued." if rollback_ok
                               else "Release state is explicit; operator remediation is required.",
                      "risk": "Low — Vercel keeps the previous good deployment serving." if rollback_ok
                              else "Elevated — the repository branch may still point at the rejected candidate.",
                      "command": ""})
    return len(pend)


if __name__ == "__main__":
    print("checked releases:", run())
