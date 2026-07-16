#!/usr/bin/env python3
"""
branch_recovery.py - detect and recover missing git branches.

Recovery strategies (tried in order):
  1. Fetch from origin/upstream remotes
  2. Restore from git reflog if the branch was recently active
  3. Mark as unrecoverable if the branch is >30 days stale

Pure git operations — no database writes.

Env vars:
    ORCH_BRANCH_RECOVERY_ENABLED    "true" (default) to enable
    ORCH_BRANCH_RECOVERY_STALE_DAYS days before marking unrecoverable (default: 30)
    ORCH_BRANCH_RECOVERY_TIMEOUT    git command timeout in seconds (default: 60)
"""
import os, re, subprocess, sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import log as _log_mod
_log = _log_mod.get("branch_recovery")

ENABLED = os.environ.get("ORCH_BRANCH_RECOVERY_ENABLED", "true").lower() in ("1", "true", "yes", "on")
STALE_DAYS = int(os.environ.get("ORCH_BRANCH_RECOVERY_STALE_DAYS", "30"))
TIMEOUT = int(os.environ.get("ORCH_BRANCH_RECOVERY_TIMEOUT", "60"))

# ── module-level counters ──────────────────────────────────────────
_stats = {
    "recover_attempts": 0,
    "recover_fetched": 0,
    "recover_reflog": 0,
    "recover_unrecoverable": 0,
    "recover_errors": 0,
    "detect_calls": 0,
    "detect_missing_found": 0,
}


def stats():
    """Return a snapshot of module counters."""
    return dict(_stats)


# ── git helpers ────────────────────────────────────────────────────
def _git(repo, *args):
    """Run a git command; return (returncode, stdout, stderr)."""
    try:
        r = subprocess.run(
            ["git"] + list(args),
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
        )
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"
    except Exception as e:
        return -1, "", str(e)


def _is_git_repo(path):
    """Check whether *path* is inside a valid git working tree."""
    if not path or not os.path.isdir(path):
        return False
    rc, _, _ = _git(path, "rev-parse", "--is-inside-work-tree")
    return rc == 0


def _branch_exists_local(repo, branch):
    rc, _, _ = _git(repo, "rev-parse", "--verify", f"refs/heads/{branch}")
    return rc == 0


def _branch_on_remote(repo, branch, remote="origin"):
    """Return True when the branch exists on *remote*."""
    rc, out, _ = _git(repo, "ls-remote", "--heads", remote, branch)
    return rc == 0 and bool(out.strip())


def _fetch_branch(repo, branch, remote="origin"):
    """Attempt to fetch *branch* from *remote* and create a local ref."""
    rc, _, err = _git(repo, "fetch", remote,
                      f"refs/heads/{branch}:refs/heads/{branch}")
    return rc == 0, err


def _reflog_recover(repo, branch):
    """Try to find *branch* in the reflog and recreate it.

    Searches reflog for checkout/branch-create entries referencing this branch.
    Only succeeds if the reflog entry is within STALE_DAYS.
    """
    rc, out, _ = _git(repo, "reflog", "--format=%H %gd %gs", "--all")
    if rc != 0 or not out:
        return False, "no reflog data"

    pattern = re.compile(
        r"^([0-9a-f]{7,40})\s+\S+\s+.*(?:checkout|branch).*\b"
        + re.escape(branch) + r"\b",
        re.IGNORECASE,
    )
    candidate_sha = None
    for line in out.splitlines():
        m = pattern.match(line)
        if m:
            candidate_sha = m.group(1)
            break

    if not candidate_sha:
        return False, "branch not found in reflog"

    # Check staleness of the commit
    rc2, date_str, _ = _git(repo, "show", "-s", "--format=%ci", candidate_sha)
    if rc2 == 0 and date_str:
        try:
            commit_dt = datetime.strptime(date_str[:19], "%Y-%m-%d %H:%M:%S")
            if datetime.utcnow() - commit_dt > timedelta(days=STALE_DAYS):
                return False, f"reflog entry too old ({date_str[:10]})"
        except ValueError:
            pass  # can't parse — proceed anyway

    rc3, _, err = _git(repo, "branch", branch, candidate_sha)
    if rc3 == 0:
        return True, f"restored from reflog ({candidate_sha[:8]})"
    return False, f"branch create failed: {err}"


# ── public API ─────────────────────────────────────────────────────
def recover_branch(project_path, branch_name):
    """Attempt to recover a missing branch.

    Returns dict with keys:
        status:       'recovered' | 'unrecoverable'
        action_taken: str describing what happened
    """
    if not ENABLED:
        return {"status": "unrecoverable", "action_taken": "feature disabled"}

    _stats["recover_attempts"] += 1

    if not _is_git_repo(project_path):
        _stats["recover_errors"] += 1
        return {"status": "unrecoverable",
                "action_taken": f"invalid git path: {project_path}"}

    # Already exists locally — nothing to do
    if _branch_exists_local(project_path, branch_name):
        return {"status": "recovered",
                "action_taken": "branch already exists locally"}

    # Strategy 1: fetch from origin
    if _branch_on_remote(project_path, branch_name, "origin"):
        ok, detail = _fetch_branch(project_path, branch_name, "origin")
        if ok:
            _stats["recover_fetched"] += 1
            _log.info("recovered %s via origin fetch", branch_name)
            return {"status": "recovered",
                    "action_taken": "fetched from origin"}
        _log.warning("origin fetch failed for %s: %s", branch_name, detail)

    # Strategy 1b: try upstream remote
    if _branch_on_remote(project_path, branch_name, "upstream"):
        ok, detail = _fetch_branch(project_path, branch_name, "upstream")
        if ok:
            _stats["recover_fetched"] += 1
            _log.info("recovered %s via upstream fetch", branch_name)
            return {"status": "recovered",
                    "action_taken": "fetched from upstream"}
        _log.warning("upstream fetch failed for %s: %s", branch_name, detail)

    # Strategy 2: reflog recovery
    ok, detail = _reflog_recover(project_path, branch_name)
    if ok:
        _stats["recover_reflog"] += 1
        _log.info("recovered %s via reflog: %s", branch_name, detail)
        return {"status": "recovered",
                "action_taken": f"reflog recovery: {detail}"}

    # Strategy 3: unrecoverable
    _stats["recover_unrecoverable"] += 1
    _log.info("branch %s is unrecoverable: %s", branch_name, detail)
    return {"status": "unrecoverable",
            "action_taken": f"all strategies exhausted: {detail}"}


def detect_missing_branches(project_path, expected_branches):
    """Return a list of branch names from *expected_branches* that are missing locally.

    Args:
        project_path:      path to git repo
        expected_branches: iterable of branch name strings

    Returns:
        list of missing branch names (empty list if all present or on error)
    """
    _stats["detect_calls"] += 1

    if not ENABLED:
        return []

    if not _is_git_repo(project_path):
        _stats["recover_errors"] += 1
        return []

    missing = []
    for branch in expected_branches:
        if not _branch_exists_local(project_path, branch):
            missing.append(branch)
    _stats["detect_missing_found"] += len(missing)
    return missing
