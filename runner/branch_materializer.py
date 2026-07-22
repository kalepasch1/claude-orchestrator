#!/usr/bin/env python3
"""
branch_materializer.py — Post-decompose branch creation guarantee.

After planner.py decomposes a prompt into subtasks, this module ensures each
task has a real git branch before it enters QUEUED state. This prevents the
common failure mode where an executor claims a task but its branch doesn't exist.

Flow:
  1. Derive branch name deterministically from task slug + project
  2. Create branch locally from base_branch if missing
  3. Push to origin synchronously
  4. On failure, tag the task 'branch-init-failed' for quarantine

Env vars:
    ORCH_BRANCH_MATERIALIZER_ENABLED  – "true" (default) / "false"
    ORCH_BRANCH_PREFIX                – branch name prefix (default "agent/")
    ORCH_BRANCH_PUSH_TIMEOUT          – push timeout in seconds (default 30)
"""
import os, sys, subprocess, re, threading, time
from typing import Optional
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import log as _log_mod

_log = _log_mod.get("branch_materializer")

ENABLED = os.environ.get("ORCH_BRANCH_MATERIALIZER_ENABLED", "true").lower() == "true"
BRANCH_PREFIX = os.environ.get("ORCH_BRANCH_PREFIX", "agent/")
PUSH_TIMEOUT = int(os.environ.get("ORCH_BRANCH_PUSH_TIMEOUT", "30"))

_lock = threading.Lock()
_stats = {
    "branches_created": 0,
    "branches_existed": 0,
    "failures": 0,
}


def derive_branch_name(task_slug, project_name=None):
    """Deterministic branch name from task slug.

    Returns a safe git branch name like 'agent/my-task-slug'.
    """
    slug = re.sub(r"[^a-z0-9\-]", "-", (task_slug or "unknown").lower().strip())
    slug = re.sub(r"-+", "-", slug).strip("-")
    if len(slug) > 80:
        slug = slug[:80].rstrip("-")
    return f"{BRANCH_PREFIX}{slug}"


def _run_git(repo_path, args, timeout=30):
    """Run a git command, return (returncode, stdout, stderr)."""
    try:
        proc = subprocess.run(
            ["git"] + args,
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"
    except Exception as e:
        return -1, "", str(e)


def _branch_exists_local(repo_path, branch_name):
    """Check if branch exists locally."""
    rc, _, _ = _run_git(repo_path, ["rev-parse", "--verify", branch_name])
    return rc == 0


def _branch_exists_remote(repo_path, branch_name):
    """Check if branch exists on origin."""
    rc, out, _ = _run_git(repo_path, ["ls-remote", "--heads", "origin", branch_name], timeout=15)
    return rc == 0 and bool(out.strip())


def materialize_branch(task, repo_path, base_branch="master"):
    """Ensure a git branch exists for this task, creating and pushing if needed.

    Returns dict:
        {"ok": bool, "branch": str, "action": str, "error": Optional[str]}
    """
    if not ENABLED:
        return {"ok": True, "branch": "", "action": "disabled", "error": None}

    slug = task.get("slug") or task.get("id") or "unknown"
    branch = derive_branch_name(slug)

    # Check if already exists locally
    if _branch_exists_local(repo_path, branch):
        with _lock:
            _stats["branches_existed"] += 1
        _log.info("branch %s already exists locally", branch)
        return {"ok": True, "branch": branch, "action": "existed", "error": None}

    # Check remote
    if _branch_exists_remote(repo_path, branch):
        # Fetch it locally
        rc, _, err = _run_git(repo_path, ["fetch", "origin", f"{branch}:{branch}"], timeout=20)
        if rc == 0:
            with _lock:
                _stats["branches_existed"] += 1
            return {"ok": True, "branch": branch, "action": "fetched", "error": None}

    # Create from base
    rc, _, err = _run_git(repo_path, ["branch", branch, base_branch])
    if rc != 0:
        with _lock:
            _stats["failures"] += 1
        _log.error("failed to create branch %s from %s: %s", branch, base_branch, err)
        return {"ok": False, "branch": branch, "action": "create-failed", "error": err}

    # Push to origin
    rc, _, err = _run_git(repo_path, ["push", "origin", branch], timeout=PUSH_TIMEOUT)
    if rc != 0:
        with _lock:
            _stats["failures"] += 1
        _log.error("failed to push branch %s: %s", branch, err)
        return {"ok": False, "branch": branch, "action": "push-failed", "error": err}

    with _lock:
        _stats["branches_created"] += 1
    _log.info("materialized branch %s from %s", branch, base_branch)
    return {"ok": True, "branch": branch, "action": "created", "error": None}


def materialize_task_branches(tasks, repo_path, base_branch="master"):
    """Materialize branches for a list of tasks. Returns list of results.

    Tasks that fail get tagged with 'branch-init-failed' in their result.
    """
    results = []
    for task in tasks:
        result = materialize_branch(task, repo_path, base_branch)
        if not result["ok"]:
            result["tag"] = "branch-init-failed"
        results.append({"task": task.get("slug", "?"), **result})
    return results


def stats():
    """Return copy of materializer stats."""
    with _lock:
        return dict(_stats)
