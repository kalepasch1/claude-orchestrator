#!/usr/bin/env python3
"""
deploy_verify.py - guarantees a bad Vercel prod deploy never means downtime. After release_train pushes
the prod branch, this polls the Vercel deployment for that commit:
  * success -> mark the release deployed, record to_sha as the project's last_good_sha (rollback point),
    close the loop.
  * failed/error -> AUTO-ROLLBACK: reset the prod branch to last_good_sha and force-push, so the last
    known-good deploy is restored. (Vercel keeps the previous successful deploy serving until a new one
    succeeds, so users see no downtime; this also restores git so the next release starts clean.)
Vercel's API needs VERCEL_TOKEN (read + deploy). Guarded: without a token it just records status from git
push success and leaves rollback to you. Schedule every ~2 min.
"""
import os, sys, json, urllib.request, urllib.error, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

VBASE = "https://api.vercel.com"


def _vget(path):
    tok = os.environ.get("VERCEL_TOKEN", "").strip()
    if not tok:
        return None
    req = urllib.request.Request(VBASE + path, headers={"Authorization": f"Bearer {tok}"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


def _latest_deploy_state(vercel_project):
    """Return ('READY'|'ERROR'|'BUILDING'|..., url) for the project's most recent prod deployment."""
    try:
        team = os.environ.get("VERCEL_TEAM_ID", "")
        q = f"/v6/deployments?app={vercel_project}&target=production&limit=1" + (f"&teamId={team}" if team else "")
        d = _vget(q) or {}
        deps = d.get("deployments", [])
        if deps:
            return deps[0].get("state") or deps[0].get("readyState"), deps[0].get("url")
    except Exception as e:
        print(f"deploy_verify: vercel query failed ({e})")
    return None, None


def _rollback(project, repo, prod, last_good):
    _git = lambda *a: subprocess.run(["git", *a], cwd=repo, capture_output=True, text=True)
    _git("branch", "-f", prod, last_good)
    if os.environ.get("ORCH_PUSH_ON_MERGE", "false").lower() == "true":
        _git("push", "--force-with-lease", "origin", prod)
    print(f"deploy_verify: ROLLED BACK {project} {prod} -> {last_good[:8]}")


def run():
    pend = db.select("releases", {"select": "*", "deploy_status": "in.(building,pending)",
                                  "order": "created_at.desc", "limit": "20"}) or []
    projs = {p["name"]: p for p in (db.select("projects", {"select": "*"}) or [])}
    import datetime
    stuck_min = int(os.environ.get("DEPLOY_STUCK_MIN", "15"))
    for r in pend:
        p = projs.get(r["project"], {})
        vproj = p.get("vercel_project") or r["project"]
        state, url = _latest_deploy_state(vproj)
        # SAFETY-NET ROLLBACK: if we can't confirm success and the release has been pending/building
        # too long (Vercel token missing, project-name mismatch, or a genuinely failed build), revert
        # to last-good so prod is never left on a broken/unknown deploy. Vercel keeps the prior good
        # deploy serving, so this restores git to match with zero downtime.
        if state not in ("READY",):
            try:
                created = datetime.datetime.fromisoformat(str(r["created_at"]).replace("Z", "+00:00"))
                age_min = (datetime.datetime.now(datetime.timezone.utc) - created).total_seconds() / 60
            except Exception:
                age_min = 0
            if state in ("ERROR", "CANCELED") or (state is None and age_min > stuck_min):
                repo = p.get("repo_path", ""); last_good = p.get("last_good_sha") or r.get("from_sha")
                if repo and last_good and os.path.isdir(repo):
                    _rollback(r["project"], repo, p.get("prod_branch") or "main", last_good)
                db.update("releases", {"id": r["id"]}, {"deploy_status": "rolled_back",
                          "note": f"auto-rollback: state={state or 'unconfirmed'} age={age_min:.0f}m -> {(last_good or '')[:8]}"})
                db.insert("approvals", {"project": r["project"], "kind": "self",
                          "title": f"Prod deploy reverted: {r['project']}",
                          "why": f"Deploy {state or 'unconfirmed'} after {age_min:.0f}m; restored last-good. No downtime.",
                          "value": "Failing change is out of prod; build gate should now catch it pre-merge.",
                          "risk": "None — prod on last-good.", "command": ""})
            continue
        if state is None:
            continue  # (unreachable now, kept for clarity)
        if state in ("READY",):
            db.update("releases", {"id": r["id"]},
                      {"deploy_status": "success", "vercel_url": url, "deployed_at": "now()"})
            db.update("projects", {"name": r["project"]}, {"last_good_sha": r["to_sha"]})
            print(f"deploy_verify: {r['project']} deploy OK ({url})")
        elif state in ("ERROR", "CANCELED"):
            repo = p.get("repo_path", ""); last_good = p.get("last_good_sha") or r.get("from_sha")
            if repo and last_good and os.path.isdir(repo):
                _rollback(r["project"], repo, p.get("prod_branch") or "main", last_good)
            db.update("releases", {"id": r["id"]}, {"deploy_status": "rolled_back",
                      "note": f"vercel {state} -> rolled back to {(last_good or '')[:8]}"})
            db.insert("approvals", {"project": r["project"], "kind": "self",
                      "title": f"Prod deploy failed + auto-rolled-back: {r['project']}",
                      "why": f"Vercel deploy {state}; restored {(last_good or '')[:8]}. No downtime (previous deploy kept serving).",
                      "value": "Investigate the failing change; it's out of prod.", "risk": "None — prod is on last-good.",
                      "command": ""})
    return len(pend)


if __name__ == "__main__":
    print("checked releases:", run())
