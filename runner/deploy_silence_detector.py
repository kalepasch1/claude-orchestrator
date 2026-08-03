#!/usr/bin/env python3
"""
deploy_silence_detector.py - alert on the ABSENCE of production deploys.

Every deploy check the fleet owns is triggered BY a deployment: deploy_verify confirms a
deploy that happened, build_gate checks a build that ran, vercel_config_guard validates a
config that was used. None of them can fire when the deployment never occurs at all.

That is precisely the illuminati failure. An `ignoreCommand` comparing
$VERCEL_GIT_COMMIT_REF against "main" on a repo whose default branch is `master` made the
command exit 0 on every production push, and exit 0 means SKIP. Vercel reports a skipped
build as a SUCCESS, so the dashboard was green, no deployment failed, no alert existed --
and production silently stopped updating for a day. Nobody noticed because *nothing
happening* is not an event.

This module inverts the question. Instead of "did this deploy succeed?" it asks "when did
this project last successfully deploy to production, and is that longer ago than it should
be given that commits are still landing?" A project whose default branch has advanced but
whose last READY production deployment is N days old is broken, whatever the dashboard says.

vercel_config_guard.check_deploy_skip() blocks the CONFIG that causes this at merge time;
this detector catches the state regardless of cause -- a disabled project, a revoked token,
a paused integration, a deleted git connection.

Entry point:
  run()   periodic sweep; alerts (notify + approvals card) and files remediation tasks.
Structured JSONL goes to .runtime/logs/deploy-silence-detector.log.
"""
import json
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

NAME = "deploy-silence-detector"
ENABLED = os.environ.get("ORCH_DEPLOY_SILENCE_ENABLED", "true").lower() in (
    "1", "true", "yes", "on")
FILE_TASKS = os.environ.get("ORCH_DEPLOY_SILENCE_FILE_TASKS", "true").lower() in (
    "1", "true", "yes", "on")

# A project is "silent" when production has not deployed in this long WHILE commits landed.
SILENCE_DAYS = float(os.environ.get("ORCH_DEPLOY_SILENCE_DAYS", "2"))
# Re-alerting every cycle is its own kind of noise; hold for this long between alerts.
COOLDOWN_S = float(os.environ.get("ORCH_DEPLOY_SILENCE_COOLDOWN_S", "21600"))
DAY = 86400.0


def _home():
    return os.environ.get("CLAUDE_ORCH_HOME",
                          os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                       "..", ".runtime"))


def _log_event(event):
    row = dict(event)
    row.setdefault("at", time.time())
    row.setdefault("bot", NAME)
    try:
        path = os.path.join(_home(), "logs")
        os.makedirs(path, exist_ok=True)
        with open(os.path.join(path, NAME + ".log"), "a") as fh:
            fh.write(json.dumps(row, separators=(",", ":"), default=str) + "\n")
    except OSError:
        pass
    return row


def _state_path():
    return os.path.join(_home(), "deploy_silence_state.json")


def _load_state():
    try:
        with open(_state_path()) as fh:
            return json.load(fh) or {}
    except (OSError, ValueError):
        return {}


def _save_state(state):
    try:
        os.makedirs(_home(), exist_ok=True)
        with open(_state_path(), "w") as fh:
            json.dump(state, fh, separators=(",", ":"), default=str)
    except OSError:
        pass


def _git(repo, *args):
    try:
        r = subprocess.run(["git"] + list(args), cwd=repo, capture_output=True,
                           text=True, errors="replace", timeout=60)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        return -1, "", str(exc)


def last_commit_age_days(repo, branch):
    """Days since the last commit on the production branch, or None."""
    rc, out, _ = _git(repo, "log", "-1", "--format=%ct", branch)
    if rc != 0 or not out.strip():
        return None
    try:
        return (time.time() - float(out.strip())) / DAY
    except ValueError:
        return None


def last_production_deploy(vercel_project):
    """(age_days, state, url) of the most recent READY production deploy, or None.

    Reuses deploy_verify's authenticated Vercel client so there is exactly one place that
    knows about VERCEL_TOKEN, team ids and API versions.
    """
    try:
        import deploy_verify
    except Exception:
        return None
    try:
        data = deploy_verify._vget(
            "/v6/deployments?limit=20&target=production&projectId=" + str(vercel_project))
    except Exception:
        return None
    if not data:
        return None
    for dep in (data.get("deployments") or []):
        state = (dep.get("state") or dep.get("readyState") or "").upper()
        if state != "READY":
            continue
        created = dep.get("created") or dep.get("createdAt") or 0
        try:
            age = (time.time() - float(created) / 1000.0) / DAY
        except (TypeError, ValueError):
            continue
        return age, state, dep.get("url") or ""
    # Deployments exist but NONE is READY -- also silence, and worth saying so distinctly.
    deps = data.get("deployments") or []
    if deps:
        return None, (deps[0].get("state") or deps[0].get("readyState") or "?").upper(), ""
    return None


def evaluate(project_row, silence_days=None):
    """Decide whether one project is deploy-silent. Returns a finding dict or None."""
    silence_days = SILENCE_DAYS if silence_days is None else silence_days
    repo = project_row.get("repo_path") or ""
    name = project_row.get("name") or "?"
    branch = project_row.get("prod_branch") or project_row.get("default_base") or "master"
    if not repo or not os.path.isdir(repo):
        return None
    commit_age = last_commit_age_days(repo, branch)
    if commit_age is None:
        return None
    # No recent commits => nothing SHOULD have deployed. Not silence, just quiet.
    if commit_age > silence_days:
        return None
    try:
        import deploy_verify
        vercel_project = deploy_verify._vercel_project(name, project_row)
    except Exception:
        vercel_project = None
    if not vercel_project:
        return None
    latest = last_production_deploy(vercel_project)
    if latest is None:
        return {"project": name, "repo": repo, "branch": branch, "vercel": vercel_project,
                "commit_age_days": commit_age, "deploy_age_days": None,
                "reason": ("%s has commits on '%s' as recently as %.1f day(s) ago, but the "
                           "Vercel API reports NO production deployment history at all for "
                           "project '%s'. Production is not being built. A skipped build is "
                           "recorded as a success, so nothing else in the fleet can see this."
                           % (name, branch, commit_age, vercel_project))}
    deploy_age, state, url = latest
    if deploy_age is None:
        return {"project": name, "repo": repo, "branch": branch, "vercel": vercel_project,
                "commit_age_days": commit_age, "deploy_age_days": None,
                "reason": ("%s has recent commits on '%s' (%.1f day(s) ago) but NOT ONE "
                           "production deployment has reached READY — the newest is in state "
                           "%s." % (name, branch, commit_age, state))}
    if deploy_age <= silence_days:
        return None
    return {"project": name, "repo": repo, "branch": branch, "vercel": vercel_project,
            "commit_age_days": commit_age, "deploy_age_days": deploy_age, "url": url,
            "reason": ("%s last deployed to production %.1f day(s) ago (threshold %.1f) while "
                       "its branch '%s' received a commit %.1f day(s) ago. Commits are landing "
                       "and production is NOT updating. Check vercel.json ignoreCommand and "
                       "git.deploymentEnabled first: an ignoreCommand that exits 0 SKIPS the "
                       "build and Vercel records the skip as a SUCCESS, which is exactly how "
                       "illuminati lost a day of production deploys with no alert anywhere."
                       % (name, deploy_age, silence_days, branch, commit_age))}


def _alert(finding):
    """Put the silence somewhere a human actually looks: notify + an approvals card."""
    headline = ("DEPLOY SILENCE: %s has not deployed to production in %s day(s) while "
                "commits keep landing" % (finding["project"],
                                          ("%.1f" % finding["deploy_age_days"])
                                          if finding.get("deploy_age_days") is not None
                                          else "ANY number of"))
    try:
        import notify
        notify.send(headline)
    except Exception as exc:
        _log_event({"event": "notify_error", "error": str(exc)})
    try:
        db.insert("approvals", {
            "kind": "deploy_silence", "project": finding["project"],
            "summary": headline[:300], "detail": finding["reason"][:2000],
            "state": "OPEN"}, upsert=False)
    except Exception as exc:
        _log_event({"event": "approval_error", "error": str(exc)})
    return headline


def _file_task(project_row, finding):
    if not FILE_TASKS or not project_row.get("id"):
        return None
    slug = ("deploysilence-%s" % re.sub(r"[^a-z0-9]+", "-",
                                        str(finding["project"]).lower()).strip("-"))[:60]
    try:
        existing = db.select("tasks", {"select": "id,state", "slug": "eq.%s" % slug,
                                       "limit": "1"}) or []
        if existing and existing[0].get("state") not in (
                "DONE", "MERGED", "SHIPPED", "CLOSED", "SHELVED"):
            return None
        return db.insert("tasks", {
            "project_id": project_row["id"], "slug": slug, "state": "QUEUED", "kind": "build",
            "prompt": ("Production has stopped deploying and NOTHING reported a failure.\n\n"
                       "%s\n\nA Vercel build that is SKIPPED is recorded as a SUCCESS, so the "
                       "dashboard stays green. Check, in order:\n"
                       "  1. vercel.json ignoreCommand — does it exit 0 for branch '%s'? "
                       "exit 0 means SKIP.\n"
                       "  2. vercel.json git.deploymentEnabled — is '%s' mapped to false, or "
                       "matched by a glob that maps to false?\n"
                       "  3. The Vercel project's git connection and VERCEL_TOKEN validity.\n\n"
                       "Verify with: python3 runner/vercel_config_guard.py %s"
                       % (finding["reason"], finding["branch"], finding["branch"],
                          finding["project"])),
        })
    except Exception as exc:
        _log_event({"event": "task_error", "slug": slug, "error": str(exc)})
        return None


def run(project=None, silence_days=None):
    """Sweep every project for production-deploy silence."""
    if not ENABLED:
        print("deploy_silence_detector: disabled")
        return {"enabled": False}
    params = {"select": "*"}
    if project:
        params["name"] = "eq.%s" % project
    projects = db.select("projects", params) or []
    state = _load_state()
    now = time.time()
    summary = {"projects": 0, "silent": 0, "alerted": 0, "tasks_filed": 0}
    for p in projects:
        summary["projects"] += 1
        try:
            finding = evaluate(p, silence_days)
        except Exception as exc:
            _log_event({"event": "evaluate_error", "project": p.get("name"), "error": str(exc)})
            continue
        if not finding:
            continue
        summary["silent"] += 1
        _log_event({"event": "silence", **finding})
        print("  %-14s SILENT: %s" % (p.get("name"), finding["reason"][:150]), flush=True)
        prior = state.get(str(p.get("name")), {})
        if (now - float(prior.get("last_alert") or 0)) >= COOLDOWN_S:
            _alert(finding)
            summary["alerted"] += 1
            state[str(p.get("name"))] = {"last_alert": now,
                                         "deploy_age_days": finding.get("deploy_age_days")}
        if _file_task(p, finding):
            summary["tasks_filed"] += 1
    _save_state(state)
    _log_event({"event": "sweep", **summary})
    print("deploy_silence_detector: %(projects)d project(s), %(silent)d silent, "
          "%(alerted)d alerted, %(tasks_filed)d task(s) filed" % summary)
    return summary


def stats():
    try:
        projects = db.select("projects", {"select": "name,repo_path"}) or []
        return {"enabled": ENABLED, "projects": len(projects), "silence_days": SILENCE_DAYS}
    except Exception:
        return {"enabled": ENABLED, "projects": 0, "silence_days": SILENCE_DAYS}


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    run(args[0] if args else None)
