#!/usr/bin/env python3
"""
branch_lifecycle.py — advanced branch management with zero-spend recovery.

Provides lifecycle tracking for agent branches: validation, staleness detection,
cleanup eligibility, and zero-spend recovery (re-queuing tasks whose branches
were lost or never created without burning additional API spend).

Env vars:
    ORCH_BRANCH_STALE_DAYS       days before a branch is considered stale (default 7)
    ORCH_BRANCH_MAX_RETRIES      max recovery attempts before giving up (default 3)
    ORCH_BRANCH_LIFECYCLE        "true" to enable (default "true")
"""
import os
import re
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import log as _log_mod

_log = _log_mod.get("branch_lifecycle")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
ENABLED = os.environ.get("ORCH_BRANCH_LIFECYCLE", "true").lower() in ("1", "true", "yes")
STALE_DAYS = int(os.environ.get("ORCH_BRANCH_STALE_DAYS", "7"))
MAX_RETRIES = int(os.environ.get("ORCH_BRANCH_MAX_RETRIES", "3"))

# Valid branch name pattern (git rules, simplified)
_VALID_BRANCH_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._/-]{0,240}[a-zA-Z0-9]$")
_FORBIDDEN_SEQUENCES = ("..", "~", "^", ":", "\\", " ", "[", "@{")


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def validate_branch_name(name):
    """Check whether *name* is a valid git branch name.

    Returns (True, "") on success or (False, reason) on failure.
    """
    if not name:
        return False, "empty branch name"
    if len(name) > 250:
        return False, f"branch name too long ({len(name)} chars, max 250)"
    for seq in _FORBIDDEN_SEQUENCES:
        if seq in name:
            return False, f"contains forbidden sequence '{seq}'"
    if name.endswith(".lock") or name.endswith("/"):
        return False, "ends with .lock or /"
    if name.startswith("-") or name.startswith("."):
        return False, "starts with - or ."
    if "//" in name:
        return False, "contains consecutive slashes"
    return True, ""


def is_agent_branch(name):
    """Return True if *name* follows the agent/<slug> convention."""
    return bool(name and name.startswith("agent/") and len(name) > 6)


def is_feature_branch(name):
    """Return True if *name* follows the feature/<id> convention."""
    return bool(name and name.startswith("feature/") and len(name) > 8)


# ---------------------------------------------------------------------------
# Branch existence & staleness (requires repo access)
# ---------------------------------------------------------------------------
def branch_exists(repo_path, branch_name):
    """Check if a branch exists in *repo_path*. Returns True/False/None (can't check)."""
    if not repo_path or not os.path.isdir(repo_path):
        return None
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--verify", branch_name],
            cwd=repo_path, capture_output=True, text=True, timeout=15,
        )
        return r.returncode == 0
    except Exception:
        return None


def branch_last_commit_epoch(repo_path, branch_name):
    """Return the unix timestamp of the last commit on *branch_name*, or None."""
    if not repo_path or not os.path.isdir(repo_path):
        return None
    try:
        r = subprocess.run(
            ["git", "log", "-1", "--format=%ct", branch_name],
            cwd=repo_path, capture_output=True, text=True, timeout=15,
        )
        if r.returncode == 0 and r.stdout.strip():
            return int(r.stdout.strip())
    except Exception:
        pass
    return None


def is_stale(repo_path, branch_name, stale_days=None):
    """Return True if the branch's last commit is older than *stale_days*."""
    stale_days = stale_days if stale_days is not None else STALE_DAYS
    epoch = branch_last_commit_epoch(repo_path, branch_name)
    if epoch is None:
        return None  # can't determine
    age_days = (time.time() - epoch) / 86400
    return age_days > stale_days


# ---------------------------------------------------------------------------
# Cleanup eligibility
# ---------------------------------------------------------------------------
def list_cleanup_candidates(repo_path, merged_slugs, stale_days=None):
    """Return list of agent branches eligible for cleanup.

    A branch is eligible if:
      - Its task slug is in *merged_slugs* (task state MERGED/DONE), OR
      - It's stale (no commits for *stale_days*).
    """
    stale_days = stale_days if stale_days is not None else STALE_DAYS
    if not repo_path or not os.path.isdir(repo_path):
        return []

    try:
        r = subprocess.run(
            ["git", "branch", "--list", "agent/*"],
            cwd=repo_path, capture_output=True, text=True, timeout=30,
        )
        if r.returncode != 0:
            return []
        branches = [b.strip().lstrip("* ") for b in r.stdout.splitlines() if b.strip()]
    except Exception:
        return []

    candidates = []
    for branch in branches:
        slug = branch.replace("agent/", "", 1) if branch.startswith("agent/") else branch
        # Already merged → safe to clean
        if slug in merged_slugs:
            candidates.append({"branch": branch, "reason": "merged", "slug": slug})
            continue
        # Stale check
        stale = is_stale(repo_path, branch, stale_days)
        if stale:
            candidates.append({"branch": branch, "reason": "stale", "slug": slug})

    return candidates


# ---------------------------------------------------------------------------
# Zero-spend recovery
# ---------------------------------------------------------------------------
def zero_spend_recovery_eligible(task, repo_path):
    """Determine if a failed task can be recovered without additional API spend.

    Returns a dict with 'eligible' bool and 'strategy' string, or None on error.
    Recovery strategies:
      - 'requeue': branch exists with commits; task can be re-queued to pick up existing work
      - 'recreate_from_base': no branch exists; task can start fresh (zero prior spend)
      - 'adopt_orphan': branch exists but task state is wrong; fix state only
    """
    if not task:
        return {"eligible": False, "strategy": "none", "reason": "no task provided"}

    slug = task.get("slug", "")
    state = task.get("state", "")
    attempt = int(task.get("attempt") or 0)

    if attempt >= MAX_RETRIES:
        return {"eligible": False, "strategy": "none",
                "reason": f"max retries exceeded ({attempt}/{MAX_RETRIES})"}

    branch = f"agent/{slug}"
    exists = branch_exists(repo_path, branch)

    if exists is None:
        return {"eligible": False, "strategy": "none", "reason": "cannot access repo"}

    if exists:
        if state in ("FAILED", "ERROR", "BLOCKED"):
            return {"eligible": True, "strategy": "requeue",
                    "reason": "branch exists with prior work; requeue to continue"}
        if state == "RUNNING":
            return {"eligible": True, "strategy": "adopt_orphan",
                    "reason": "branch exists but task stalled; adopt and continue"}
        return {"eligible": False, "strategy": "none",
                "reason": f"branch exists but state '{state}' not recoverable"}
    else:
        if state in ("FAILED", "ERROR", "BLOCKED"):
            return {"eligible": True, "strategy": "recreate_from_base",
                    "reason": "no branch; start fresh from base (zero prior spend)"}
        return {"eligible": False, "strategy": "none",
                "reason": f"no branch and state '{state}' not recoverable"}


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------
_stats_lock = threading.Lock()
_stats = {"validations": 0, "stale_checks": 0, "recovery_checks": 0, "cleanups_found": 0}


def stats():
    """Return a copy of lifecycle stats."""
    with _stats_lock:
        return dict(_stats)


def reset_stats():
    """Reset stats (for testing)."""
    with _stats_lock:
        for k in _stats:
            _stats[k] = 0
