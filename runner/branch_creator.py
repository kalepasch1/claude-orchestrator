"""Branch creation executor.

Creates missing branches on approval, handling existing branches
and permission errors gracefully.
"""

import subprocess
import logging
from typing import Dict, Any, Optional

log = logging.getLogger(__name__)


class BranchCreationResult:
    """Result of a branch creation attempt."""

    def __init__(self, success: bool, branch_name: str, reason: str = ""):
        self.success = success
        self.branch_name = branch_name
        self.reason = reason

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "branch_name": self.branch_name,
            "reason": self.reason,
        }


def create_branch(project_path: str, branch_name: str,
                  base_branch: str = "main",
                  remote: str = "origin",
                  push: bool = True,
                  run_command=None) -> BranchCreationResult:
    """Create a branch from base and optionally push to origin.

    Args:
        project_path: Local path to the git repo
        branch_name: Name of the branch to create
        base_branch: Branch to base off of
        remote: Remote name
        push: Whether to push after creation
        run_command: Optional callable(cmd, cwd) -> (returncode, stdout, stderr)
                     for testing. Defaults to subprocess.run.
    """
    if run_command is None:
        run_command = _default_run

    # 1. Fetch latest
    rc, out, err = run_command(["git", "fetch", remote], project_path)
    if rc != 0:
        return BranchCreationResult(False, branch_name, f"fetch failed: {err}")

    # 2. Check if branch already exists locally or remotely
    rc, out, _ = run_command(
        ["git", "branch", "--list", branch_name], project_path
    )
    if out.strip():
        return BranchCreationResult(True, branch_name, "branch already exists locally")

    rc, out, _ = run_command(
        ["git", "ls-remote", "--heads", remote, branch_name], project_path
    )
    if out.strip():
        return BranchCreationResult(True, branch_name, "branch already exists on remote")

    # 3. Create branch
    rc, out, err = run_command(
        ["git", "branch", branch_name, f"{remote}/{base_branch}"], project_path
    )
    if rc != 0:
        return BranchCreationResult(False, branch_name, f"branch creation failed: {err}")

    # 4. Push if requested
    if push:
        rc, out, err = run_command(
            ["git", "push", remote, branch_name], project_path
        )
        if rc != 0:
            if "permission" in err.lower() or "denied" in err.lower():
                return BranchCreationResult(False, branch_name, f"permission denied: {err}")
            return BranchCreationResult(False, branch_name, f"push failed: {err}")

    return BranchCreationResult(True, branch_name, "created successfully")


def _default_run(cmd, cwd):
    """Default command runner using subprocess."""
    try:
        result = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, timeout=60
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return 1, "", "command timed out"
    except FileNotFoundError:
        return 1, "", "git not found"
