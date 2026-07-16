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
# Supabase event logging
# ---------------------------------------------------------------------------
def log_branch_event(event_type, slug, project_id=None, details=None):
    """Record a branch lifecycle event to Supabase for observability.

    Events: 'created', 'cleaned', 'recovered', 'stale_detected', 'recovery_failed'.
    Fails silently — branch operations must never block on logging.
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
    """Check if a branch exists in *repo_path*. Returns True/False/None."""
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
