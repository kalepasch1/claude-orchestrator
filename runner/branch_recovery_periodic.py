#!/usr/bin/env python3
"""
branch_recovery_periodic.py - scheduled branch detection+recovery.

Runs every 4h via the fleet scheduler. Loads project paths, detects
missing branches, and either reports (dry-run, default) or recovers.

Env vars:
    ORCH_BRANCH_RECOVERY_DRY_RUN   "true" (default) = detect+report only
    ORCH_BRANCH_RECOVERY_ENABLED   "true" (default) = feature flag
    ORCH_BRANCH_RECOVERY_BATCH     max projects per sweep (default: 20)
"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import log as _log_mod
_log = _log_mod.get("branch_recovery_periodic")
import db

ENABLED = os.environ.get("ORCH_BRANCH_RECOVERY_ENABLED", "true").lower() in ("1", "true", "yes", "on")
DRY_RUN = os.environ.get("ORCH_BRANCH_RECOVERY_DRY_RUN", "true").lower() in ("1", "true", "yes", "on")
BATCH_SIZE = int(os.environ.get("ORCH_BRANCH_RECOVERY_BATCH", "20"))

_stats = {
    "runs": 0,
    "last_run": None,
    "total_detected": 0,
    "total_recovered": 0,
    "projects_scanned": 0,
    "errors": 0,
}


def stats():
    """Return a copy of runtime statistics."""
    return dict(_stats)


def _load_projects():
    """Load project paths from env override or database."""
    env_paths = os.environ.get("ORCH_BRANCH_RECOVERY_PROJECTS", "")
    if env_paths:
        return [{"id": f"env-{i}", "name": os.path.basename(p), "repo_path": p}
                for i, p in enumerate(env_paths.split(":")) if p]
    try:
        rows = db.select("projects", {"select": "*"}) or []
        for p in rows:
            p["repo_path"] = db.localize_repo_path(p.get("repo_path", ""))
        return rows
    except Exception as e:
        _log.warning("failed to load projects from db: %s", e)
        _stats["errors"] += 1
        return []


def _detect_missing_branches(project):
    """Detect tasks with missing branches for a single project."""
    import branch_fleet_recovery
    project_id = project.get("id")
    repo_path = project.get("repo_path", "")
    if not repo_path or not os.path.isdir(repo_path):
        return []
    try:
        filt = {
            "select": "id,slug,project_id,state,kind,prompt,base_branch,note",
            "project_id": f"eq.{project_id}",
            "state": "in.(RUNNING,BLOCKED)",
            "limit": str(BATCH_SIZE * 2),
        }
        tasks = db.select("tasks", filt) or []
    except Exception as e:
        _log.warning("failed to query tasks for project %s: %s", project.get("name"), e)
        _stats["errors"] += 1
        return []

    missing = []
    for task in tasks:
        slug = task.get("slug", "")
        if not slug:
            continue
        branch = f"agent/{slug}"
        if not branch_fleet_recovery._branch_exists_local(repo_path, branch):
            missing.append(task)
    return missing


def _recover_project(project, missing_tasks):
    """Attempt recovery of missing branches for a project. Returns (detected, recovered)."""
    import branch_fleet_recovery
    repo_path = project.get("repo_path", "")
    base_branch = project.get("default_base", "master")
    detected = len(missing_tasks)
    recovered = 0

    for task in missing_tasks:
        slug = task.get("slug", "")
        if DRY_RUN:
            _log.info("[dry-run] detected missing branch agent/%s in %s",
                      slug, project.get("name", "?"))
            continue
        try:
            result = branch_fleet_recovery.recover_branch(task, repo_path, base_branch)
            if result.get("recovered"):
                recovered += 1
                _log.info("recovered branch agent/%s via %s", slug, result.get("strategy"))
            else:
                _log.warning("could not recover agent/%s: %s", slug, result.get("strategy"))
        except Exception as e:
            _log.warning("error recovering agent/%s: %s", slug, e)
            _stats["errors"] += 1

    return detected, recovered


def run():
    """Main entry point for the periodic scheduler."""
    if not ENABLED:
        _log.info("branch recovery periodic: disabled")
        return {"skipped": True, "reason": "disabled"}

    _stats["runs"] += 1
    _stats["last_run"] = time.time()

    projects = _load_projects()
    if not projects:
        _log.info("branch recovery periodic: no projects found")
        return {"projects": 0, "detected": 0, "recovered": 0}

    total_detected = 0
    total_recovered = 0
    scanned = 0

    for project in projects[:BATCH_SIZE]:
        name = project.get("name", "?")
        try:
            missing = _detect_missing_branches(project)
            scanned += 1
            if not missing:
                continue
            detected, recovered = _recover_project(project, missing)
            total_detected += detected
            total_recovered += recovered
            mode = "dry-run" if DRY_RUN else "live"
            _log.info("project %s [%s]: detected=%d recovered=%d",
                      name, mode, detected, recovered)
        except Exception as e:
            _log.warning("error processing project %s: %s", name, e)
            _stats["errors"] += 1

    _stats["total_detected"] += total_detected
    _stats["total_recovered"] += total_recovered
    _stats["projects_scanned"] += scanned

    summary = {
        "projects": scanned,
        "detected": total_detected,
        "recovered": total_recovered,
        "dry_run": DRY_RUN,
    }
    _log.info("branch recovery periodic complete: %s", summary)
    return summary


if __name__ == "__main__":
    run()
