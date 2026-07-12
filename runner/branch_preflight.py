#!/usr/bin/env python3
"""
branch_preflight.py — Proactive branch validation before merge train processing.

Checks all pending-merge tasks for branch existence BEFORE the merge train starts
processing them, alerting operators and auto-remediating missing branches to prevent
the common failure mode where merge_train hits a missing branch mid-run.

Owner module: merge_train.py, branch_materializer.py
Slice-2 of: improve-implement-advanced-branch-management-sys
"""
import os, sys, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def _safe_import(mod):
    try:
        return __import__(mod)
    except Exception:
        return None

db = _safe_import("db")
log_mod = _safe_import("log")
_log = log_mod.get("branch_preflight") if log_mod else None

BRANCH_PREFIX = os.environ.get("ORCH_BRANCH_PREFIX", "agent/")
CHECK_TIMEOUT = int(os.environ.get("ORCH_BRANCH_CHECK_TIMEOUT", "10"))


def _branch_exists(repo_path, branch):
    """Check if a branch exists locally. Returns True/False/None (unresolvable)."""
    if not repo_path or not os.path.isdir(repo_path):
        return None
    try:
        r = subprocess.run(["git", "rev-parse", "--verify", branch],
                           cwd=repo_path, capture_output=True, text=True, timeout=CHECK_TIMEOUT)
        return r.returncode == 0
    except Exception:
        return None


def _localize_repo(raw_path):
    """Use db.localize_repo_path if available, else return raw."""
    if db and hasattr(db, "localize_repo_path"):
        return db.localize_repo_path(raw_path)
    return raw_path


def preflight_check(project_id, repo_path_raw, tasks):
    """Check all tasks for branch existence before merge processing.

    Args:
        project_id: project UUID
        repo_path_raw: raw repo_path from the project record
        tasks: list of task dicts with at least {slug, state}

    Returns:
        {
            "ready": [task_dicts with branches present],
            "missing": [task_dicts with missing branches],
            "unresolvable": [task_dicts where repo can't be checked],
            "repo_path": localized repo path used
        }
    """
    repo = _localize_repo(repo_path_raw)
    ready, missing, unresolvable = [], [], []

    for task in tasks:
        slug = task.get("slug", "")
        branch = f"{BRANCH_PREFIX}{slug}"
        exists = _branch_exists(repo, branch)

        if exists is True:
            ready.append(task)
        elif exists is False:
            missing.append(task)
            if _log:
                _log.warning("preflight: branch %s missing for task %s", branch, slug)
        else:
            unresolvable.append(task)

    return {
        "ready": ready,
        "missing": missing,
        "unresolvable": unresolvable,
        "repo_path": repo,
        "total_checked": len(tasks),
    }


def auto_remediate_missing(project_id, repo_path_raw, missing_tasks, base_branch="main"):
    """Attempt to create missing branches for tasks that need them.

    Uses branch_materializer if available, otherwise creates directly.

    Returns list of {slug, remediated: bool, error: str|None}
    """
    repo = _localize_repo(repo_path_raw)
    if not repo or not os.path.isdir(repo):
        return [{"slug": t.get("slug"), "remediated": False, "error": "repo not found"}
                for t in missing_tasks]

    bm = _safe_import("branch_materializer")
    results = []
    for task in missing_tasks:
        slug = task.get("slug", "")
        if bm:
            r = bm.materialize_branch(task, repo, base_branch)
            results.append({"slug": slug, "remediated": r.get("ok", False),
                            "error": r.get("error")})
        else:
            # Direct creation fallback
            branch = f"{BRANCH_PREFIX}{slug}"
            try:
                proc = subprocess.run(["git", "branch", branch, base_branch],
                                       cwd=repo, capture_output=True, text=True, timeout=15)
                ok = proc.returncode == 0
                results.append({"slug": slug, "remediated": ok,
                                "error": None if ok else proc.stderr.strip()})
            except Exception as e:
                results.append({"slug": slug, "remediated": False, "error": str(e)})

    return results


def run_preflight(project_id):
    """Full preflight: load project, check branches, remediate missing ones.

    Returns summary dict.
    """
    if not db:
        return {"error": "db unavailable"}
    try:
        projects = db.select("projects", {"select": "*", "id": f"eq.{project_id}"}) or []
        if not projects:
            return {"error": f"project {project_id} not found"}
        proj = projects[0]
        repo_raw = proj.get("repo_path", "")

        # Get tasks pending merge (RUNNING state with merge-related notes, or DONE awaiting train)
        pending = db.select("tasks", {
            "select": "id,slug,state,kind,base_branch",
            "project_id": f"eq.{project_id}",
            "state": "in.(DONE,RUNNING)",
            "limit": "200"
        }) or []

        check = preflight_check(project_id, repo_raw, pending)
        remediated = []
        if check["missing"]:
            base = proj.get("base_branch", "main")
            remediated = auto_remediate_missing(project_id, repo_raw, check["missing"], base)

        return {
            "project": proj.get("name"),
            "total_checked": check["total_checked"],
            "ready": len(check["ready"]),
            "missing": len(check["missing"]),
            "unresolvable": len(check["unresolvable"]),
            "remediated": sum(1 for r in remediated if r.get("remediated")),
            "remediation_failures": [r for r in remediated if not r.get("remediated")],
        }
    except Exception as e:
        return {"error": str(e)}
