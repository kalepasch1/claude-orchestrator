#!/usr/bin/env python3
"""branch_creator.py — create missing agent branches on approval.

Creates agent/<slug> branches from a base branch when the merge train or
task executor discovers a branch is missing. Uses environment-variable
credentials (never hardcoded). All git operations use subprocess with
timeouts to prevent hangs.

Env vars:
    GITHUB_PAT              Personal access token (required for push)
    ORCH_GIT_TIMEOUT        Git command timeout in seconds (default 60)

Security:
    - No secrets in code — reads GITHUB_PAT from env only
    - PAT is never logged or included in error messages
    - Failed auth returns a generic error, not credential details
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import log as _log_mod
import branch_lifecycle as bl

_log = _log_mod.get("branch_creator")
GIT_TIMEOUT = int(os.environ.get("ORCH_GIT_TIMEOUT", "60"))


def _git(args, repo):
    """Run a git command. Returns (stdout, success_bool)."""
    try:
        r = subprocess.run(
            ["git"] + args, cwd=repo,
            capture_output=True, text=True, timeout=GIT_TIMEOUT,
        )
        return r.stdout.strip(), r.returncode == 0
    except subprocess.TimeoutExpired:
        _log.warning("git timeout: %s", " ".join(args[:3]))
        return "", False
    except Exception as exc:
        _log.warning("git error: %s", exc)
        return "", False


def create_branch(project_id, branch_name, base_branch="main", repo_path=None):
    """Create an agent branch from *base_branch* and push to origin.

    Args:
        project_id:  project identifier (used for logging, not git ops)
        branch_name: full branch name, e.g. "agent/my-task-slug"
        base_branch: branch to fork from (default "main")
        repo_path:   absolute path to local repo clone

    Returns:
        dict with keys: success (bool), reason (str)
    """
    # ── Validate inputs ──
    if not repo_path or not os.path.isdir(repo_path):
        return {"success": False, "reason": f"repo path not found: {repo_path}"}

    ok, err = bl.validate_branch_name(branch_name)
    if not ok:
        return {"success": False, "reason": f"invalid branch name: {err}"}

    # ── Check PAT availability (never log the value) ──
    pat = os.environ.get("GITHUB_PAT", "")
    if not pat:
        return {"success": False,
                "reason": "GITHUB_PAT not set — cannot push. "
                          "Set it in the environment before calling."}

    # ── Fetch latest ──
    _, fetched = _git(["fetch", "origin", "--quiet"], repo_path)
    if not fetched:
        _log.warning("fetch failed for %s (continuing with local state)", project_id)

    # ── Check if branch already exists ──
    existing = bl.branch_exists(repo_path, branch_name)
    if existing:
        return {"success": True, "reason": "branch already exists"}

    # ── Create branch from base ──
    _, created = _git(
        ["branch", branch_name, f"origin/{base_branch}"],
        repo_path,
    )
    if not created:
        # Fallback: try local base branch
        _, created = _git(["branch", branch_name, base_branch], repo_path)
    if not created:
        return {"success": False,
                "reason": f"failed to create branch from {base_branch}"}

    # ── Push to origin ──
    _, pushed = _git(
        ["push", "origin", f"{branch_name}:{branch_name}"],
        repo_path,
    )
    if not pushed:
        return {"success": False,
                "reason": "branch created locally but push failed "
                          "(check GITHUB_PAT scope)"}

    _log.info("created branch %s from %s in %s", branch_name, base_branch, project_id)
    return {"success": True, "reason": "created and pushed"}
