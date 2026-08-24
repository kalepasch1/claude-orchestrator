#!/usr/bin/env python3
"""
branch_fleet_recovery.py - fleet-wide missing branch auto-recovery.

When a branch is missing across all fleet machines, attempts recovery:
  1. Check if branch exists on any remote, fetch if so (requires git auth)
  2. If missing everywhere or auth fails, requeue task for re-execution

Env vars:
    ORCH_FLEET_BRANCH_RECOVERY   "true" (default) to enable
    ORCH_FLEET_RECOVERY_BATCH    max tasks per run (default: 5)
    ORCH_GIT_PAT                 Personal Access Token for private repos
"""
import os, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import log as _log_mod
_log = _log_mod.get("branch_fleet_recovery")
import db
import git_auth

ENABLED = os.environ.get("ORCH_FLEET_BRANCH_RECOVERY", "true").lower() in ("1", "true", "yes", "on")
BATCH_SIZE = int(os.environ.get("ORCH_FLEET_RECOVERY_BATCH", "5"))
DRY_RUN = os.environ.get("ORCH_FLEET_RECOVERY_DRY_RUN", "false").lower() in ("1", "true", "yes", "on")
TIMEOUT = int(os.environ.get("ORCH_FLEET_RECOVERY_TIMEOUT_S", "60"))

def _git(repo, *args):
    """Run git command without auth (for local checks)."""
    try:
        r = subprocess.run(["git"] + list(args), cwd=repo,
                           capture_output=True, text=True, timeout=TIMEOUT)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except Exception as e:
        return -1, "", str(e)

def _branch_exists_local(repo, branch):
    rc, _, _ = _git(repo, "rev-parse", "--verify", branch)
    return rc == 0

def _branch_exists_remote(repo, branch):
    """Check if branch exists on remote, using authenticated git operations."""
    return git_auth.branch_exists_remote(repo, branch, "origin")

#: How many times a slug may be re-wrapped in the `recover-` prefix before the
#: sweep refuses to requeue it again. Generation 0 is the original task, so the
#: default of 1 permits exactly one recovery attempt.
MAX_GENERATION = int(os.environ.get("ORCH_FLEET_RECOVERY_MAX_GENERATION", "1"))

RECOVERY_PREFIX = "recover-"


def recovery_generation(slug):
    """How many `recover-` wrappers this slug already carries.

    `recover_branch` requeues a lost branch as `recover-<slug>`. Nothing stopped
    the *recovery* task from being swept in turn: once it reached DONE and its
    own branch `agent/recover-<slug>` went missing, the next sweep produced
    `recover-recover-<slug>`, then `recover-recover-recover-<slug>`, without
    bound. Every generation re-attempted the same patch against the same paths,
    which is why one file (e.g. packages/darwin-kernel/src/passport/passport.ts)
    kept coming back with an identical conflict — the conflict was not being
    retried, it was being *recreated* by a new task each cycle.

    Counting the prefixes is what makes that loop observable, and capping it is
    what stops it. Fail-soft: a non-string slug reports generation 0.
    """
    if not isinstance(slug, str):
        return 0
    generation = 0
    remainder = slug
    while remainder.startswith(RECOVERY_PREFIX):
        generation += 1
        remainder = remainder[len(RECOVERY_PREFIX):]
    return generation


def recover_branch(task, repo_path, base_branch="master"):
    slug = task.get("slug", "")
    branch = f"agent/{slug}"
    if _branch_exists_local(repo_path, branch):
        return {"recovered": True, "strategy": "already_exists"}
    if _branch_exists_remote(repo_path, branch):
        if DRY_RUN:
            return {"recovered": False, "strategy": "dry_run"}
        # Use authenticated git operations for fetch
        ok, err = git_auth.fetch_branch(repo_path, branch, "origin")
        if ok:
            _log.info("recovered %s from remote", branch)
            return {"recovered": True, "strategy": "fetched_remote"}
        _log.warning("fetch failed for %s (auth may be required)", branch)
    if DRY_RUN:
        return {"recovered": False, "strategy": "dry_run"}
    # Check if PAT is configured
    if not git_auth.pat_available():
        _log.info("skipping recovery for %s (PAT unavailable)", slug)
        return {"recovered": False, "strategy": "pat_unavailable"}
    generation = recovery_generation(slug)
    if generation >= MAX_GENERATION:
        # Refuse to deepen the chain. Logged with the generation so the loop is
        # legible in the sweep output instead of showing up as an ever-growing
        # slug nobody connects back to the original task.
        _log.warning(
            "refusing to requeue %s: recovery generation %d >= max %d "
            "(branch %s still missing; the chain is looping, not converging)",
            slug, generation, MAX_GENERATION, branch,
        )
        return {"recovered": False, "strategy": "max_generation_exceeded",
                "detail": f"generation={generation} max={MAX_GENERATION}"}
    recovery_slug = f"{RECOVERY_PREFIX}{slug}"
    try:
        existing = db.select("tasks", {"select": "id", "slug": f"eq.{recovery_slug}",
                   "project_id": f"eq.{task.get('project_id')}", "limit": "1"}) or []
        if existing:
            return {"recovered": False, "strategy": "already_requeued"}
        row = {"project_id": task.get("project_id"), "slug": recovery_slug,
               "prompt": f"Re-execute (branch lost fleet-wide): {(task.get('prompt') or '')[:500]}",
               "deps": [], "kind": task.get("kind", "build"), "state": "QUEUED",
               "base_branch": task.get("base_branch", base_branch),
               "note": f"fleet-recovery: branch {branch} missing everywhere"}
        db.insert("tasks", row, upsert=True)
        db.update("tasks", task["id"], {"note": f"fleet-recovery: requeued as {recovery_slug}"})
        _log.info("requeued %s as %s", slug, recovery_slug)
        return {"recovered": True, "strategy": "requeued", "detail": recovery_slug}
    except Exception as e:
        return {"recovered": False, "strategy": "error", "detail": str(e)}

def sweep(project_id=None):
    if not ENABLED:
        return []
    filt = {"select": "id,slug,project_id,state,kind,prompt,base_branch,note",
            "state": "eq.DONE", "limit": str(BATCH_SIZE * 3)}
    if project_id:
        filt["project_id"] = f"eq.{project_id}"
    tasks = db.select("tasks", filt) or []
    projects = {p["id"]: p for p in (db.select("projects", {"select": "*"}) or [])}
    results = []
    for task in tasks:
        if len(results) >= BATCH_SIZE:
            break
        proj = projects.get(task.get("project_id"), {})
        repo = db.localize_repo_path(proj.get("repo_path", ""))
        if not repo or not os.path.isdir(repo):
            continue
        if _branch_exists_local(repo, f"agent/{task.get('slug')}"):
            continue
        result = recover_branch(task, repo, proj.get("default_base", "master"))
        result["slug"] = task.get("slug")
        results.append(result)
    if results:
        _log.info("fleet branch recovery: processed %d tasks", len(results))
    return results
