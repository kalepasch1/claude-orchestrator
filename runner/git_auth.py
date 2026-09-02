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


def redact(text):
    """Strip the configured PAT, and any recognised key shape, from git output.

    git puts the credential into its own error text as a matter of routine --
    "fatal: unable to access 'https://x-access-token:ghp_xxx@github.com/o/r/'"
    is the standard failure for an expired token -- and this module's callers
    put that text straight into log lines and task notes, where it persists and
    is read by everything downstream. run_git returned result.stderr verbatim,
    so the boundary where the credential is known was also the one place it was
    never removed.

    Two passes, because neither alone is enough: db.redact_secrets knows the
    published key shapes (ghp_, github_pat_, sk-ant-, ...) but not a token whose
    format it has never seen, and the literal _PAT match catches exactly that
    one at the cost of knowing nothing else. Fail-soft throughout: redaction
    must never be the reason a git error goes unreported.
    """
    if not text or not isinstance(text, str):
        return text
    out = _redact_known_shapes(text)
    if _PAT:
        out = out.replace(_PAT, "[REDACTED]")
    return out


def _redact_known_shapes(text):
    """db.redact_secrets applied to text, or text unchanged if db cannot load.

    Imported lazily and fail-soft: git_auth is imported by modules that run
    before the control plane is reachable, and a redaction that raises would
    turn a reported git error into an unreported one.
    """
    try:
        import db as _db
        return _db.redact_secrets(text)
    except Exception:
        return text


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
        return (result.returncode,
                redact(result.stdout.strip()),
                redact(result.stderr.strip()))
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"
    except Exception as e:
        detail = redact(str(e))[:200]
        if _DEBUG:
            _log.debug("Git command failed: %s", detail)
        return -1, "", detail


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
