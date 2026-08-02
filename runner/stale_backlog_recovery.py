#!/usr/bin/env python3
"""
stale_backlog_recovery.py — detection and recovery of orphaned/stale backlog tasks.

Complements backlog_recovery.py (branch-level triage) with task-level recovery:

1. Detects tasks stuck in RUNNING state beyond a staleness threshold
2. Consolidates duplicate/redundant runs of the same task slug
3. Builds auditable recovery actions: requeue, mark_stale, cancel
4. Materializes lost task data from task_artifacts when available

Every entry point is fail-soft: bad timestamps, missing fields, DB or git
errors return empty/False results rather than raising, so a recovery pass
can never wedge the runner.

Env vars:
    ORCH_STALE_THRESHOLD_SECONDS   seconds a RUNNING task may live before it is
                                   considered stale (default 1800)
    ORCH_BACKLOG_STALE_MINUTES     fallback threshold in minutes, used only when
                                   ORCH_STALE_THRESHOLD_SECONDS is unset
    ORCH_BACKLOG_BATCH_LIMIT       max tasks examined per recovery pass (default 50)
    ORCH_MAX_CONSOLIDATIONS        max duplicate runs consolidated per slug (default 3)
    ORCH_RETRY_BACKOFF_BASE        base retry delay in seconds (default 60)
    ORCH_RETRY_BACKOFF_MULTIPLIER  exponential backoff multiplier (default 2.0)
    ORCH_MAX_BACKOFF               retry delay cap in seconds (default 3600)
"""
import os
import subprocess
import sys
import threading
import time
from typing import Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import log as _log_mod

_log = _log_mod.get("stale_backlog_recovery")


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except Exception:
        return default


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "") or default)
    except Exception:
        return default


def _stale_threshold() -> int:
    seconds = os.environ.get("ORCH_STALE_THRESHOLD_SECONDS")
    if seconds:
        try:
            return max(1, int(seconds))
        except Exception:
            pass
    minutes = os.environ.get("ORCH_BACKLOG_STALE_MINUTES")
    if minutes:
        try:
            return max(1, int(minutes) * 60)
        except Exception:
            pass
    return 1800


STALE_THRESHOLD = _stale_threshold()
BATCH_LIMIT = max(1, _int_env("ORCH_BACKLOG_BATCH_LIMIT", 50))
MAX_CONSOLIDATIONS = max(1, _int_env("ORCH_MAX_CONSOLIDATIONS", 3))
RETRY_BACKOFF_BASE = max(1, _int_env("ORCH_RETRY_BACKOFF_BASE", 60))
RETRY_BACKOFF_MULTIPLIER = _float_env("ORCH_RETRY_BACKOFF_MULTIPLIER", 2.0)
MAX_BACKOFF = max(1, _int_env("ORCH_MAX_BACKOFF", 3600))

VALID_ACTIONS = ("requeue", "mark_stale", "cancel")
_TERMINAL_STATES = ("COMPLETED", "FAILED", "CANCELLED", "STALE", "MERGED")

_lock = threading.Lock()
_applied: List[Dict] = []


def _age_seconds(task: Dict, now: Optional[float] = None) -> Optional[float]:
    """Seconds since the task started, or None when the timestamp is unusable."""
    try:
        started = task.get("started_at")
        if started is None:
            return None
        age = (now if now is not None else time.time()) - float(started)
        return age if age >= 0 else None
    except Exception:
        return None


def detect_stale_tasks(tasks: Optional[List[Dict]], threshold_sec: Optional[int] = None) -> List[Dict]:
    """Return RUNNING tasks older than the threshold, most stale first.

    Tasks with missing or malformed timestamps are treated as fresh (safe
    default): a bad clock must never cause a healthy task to be reaped.
    """
    threshold = threshold_sec if threshold_sec is not None else STALE_THRESHOLD
    stale = []
    now = time.time()
    for task in (tasks or []):
        try:
            if not isinstance(task, dict):
                continue
            state = str(task.get("state") or "").upper()
            if state != "RUNNING":
                continue
            age = _age_seconds(task, now)
            if age is None or age < threshold:
                continue
            stale.append((age, task))
        except Exception:
            continue
    stale.sort(key=lambda pair: pair[0], reverse=True)
    return [task for _, task in stale]


def consolidate_duplicates(tasks: Optional[List[Dict]]) -> Dict[str, Dict]:
    """Group RUNNING duplicates by slug: oldest run is kept, younger ones cancel.

    Returns ``{slug: {"keeper": task, "to_cancel": [younger tasks...]}}`` for
    slugs with more than one running instance. At most MAX_CONSOLIDATIONS
    younger runs are marked per slug per pass.
    """
    groups: Dict[str, List[Dict]] = {}
    for task in (tasks or []):
        try:
            if not isinstance(task, dict):
                continue
            if str(task.get("state") or "RUNNING").upper() != "RUNNING":
                continue
            slug = task.get("slug")
            if not slug:
                continue
            groups.setdefault(str(slug), []).append(task)
        except Exception:
            continue

    consolidated: Dict[str, Dict] = {}
    for slug, group in groups.items():
        if len(group) < 2:
            continue

        def _started(t: Dict) -> float:
            try:
                return float(t.get("started_at"))
            except Exception:
                return float("inf")  # unknown age never wins keeper

        ordered = sorted(group, key=_started)
        consolidated[slug] = {
            "keeper": ordered[0],
            "to_cancel": ordered[1:1 + MAX_CONSOLIDATIONS],
        }
    return consolidated


def build_recovery_action(task: Optional[Dict], action_type: str, reason: str = "") -> Optional[Dict]:
    """Build an auditable recovery action, or None for invalid input."""
    try:
        if not isinstance(task, dict) or action_type not in VALID_ACTIONS:
            return None
        target_state = {"requeue": "QUEUED", "mark_stale": "STALE", "cancel": "CANCELLED"}[action_type]
        return {
            "task_id": task.get("id"),
            "slug": task.get("slug"),
            "action": action_type,
            "target_state": target_state,
            "reason": reason or f"stale_running_over_{STALE_THRESHOLD}s",
            "attempt": task.get("attempt", 1),
            "timestamp": time.time(),
        }
    except Exception:
        return None


def detect_lost_data(tasks: Optional[List[Dict]]) -> List[Dict]:
    """Flag tasks whose artifact record is missing (work may be unrecoverable)."""
    lost = []
    for task in (tasks or []):
        try:
            if not isinstance(task, dict):
                continue
            if "artifact_id" in task and not task.get("artifact_id"):
                lost.append({
                    "id": task.get("id"),
                    "slug": task.get("slug"),
                    "issue": "missing_artifacts",
                })
        except Exception:
            continue
    return lost


def get_artifact_data(artifact_or_slug: Optional[str]) -> Optional[Dict]:
    """Fetch stored artifact data via task_artifacts; None when unavailable."""
    if not artifact_or_slug:
        return None
    try:
        import task_artifacts
        return task_artifacts.get_artifacts(artifact_or_slug)
    except Exception:
        return None


def materialize_lost_data(task: Optional[Dict]) -> Optional[Dict]:
    """Recover a task's lost state (commit, files, patch) from task_artifacts."""
    try:
        if not isinstance(task, dict):
            return None
        data = get_artifact_data(task.get("artifact_id") or task.get("slug"))
        if not data:
            return None
        return dict(data)
    except Exception:
        return None


def calculate_backoff_delay(attempt: int) -> float:
    """Exponential retry delay for the given attempt number, capped at MAX_BACKOFF."""
    try:
        exponent = max(0, int(attempt) - 1)
        return min(float(MAX_BACKOFF), RETRY_BACKOFF_BASE * (RETRY_BACKOFF_MULTIPLIER ** exponent))
    except Exception:
        return float(RETRY_BACKOFF_BASE)


def apply_recovery_action(action: Optional[Dict], repo_path: str = ".") -> bool:
    """Apply a recovery action; False on any error (never raises).

    Requeue verifies whether the task's agent branch still exists so a
    missing worktree/branch is recorded rather than assumed.
    """
    try:
        if not isinstance(action, dict) or action.get("action") not in VALID_ACTIONS:
            return False
        record = dict(action)
        if action["action"] == "requeue":
            # A requeue must be grounded in real repo state: confirm we are in a
            # git checkout and whether the task's agent branch survived.
            probe = subprocess.run(
                ["git", "rev-parse", "--git-dir"],
                cwd=repo_path, capture_output=True, text=True, timeout=15,
            )
            record["repo_ok"] = probe.returncode == 0
            if record["repo_ok"] and action.get("slug"):
                result = subprocess.run(
                    ["git", "rev-parse", "--verify", "--quiet", f"agent/{action['slug']}"],
                    cwd=repo_path, capture_output=True, text=True, timeout=15,
                )
                record["branch_exists"] = result.returncode == 0
        with _lock:
            _applied.append(record)
        return True
    except Exception as e:
        _log.warning("apply_recovery_action fail-soft: %s", e)
        return False


def run_recovery_pipeline(tasks: Optional[List[Dict]], threshold_sec: Optional[int] = None,
                          batch_limit: Optional[int] = None) -> Dict:
    """Full pass: detect stale → consolidate duplicates → queue one action per task.

    Idempotent and side-effect free: actions are returned for the caller to
    apply, so re-running on the same snapshot yields the same plan.
    """
    result = {"detected_stale": 0, "consolidated": 0, "actions_queued": 0, "actions": []}
    try:
        limit = batch_limit if batch_limit is not None else BATCH_LIMIT
        batch = [t for t in (tasks or []) if isinstance(t, dict)][:max(1, int(limit))]
        stale = detect_stale_tasks(batch, threshold_sec)
        result["detected_stale"] = len(stale)

        groups = consolidate_duplicates(stale)
        result["consolidated"] = len(groups)
        cancelled_ids = set()
        actions = []
        for group in groups.values():
            for task in group["to_cancel"]:
                action = build_recovery_action(task, "cancel", reason="duplicate_run")
                if action:
                    actions.append(action)
                    cancelled_ids.add(task.get("id"))

        for task in stale:
            if task.get("id") in cancelled_ids:
                continue
            action = build_recovery_action(task, "requeue", reason="stale_running")
            if action:
                actions.append(action)

        result["actions"] = actions
        result["actions_queued"] = len(actions)
    except Exception as e:
        _log.warning("run_recovery_pipeline fail-soft: %s", e)
    return result


def stats() -> Dict:
    """Observability hook: counts of actions applied this process."""
    with _lock:
        by_action: Dict[str, int] = {}
        for record in _applied:
            by_action[record.get("action", "?")] = by_action.get(record.get("action", "?"), 0) + 1
        return {"applied_total": len(_applied), "by_action": by_action}


def invalidate() -> None:
    """Clear the applied-actions record (for tests and operator resets)."""
    with _lock:
        _applied.clear()
