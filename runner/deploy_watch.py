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
import os, sys, json, datetime, urllib.request, urllib.parse, urllib.error
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

TOKEN = os.environ.get("VERCEL_TOKEN")
TEAM = os.environ.get("VERCEL_TEAM_ID")
RED_ALERT_HOURS = int(os.environ.get("ORCH_DEPLOY_RED_ALERT_HOURS", "6"))


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
            "at": d.get("created"), "sha": (d.get("meta") or {}).get("githubCommitSha"),
            "url": d.get("url"), "id": d.get("uid") or d.get("id")}


def _ensure_project_mapping(app, vercel_project):
    if not app or not vercel_project:
        return
    try:
        db.update("projects", {"name": app}, {"vercel_project": vercel_project})
    except Exception:
        pass


def _file_watch_issue(app, vercel_project, error):
    try:
        title = f"Deploy watch error: {app}"
        auth_hint = ""
        if isinstance(error, urllib.error.HTTPError) and error.code in (401, 403):
            auth_hint = " The Vercel token is rejected by the API or lacks access to the team/project; set a valid VERCEL_TOKEN and VERCEL_TEAM_ID when applicable."
        ex = db.select("approvals", {"select": "id", "project": f"eq.{app}",
                                    "status": "eq.pending", "title": f"eq.{title}"}) or []
        why = f"Vercel project `{vercel_project}` could not be polled: {str(error)[:500]}.{auth_hint}"
        if ex:
            try:
                db.update("approvals", {"id": ex[0]["id"]}, {"why": why})
            except Exception:
                pass
            return
        db.insert("approvals", {"project": app, "kind": "proposal", "title": title,
                  "why": why,
                  "value": "Fix Vercel project slug/token/team mapping so deploy verification works across the fleet.",
                  "risk": "Deploys may be green or red, but the orchestrator cannot currently prove it."})
    except Exception:
        pass


def _escalate_error_apps():
    """File ops cards and auto-queue deployfix tasks for apps stuck in ERROR beyond threshold."""
    try:
        rows = db.select("deploy_health", {
            "select": "app,last_deploy_state,updated_at",
            "last_deploy_state": "eq.ERROR",
        }) or []
        now = datetime.datetime.now(datetime.timezone.utc)
        today = now.strftime("%Y%m%d")
        for r in rows:
            app = r.get("app")
            if not app:
                continue
            updated = r.get("updated_at")
            if not updated:
                continue
            if isinstance(updated, str):
                updated = updated.replace("Z", "+00:00")
                try:
                    updated = datetime.datetime.fromisoformat(updated)
                except (ValueError, TypeError):
                    continue
            if updated.tzinfo is None:
                updated = updated.replace(tzinfo=datetime.timezone.utc)
            age_hours = (now - updated).total_seconds() / 3600
            if age_hours < RED_ALERT_HOURS:
                continue
            # Ops card (dedupe by title)
            title = f"Deploy ERROR red alert: {app}"
            ex = db.select("approvals", {"select": "id", "project": f"eq.{app}",
                                         "status": "eq.pending", "title": f"eq.{title}"}) or []
            if not ex:
                db.insert("approvals", {
                    "project": app, "kind": "ops",
                    "title": title,
                    "why": f"{app} has been in deploy ERROR state for {age_hours:.1f}h (threshold: {RED_ALERT_HOURS}h). Immediate investigation required.",
                    "value": f"Check Vercel build logs and recent commits for {app}.",
                    "risk": "Production may be down or serving stale code.",
                })
            # Auto-queue deployfix task (dedupe by slug)
            slug = f"deployfix-{app}-{today}"
            ex_task = db.select("tasks", {"select": "id", "slug": f"eq.{slug}"}) or []
            if not ex_task:
                proj = db.select("projects", {"select": "id", "name": f"eq.{app}"}) or []
                if proj:
                    db.insert("tasks", {
                        "slug": slug,
                        "project_id": proj[0]["id"],
                        "kind": "bugfix",
                        "state": "QUEUED",
                        "prompt": f"Deploy for {app} has been in ERROR for {age_hours:.1f}h. Investigate the Vercel build logs, identify the failing build, and fix the deployment. Check recent commits for breaking changes.",
                        "base_branch": "main",
                    })
                    print(f"deploy_watch: auto-queued {slug}")
    except Exception as e:
        print(f"deploy_watch escalate: {e}")


def run():
    try:
        import fleet_deploy_doctor
        fleet_deploy_doctor.run(file_cards=True)
    except Exception as e:
        print(f"deploy_watch binding audit: {e}")
    if not TOKEN:
        print("deploy_watch: VERCEL_TOKEN unset; skipping"); return
    rows = db.select("deploy_health", {"select": "app,vercel_project"}) or []
    seen = 0
    for r in rows:
        proj = r.get("vercel_project")
        if not proj:
            continue
        _ensure_project_mapping(r.get("app"), proj)
        try:
            d = _latest_prod(proj)
            if d:
                # created is epoch ms; store as ISO via SQL now-ish fallback handled server-side
                db.rpc("record_deploy", {"p_app": r["app"], "p_state": d["state"], "p_sha": d.get("sha")})
                seen += 1
        except Exception as e:
            print(f"deploy_watch {r['app']}: {e}")
            _file_watch_issue(r.get("app"), proj, e)
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
    _escalate_error_apps()
    print(f"deploy_watch: polled {seen} projects")


if __name__ == "__main__":
    run()
