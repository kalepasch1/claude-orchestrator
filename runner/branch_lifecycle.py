#!/usr/bin/env python3
"""
branch_lifecycle.py — Supabase-backed branch lifecycle tracking.

Logs branch events (creation, cleanup, staleness, recovery) to Supabase
for observability and dashboards. All logging is fire-and-forget —
branch operations never block on telemetry writes.

Env vars:
    ORCH_BRANCH_LIFECYCLE         "true" to enable (default "true")
    ORCH_BRANCH_STALE_DAYS        days before a branch is considered stale (default 7)
    ORCH_BRANCH_MAX_RETRIES       max recovery attempts before giving up (default 3)
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

ENABLED = os.environ.get("ORCH_BRANCH_LIFECYCLE", "true").lower() in ("1", "true", "yes")
STALE_DAYS = int(os.environ.get("ORCH_BRANCH_STALE_DAYS", "7"))
MAX_RETRIES = int(os.environ.get("ORCH_BRANCH_MAX_RETRIES", "3"))


# ---------------------------------------------------------------------------
# Branch name validation
# ---------------------------------------------------------------------------
# RESTORED 2026-08-24: two production callers import this — branch_creator.create_agent_branch()
# (`ok, err = bl.validate_branch_name(branch_name)`) and branch_health.health_score()
# (`from branch_lifecycle import validate_branch_name`) — but the function was never present in
# this module. Every create_agent_branch() call raised AttributeError before it reached git, and
# health_score() raised ImportError on its first line, so bulk_health()'s `except Exception`
# scored EVERY branch 0.5/"exception during scoring" and the naming component never ran.
#
# The rules are git's own (`git check-ref-format --branch`), verified case-by-case against it:
# a name that this accepts is one `git branch` will accept. Two deliberate divergences, both
# stricter than git:
#   - a 255-character cap: a loose ref is a FILE under .git/refs, so longer names are creatable
#     on some filesystems and not others, and the fleet mirrors branches across machines.
#   - the single character "@": git allows it, but it is also the revision shorthand for HEAD,
#     so every later `git rev-parse agent/@`-style read of it is ambiguous.
_MAX_BRANCH_LEN = 255
# Characters git forbids anywhere in a ref, plus ASCII control characters.
_ILLEGAL_CHARS = {
    "~": "'~'", "^": "'^'", ":": "':'", "?": "'?'", "*": "'*'",
    "[": "'['", "\\": "backslash", " ": "a space", "\x7f": "a control character",
}


def validate_branch_name(name):
    """Validate a git branch name. Returns (ok, reason).

    ``reason`` is "" when the name is valid, otherwise a short human-readable
    explanation suitable for a caller's error message. Never raises: a
    non-string argument is simply invalid.
    """
    if not name or not isinstance(name, str):
        return False, "branch name is empty"
    if len(name) > _MAX_BRANCH_LEN:
        return False, f"branch name too long ({len(name)} > {_MAX_BRANCH_LEN})"
    for ch, label in _ILLEGAL_CHARS.items():
        if ch in name:
            return False, f"contains {label}"
    if any(ord(c) < 0x20 for c in name):
        return False, "contains a control character"
    if ".." in name:
        return False, "contains '..'"
    if "@{" in name:
        return False, "contains '@{'"
    if name == "@":
        return False, "'@' alone is not a valid branch name"
    if name.startswith("-"):
        return False, "starts with '-'"
    if name.startswith("/") or name.endswith("/"):
        return False, "starts or ends with '/'"
    if "//" in name:
        return False, "contains consecutive slashes"
    if name.endswith("."):
        return False, "ends with '.'"
    for part in name.split("/"):
        if not part:
            return False, "contains an empty path component"
        if part.startswith("."):
            return False, "a path component starts with '.'"
        if part.endswith(".lock"):
            return False, "a path component ends with '.lock'"
    return True, ""


# ---------------------------------------------------------------------------
# Supabase event logging
# ---------------------------------------------------------------------------
def log_branch_event(event_type, slug, project_id=None, details=None):
    """Record a branch lifecycle event to Supabase for observability.

    Returns (True, "") on success or (False, reason) on failure.
    """
    if not ENABLED:
        return
    try:
        import db as _db
        row = {
            "event_type": event_type,
            "slug": slug or "",
            "project_id": project_id,
            "details": details or {},
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        _db.insert("branch_events", row)
    except Exception as exc:
        _log.warning("branch event log failed (%s/%s): %s", event_type, slug, exc)


def get_branch_health_summary(project_id=None):
    """Query Supabase for branch health metrics.

    Returns dict of event_type -> count for the most recent 1000 events.
    Used by dashboards and alerting. Fails gracefully.
    """
    try:
        import db as _db
        params = {"select": "event_type", "limit": "1000", "order": "ts.desc"}
        if project_id:
            params["project_id"] = f"eq.{project_id}"
        rows = _db.select("branch_events", params) or []
        counts = {}
        for r in rows:
            et = r.get("event_type", "unknown")
            counts[et] = counts.get(et, 0) + 1
        return counts
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Branch existence & staleness
# ---------------------------------------------------------------------------
def branch_exists(repo_path, branch_name):
    """Check if a branch exists in *repo_path*. Returns True/False/None.

    None means "could not determine" — the path is missing, is not a git repository, or
    git could not be run. Callers (zero_spend_recovery_eligible) branch on that: None is
    "cannot access repo", False is the much stronger claim "this repo definitely has no
    such branch", which is what sends a task down the recreate_from_base path.
    """
    if not repo_path or not os.path.isdir(repo_path):
        return None
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--verify", branch_name],
            cwd=repo_path, capture_output=True, text=True, timeout=15,
        )
        if r.returncode == 0:
            return True
        # FIX 2026-08-24: a directory that EXISTS but is not a git repository used to return
        # False — indistinguishable from "the branch is absent" — because `git rev-parse
        # --verify` exits 128 for both a missing ref and a missing repository. A wrong repo
        # path or a worktree replaced by a plain directory therefore reported "no branch" and
        # recommended recreate_from_base against something that is not a repo at all.
        if "not a git repository" in (r.stderr or "").lower():
            return None
        return False
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
        return None
    age_days = (time.time() - epoch) / 86400
    return age_days > stale_days


# ---------------------------------------------------------------------------
# Zero-spend recovery eligibility
# ---------------------------------------------------------------------------
def zero_spend_recovery_eligible(task, repo_path):
    """Determine if a failed task can be recovered without additional API spend.

    Returns dict with 'eligible' bool and 'strategy' string.
    Strategies: 'requeue', 'recreate_from_base', 'adopt_orphan'.
    """
    if not task:
        return {"eligible": False, "strategy": "none", "reason": "no task"}
    slug = task.get("slug", "")
    attempt = int(task.get("attempt") or 0)
    if attempt >= MAX_RETRIES:
        return {"eligible": False, "strategy": "none",
                "reason": f"max retries ({attempt}/{MAX_RETRIES})"}
    branch = f"agent/{slug}"
    exists = branch_exists(repo_path, branch)
    if exists is None:
        return {"eligible": False, "strategy": "none", "reason": "cannot access repo"}
    state = task.get("state", "")
    if exists:
        if state in ("FAILED", "ERROR", "BLOCKED"):
            return {"eligible": True, "strategy": "requeue",
                    "reason": "branch exists; requeue to continue"}
        if state == "RUNNING":
            return {"eligible": True, "strategy": "adopt_orphan",
                    "reason": "branch exists but task stalled"}
    else:
        if state in ("FAILED", "ERROR", "BLOCKED"):
            return {"eligible": True, "strategy": "recreate_from_base",
                    "reason": "no branch; start fresh (zero prior spend)"}
    return {"eligible": False, "strategy": "none",
            "reason": f"state '{state}' not recoverable"}


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
