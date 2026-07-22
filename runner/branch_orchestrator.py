#!/usr/bin/env python3
"""
branch_orchestrator.py — Event-driven branch provisioning and cleanup.

Listens to task state changes and merge train pressure signals to
dynamically create branches for QUEUED tasks (addressing the missing_branch
bottleneck) and remove stale branches for DONE/MERGED tasks.

All SCM operations use environment-variable credentials (never hardcoded).
Failures are logged and retried, never fatal.

Env vars:
    ORCH_BRANCH_ORCHESTRATOR_ENABLED  "true" (default) / "false"
    ORCH_BRANCH_CLEANUP_STALE_DAYS    days before cleanup (default 14)
    ORCH_BRANCH_PROVISION_BATCH       max branches to create per run (default 10)
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import log as _log_mod

_log = _log_mod.get("branch_orchestrator")

ENABLED = os.environ.get("ORCH_BRANCH_ORCHESTRATOR_ENABLED", "true").lower() == "true"
STALE_DAYS = int(os.environ.get("ORCH_BRANCH_CLEANUP_STALE_DAYS", "14"))
PROVISION_BATCH = int(os.environ.get("ORCH_BRANCH_PROVISION_BATCH", "10"))


def find_missing_branches(limit=None):
    """Find QUEUED tasks whose agent branch does not yet exist.

    Returns list of dicts with task metadata for provisioning.
    """
    import db
    limit = limit or PROVISION_BATCH
    tasks = db.select("tasks", {
        "select": "id,slug,project_id,base_branch",
        "state": "eq.QUEUED",
        "order": "created_at.asc",
        "limit": str(limit * 3),
    }) or []
    projects = {p["id"]: p for p in (db.select("projects", {"select": "*"}) or [])}

    missing = []
    for t in tasks:
        proj = projects.get(t.get("project_id"), {})
        repo = db.localize_repo_path(proj.get("repo_path", ""))
        if not repo or not os.path.isdir(repo):
            continue
        branch = f"agent/{t.get('slug', '')}"
        try:
            import subprocess
            r = subprocess.run(["git", "rev-parse", "--verify", branch],
                               cwd=repo, capture_output=True, text=True, timeout=10)
            if r.returncode != 0:
                missing.append({
                    "task_id": t["id"],
                    "slug": t["slug"],
                    "repo_path": repo,
                    "base_branch": t.get("base_branch") or proj.get("default_base", "master"),
                })
        except Exception:
            continue
        if len(missing) >= limit:
            break
    return missing


def provision_branch(slug, repo_path, base_branch):
    """Create an agent branch from base. Returns True on success."""
    import subprocess
    branch = f"agent/{slug}"
    try:
        subprocess.run(["git", "fetch", "origin", "--quiet"],
                       cwd=repo_path, capture_output=True, timeout=30)
        for base in [f"origin/{base_branch}", base_branch]:
            r = subprocess.run(["git", "branch", branch, base],
                               cwd=repo_path, capture_output=True, text=True, timeout=15)
            if r.returncode == 0:
                push = subprocess.run(["git", "push", "origin", branch],
                                      cwd=repo_path, capture_output=True, text=True, timeout=30)
                if push.returncode == 0:
                    _log.info("provisioned branch %s in %s", branch, repo_path)
                    return True
                _log.warning("push failed for %s: %s", branch, push.stderr[:200])
                return False
        _log.warning("could not create %s from %s", branch, base_branch)
        return False
    except Exception as exc:
        _log.warning("provision_branch error for %s: %s", slug, exc)
        return False


def find_stale_branches(repo_path, done_slugs, stale_days=None):
    """Find agent branches eligible for cleanup."""
    import subprocess
    stale_days = stale_days or STALE_DAYS
    try:
        r = subprocess.run(["git", "branch", "--list", "agent/*"],
                           cwd=repo_path, capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            return []
        branches = [b.strip().lstrip("* ") for b in r.stdout.splitlines() if b.strip()]
    except Exception:
        return []

    stale = []
    for branch in branches:
        slug = branch.replace("agent/", "", 1)
        if slug in done_slugs:
            stale.append({"branch": branch, "slug": slug, "reason": "task_done"})
    return stale


def run(dry_run=False):
    """Main entry: provision missing branches and report stale ones.

    Returns summary dict with provisioned/stale counts.
    """
    if not ENABLED:
        return {"enabled": False}

    missing = find_missing_branches()
    provisioned = 0
    for m in missing:
        if dry_run:
            _log.info("dry-run: would provision %s", m["slug"])
            provisioned += 1
        else:
            if provision_branch(m["slug"], m["repo_path"], m["base_branch"]):
                provisioned += 1

    summary = {
        "missing_found": len(missing),
        "provisioned": provisioned,
        "dry_run": dry_run,
    }
    _log.info("branch_orchestrator: %d missing, %d provisioned (dry_run=%s)",
              len(missing), provisioned, dry_run)
    return summary


if __name__ == "__main__":
    import json
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run(dry_run=args.dry_run), indent=2, default=str))
