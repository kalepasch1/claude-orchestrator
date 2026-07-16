#!/usr/bin/env python3
"""
git_auth.py - Git authentication with PAT (Personal Access Token) injection.

Provides credential handling for git operations that require authentication.
Supports PAT injection via GIT_ASKPASS to avoid hardcoding credentials in
command lines or storing them in .git/config.

Env vars:
    ORCH_GIT_PAT         Personal Access Token for git operations (kept secret)
    ORCH_GIT_AUTH_DEBUG  "true" to log auth attempts (no credential values)

Fail-soft pattern: always returns sensible defaults on error, never raises.
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import log as _log_mod

_log = _log_mod.get("git_auth")
_PAT = os.environ.get("ORCH_GIT_PAT", "").strip()
_DEBUG = os.environ.get("ORCH_GIT_AUTH_DEBUG", "false").lower() in ("1", "true", "yes", "on")


def _askpass_script():
    """Create a temporary GIT_ASKPASS script that returns the PAT.

    This avoids passing the PAT on the command line and keeps it out of
    process listings and logs.
    """
    if not _PAT:
        return None
    script = os.path.join(
        os.environ.get("CLAUDE_ORCH_HOME", os.path.join(os.path.dirname(__file__), "..", ".runtime")),
        "git-askpass.sh"
    )
    os.makedirs(os.path.dirname(script), exist_ok=True)
    try:
        with open(script, "w") as f:
            f.write(f"#!/bin/sh\necho '{_PAT}'\n")
        os.chmod(script, 0o700)
        return script
    except Exception as e:
        if _DEBUG:
            _log.debug("Failed to create askpass script: %s", e)
        return None


def _env_with_auth():
    """Return environment dict with PAT authentication configured.

    Uses GIT_ASKPASS to provide credentials without exposing them on
    the command line. Falls back to plain environment if PAT not available.
    """
    env = os.environ.copy()
    if not _PAT:
        return env
    askpass = _askpass_script()
    if askpass:
        env["GIT_ASKPASS"] = askpass
        env["GIT_ASKPASS_PROMPT"] = "never"
    return env


def pat_available():
    """Check if PAT is configured and available."""
    return bool(_PAT)


def run_git(args, repo, timeout=60):
    """Run a git command with PAT authentication.

    Args:
        args: List of git command arguments (without 'git' itself)
        repo: Repository path
        timeout: Command timeout in seconds

    Returns:
        (returncode, stdout, stderr) tuple
    """
    if not repo or not os.path.isdir(repo):
        return -1, "", "repo not accessible"

    try:
        env = _env_with_auth()
        result = subprocess.run(
            ["git"] + list(args),
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"
    except Exception as e:
        if _DEBUG:
            _log.debug("Git command failed: %s", str(e)[:200])
        return -1, "", str(e)[:200]


def branch_exists_remote(repo, branch, remote="origin"):
    """Check if a branch exists on remote (requires auth if private repo).

    Returns:
        True if branch exists on remote
        False if branch doesn't exist or repo is unreachable
    """
    rc, out, _ = run_git(["ls-remote", "--heads", remote, branch], repo)
    if rc != 0:
        return False
    return bool(out.strip())


def fetch_branch(repo, branch, remote="origin"):
    """Fetch a branch from remote with authentication.

    Returns:
        (success: bool, error: str or None)
    """
    rc, _, err = run_git(["fetch", remote, f"{branch}:{branch}"], repo)
    if rc == 0:
        if _DEBUG:
            _log.debug("Fetched branch: %s", branch)
        return True, None
    # Log error safely (no credential leaks)
    error_msg = err[:200] if err else "unknown error"
    if _DEBUG:
        _log.debug("Fetch failed for %s: %s", branch, error_msg)
    return False, error_msg


def ls_remote(repo, remote="origin"):
    """List remote branches with authentication.

    Returns:
        (success: bool, branches: list[str])
    """
    rc, out, _ = run_git(["ls-remote", "--heads", remote], repo)
    if rc != 0:
        return False, []
    branches = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            ref = parts[1]
            if ref.startswith("refs/heads/"):
                branches.append(ref[len("refs/heads/"):])
    return True, branches


def auth_status():
    """Return a status dict about git authentication configuration.

    Returns:
        {
            "pat_configured": bool,
            "pat_available": bool,
        }
    """
    return {
        "pat_configured": bool(_PAT),
        "pat_available": pat_available(),
    }
