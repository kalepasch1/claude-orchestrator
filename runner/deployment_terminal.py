#!/usr/bin/env python3
"""
deployment_terminal.py — makes DEPLOYMENT, not merge, the terminal state of a task.

WHY
---
`MERGED` was terminal. Nothing downstream checked whether the change ever reached a
user. The audit found `releases` at 2,714 failed / 90 success over 30 days (3.2%) —
`tomorrow` at 277 failed / 0 success — and *nothing changed as a result*. Production
only shipped at all because Vercel's git integration auto-deploys on push; the
orchestrator's own release path was ~97% dead and invisible.

WHAT THIS ADDS
--------------
1. A real terminal state `DEPLOYED_AND_VERIFIED`, reached only when BOTH hold:
      a) the project's production URL returns HTTP 200, AND
      b) the release commit SHA is actually live in the deployed build
         (Vercel's READY production deployment reports that exact SHA).
   Merge alone can no longer be mistaken for delivery.

2. Back-pressure: a project whose most recent release failed is BLOCKED — it stops
   accepting new work until a release goes green. Previously 2,714 failures produced
   no back-pressure at all.

3. The convergence gate: **nothing that cannot itself reach the terminal state may
   spawn children.** Decomposition/continuation must call `can_spawn_children()`
   first. This is what stops the ~10:1 fan-out amplification.

ENV FLAGS
---------
  ORCH_DEPLOY_TERMINAL_ENABLED   default ON  — promote verified tasks to DEPLOYED_AND_VERIFIED
  ORCH_RELEASE_BACKPRESSURE      default ON  — block new work for red projects
  ORCH_CONVERGENCE_GATE          default ON  — enforce the no-spawn-without-terminal rule
  ORCH_BACKPRESSURE_GRACE_MIN    default 45  — minutes a failed release may age before blocking
Set any to 0 to disable (they are safety rails, so they default ON, unlike the
self-work gates in self_work_gate.py).
"""
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

DEPLOYED_AND_VERIFIED = "DEPLOYED_AND_VERIFIED"

# Release states that mean "this project is red and must not take new work".
FAILED_RELEASE_STATES = {"failed", "error", "rolled_back", "verification_blocked", "rollback_failed"}
GOOD_RELEASE_STATES = {"success", "deployed", DEPLOYED_AND_VERIFIED.lower()}

_TRUTHY = ("1", "true", "yes", "on")


def _on(flag, default="1"):
    return os.environ.get(flag, default).strip().lower() in _TRUTHY


def _grace_minutes():
    try:
        return int(os.environ.get("ORCH_BACKPRESSURE_GRACE_MIN", "45"))
    except Exception:
        return 45


# ---------------------------------------------------------------- verification


def _prod_url(project, project_row=None, health=None):
    """Best-effort production URL for a project."""
    row = project_row or {}
    if not row:
        try:
            row = (db.select("projects", {"select": "*", "name": f"eq.{project}"}) or [{}])[0]
        except Exception:
            row = {}
    h = health or {}
    if not h:
        try:
            h = (db.select("deploy_health", {"select": "*", "app": f"eq.{project}"}) or [{}])[0]
        except Exception:
            h = {}
    url = (h.get("prod_url") or h.get("url") or row.get("prod_url")
           or row.get("production_url") or row.get("url") or "")
    url = str(url or "").strip()
    if url and not url.startswith("http"):
        url = "https://" + url
    return url


def http_ok(url, timeout=20):
    """(status_code, ok) for a plain GET. A 200 is required — 3xx/4xx/5xx are not delivery."""
    if not url:
        return None, False
    req = urllib.request.Request(url, headers={"User-Agent": "beethoven-deploy-verify/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.status == 200
    except urllib.error.HTTPError as e:
        return e.code, False
    except Exception:
        return None, False


def sha_is_live(project, sha, vercel_project=None):
    """True only if Vercel's READY production deployment carries exactly this commit SHA.

    This is the 'the changed behavior is actually present' check at its minimum honest
    form: the build serving production was built from this commit, not merely 'a deploy
    happened around then'.
    """
    if not sha:
        return False, "no release sha"
    try:
        import deploy_verify
        vproj = vercel_project or deploy_verify._vercel_project(project)
        dep = deploy_verify._latest_deploy(vproj, sha=sha)
    except Exception as e:
        return False, f"vercel lookup failed: {e}"
    if not dep or dep.get("_auth_error"):
        return False, (dep or {}).get("_auth_error") or "no production deployment found"
    state = dep.get("state") or dep.get("readyState")
    if state not in ("READY",):
        return False, f"production deployment state={state}"
    meta = dep.get("meta") or {}
    live = str(meta.get("githubCommitSha") or "")
    if not live:
        return False, "deployment reports no commit sha"
    if live == str(sha) or live.startswith(str(sha)[:12]) or str(sha).startswith(live[:12]):
        return True, f"sha {live[:12]} live"
    return False, f"live sha {live[:12]} != release sha {str(sha)[:12]}"


def verify_release(release, project_row=None, health=None):
    """Full terminal check for one release row. Returns a dict; ok=True only if BOTH pass."""
    project = release.get("project")
    sha = release.get("to_sha")
    url = release.get("vercel_url") or _prod_url(project, project_row, health)
    if url and not url.startswith("http"):
        url = "https://" + url
    status, ok200 = http_ok(url)
    live, why = sha_is_live(project, sha)
    return {"project": project, "sha": sha, "url": url, "http_status": status,
            "http_ok": ok200, "sha_live": live, "sha_reason": why,
            "ok": bool(ok200 and live),
            "reason": ("verified" if (ok200 and live)
                       else f"http={status} sha_live={live} ({why})")}


# ------------------------------------------------------------------ promotion


def promote_release(release, dry_run=False):
    """Promote a release's MERGED tasks to DEPLOYED_AND_VERIFIED once the release verifies.

    Only tasks that are currently MERGED for that project and were merged at or before
    the release are promoted; nothing is ever promoted on merge alone.
    """
    if not _on("ORCH_DEPLOY_TERMINAL_ENABLED"):
        return {"promoted": 0, "reason": "ORCH_DEPLOY_TERMINAL_ENABLED=0"}
    result = verify_release(release)
    if not result["ok"]:
        return {"promoted": 0, "reason": result["reason"], "verify": result}
    project = release.get("project")
    try:
        proj = (db.select("projects", {"select": "id", "name": f"eq.{project}"}) or [{}])[0]
        pid = proj.get("id")
    except Exception:
        pid = None
    if not pid:
        return {"promoted": 0, "reason": "unknown project", "verify": result}
    cutoff = release.get("deployed_at") or release.get("created_at")
    q = {"select": "id,slug,state", "project_id": f"eq.{pid}", "state": "eq.MERGED", "limit": "500"}
    if cutoff:
        q["updated_at"] = f"lte.{cutoff}"
    try:
        tasks = db.select("tasks", q) or []
    except Exception:
        tasks = db.select("tasks", {"select": "id,slug,state", "project_id": f"eq.{pid}",
                                    "state": "eq.MERGED", "limit": "500"}) or []
    if dry_run:
        return {"promoted": 0, "would_promote": len(tasks), "verify": result, "dry_run": True}
    promoted = 0
    for t in tasks:
        try:
            db.update("tasks", {"id": t["id"]},
                      {"state": DEPLOYED_AND_VERIFIED,
                       "note": f"deployment verified: {result['url']} @ {str(result['sha'])[:12]} (HTTP 200, sha live)"})
            promoted += 1
        except Exception:
            pass
    print(f"deployment_terminal: promoted {promoted} tasks for {project} to {DEPLOYED_AND_VERIFIED}")
    return {"promoted": promoted, "verify": result}


# --------------------------------------------------------------- back-pressure


def blocking_release(project):
    """Return the failing release blocking `project`, or None if the project is green.

    A project is red when its MOST RECENT release is in a failed state and has aged past
    the grace window. That is real back-pressure: 2,714 failures used to change nothing.
    """
    if not project:
        return None
    try:
        rows = db.select("releases", {"select": "id,project,deploy_status,to_sha,created_at,note",
                                      "project": f"eq.{project}",
                                      "order": "created_at.desc", "limit": "1"}) or []
    except Exception:
        return None
    if not rows:
        return None
    rel = rows[0]
    status = str(rel.get("deploy_status") or "").strip().lower()
    if status not in FAILED_RELEASE_STATES:
        return None
    try:
        import deploy_verify
        if deploy_verify._age_minutes(rel) < _grace_minutes():
            return None            # still inside the grace window; a retry may fix it
    except Exception:
        pass
    return rel


def project_accepts_work(project, slug=""):
    """False when a project is red. Recovery/deploy-fix work is always allowed through —
    otherwise back-pressure would deadlock the very work that turns the project green."""
    if not _on("ORCH_RELEASE_BACKPRESSURE"):
        return True, "backpressure disabled"
    # HEALING EXEMPTIONS — these are the only slugs that can turn a red project green, so
    # they must always pass or back-pressure deadlocks the project forever. The prefixes are
    # taken from the slugs actually emitted in production:
    #   deployfix-<app>-<ts>  (deploy_verify._queue_deploy_fix)
    #   relfix-<app>-<sha>    (release train fix path)
    #   recover-missing-branch-*  (branch recovery)
    s = str(slug or "").lower()
    for allowed in ("deployfix", "deploy-fix", "relfix", "release-fix",
                    "rollback", "hotfix", "recover-missing-branch", "buildfix"):
        if allowed in s:
            return True, f"exempt ({allowed})"
    rel = blocking_release(project)
    if not rel:
        return True, "green"
    return False, (f"project '{project}' is RED: last release {str(rel.get('to_sha') or '')[:8]} "
                   f"is {rel.get('deploy_status')}; no new work until a release goes green "
                   f"(set ORCH_RELEASE_BACKPRESSURE=0 to override)")


# ------------------------------------------------------------ convergence gate


def can_spawn_children(task, reason_out=None):
    """THE CONVERGENCE GATE.

    Nothing that cannot itself reach the terminal state may spawn children. Every failure
    used to spawn tasks and nothing ever retired them (~10:1 amplification). A task may
    only fan out if it is itself still on a path to DEPLOYED_AND_VERIFIED.

    Blocked when the task is:
      * already in a dead/terminal-failure state (CLOSED/QUARANTINED/SHELVED/SUPERSEDED),
      * a shadow/non-integrating clone (structurally can never deploy),
      * owned by a project that is currently RED (its children could not deploy either).
    """
    if not _on("ORCH_CONVERGENCE_GATE"):
        return True, "convergence gate disabled"
    task = task or {}
    state = str(task.get("state") or "").upper()
    slug = str(task.get("slug") or "")

    # NOTE: BLOCKED is deliberately NOT in this list. A blocked task is not dead — decomposing
    # it is precisely how auto_remediate unblocks it, so gating BLOCKED would stall the very
    # remediation that lets work reach the terminal state. Only genuinely dead states qualify.
    if state in ("CLOSED", "QUARANTINED", "SHELVED", "SUPERSEDED"):
        return False, f"task {slug or task.get('id')} is {state} — cannot reach {DEPLOYED_AND_VERIFIED}, may not spawn children"
    if task.get("shadow_only"):
        return False, f"task {slug} is shadow_only — forbidden from integration, may not spawn children"
    if state == DEPLOYED_AND_VERIFIED:
        return False, f"task {slug} already reached {DEPLOYED_AND_VERIFIED} — nothing left to fan out"

    project = task.get("project") or _project_name(task.get("project_id"))
    ok, why = project_accepts_work(project, slug)
    if not ok:
        return False, f"convergence gate: {why}"
    return True, "ok"


def _project_name(project_id):
    if not project_id:
        return ""
    try:
        return (db.select("projects", {"select": "name", "id": f"eq.{project_id}"}) or [{}])[0].get("name") or ""
    except Exception:
        return ""


def gate_or_log(task, context=""):
    """Convenience wrapper: returns True if children may be spawned, logging refusals."""
    ok, why = can_spawn_children(task)
    if not ok:
        print(f"[convergence_gate] BLOCKED spawn{(' in ' + context) if context else ''}: {why}", flush=True)
    return ok


# ------------------------------------------------------------------------ job


def run():
    """Periodic pass: promote verified releases, report which projects are red."""
    rels = db.select("releases", {"select": "*", "deploy_status": "in.(success,deployed)",
                                  "order": "created_at.desc", "limit": "25"}) or []
    promoted = 0
    for rel in rels:
        try:
            promoted += promote_release(rel).get("promoted", 0)
        except Exception as e:
            print(f"deployment_terminal: promote failed for {rel.get('project')}: {e}")
    projects = [p["name"] for p in (db.select("projects", {"select": "name"}) or [])]
    red = []
    for name in projects:
        if blocking_release(name):
            red.append(name)
    print(f"deployment_terminal: promoted={promoted} red_projects={red or 'none'}")
    return {"promoted": promoted, "red_projects": red}


if __name__ == "__main__":
    import json
    print(json.dumps(run(), indent=2, default=str))
