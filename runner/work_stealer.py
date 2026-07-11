#!/usr/bin/env python3
"""
work_stealer.py - Fleet-level work stealing.

When a machine finishes its own tasks and its local project queue is empty,
it steals QUEUED tasks from other projects whose repos exist locally. This
maximises fleet utilisation without requiring manual task redistribution.

Conservative by default: ORCH_WORK_STEALING_ENABLED defaults to "false" since
cross-project execution is an opt-in capability. Enable fleet-wide via
fleet_control / fleetctl.

Env vars:
    ORCH_WORK_STEALING_ENABLED  - "true"/"false" (default "false")
    ORCH_STEAL_MAX_PER_CYCLE    - max tasks to steal per idle cycle (default "2")
"""

import sys, os, time, threading
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import log as _log_mod
_log = _log_mod.get("work_stealer")
import db

# ── Configuration (read live from env, not frozen at import) ──────────────────

def _enabled():
    return os.environ.get("ORCH_WORK_STEALING_ENABLED", "false").lower() in ("true", "1", "yes")

def _max_per_cycle():
    try:
        return int(os.environ.get("ORCH_STEAL_MAX_PER_CYCLE", "2"))
    except (ValueError, TypeError):
        return 2

# ── Thread-safe stats ────────────────────────────────────────────────────────

_lock = threading.Lock()
_stats = {
    "tasks_stolen": 0,
    "tasks_completed_stolen": 0,
    "tasks_failed_stolen": 0,
    "idle_time_saved_s": 0.0,
    "last_steal_ts": 0.0,
}


def stats():
    """Return a snapshot of work-stealing statistics."""
    with _lock:
        return dict(_stats)


def record_stolen_outcome(task_id, success):
    """Track whether a stolen task completed successfully.

    Called by the runner after a stolen task finishes so we can monitor
    cross-project success rates and back off if stealing is counterproductive.
    """
    with _lock:
        if success:
            _stats["tasks_completed_stolen"] += 1
        else:
            _stats["tasks_failed_stolen"] += 1
    _log.info("stolen outcome task=%s success=%s", task_id, success)


# ── Core logic ────────────────────────────────────────────────────────────────

def available_repos():
    """Return list of project_ids whose repos exist on this machine."""
    try:
        projs = db.select("projects", {"select": "id,repo_path"}) or []
    except Exception:
        _log.debug("available_repos: db query failed")
        return []
    result = []
    for p in projs:
        repo = p.get("repo_path")
        if not repo:
            # No repo_path means the project uses cwd; runnable anywhere.
            result.append(p["id"])
            continue
        try:
            localized = db.localize_repo_path(repo)
            if os.path.isdir(localized):
                result.append(p["id"])
        except Exception:
            pass
    return result


def should_steal(runner_id=None, primary_project_ids=None):
    """Return True when the runner should attempt to steal work.

    Conditions:
      1. Work stealing is enabled.
      2. Local queue is empty (no QUEUED tasks for primary projects).
      3. System has capacity (resource_governor.can_claim()).
      4. There are QUEUED tasks in other projects with locally-available repos.
    """
    if not _enabled():
        return False

    # Check system capacity first (cheapest gate).
    try:
        import resource_governor
        ok, reason = resource_governor.can_claim()
        if not ok:
            _log.debug("should_steal: no capacity - %s", reason)
            return False
    except Exception:
        pass  # fail-open if resource_governor unavailable

    primary_ids = set(primary_project_ids or [])

    # Check local queue: any QUEUED tasks for our primary projects?
    try:
        if primary_ids:
            for pid in primary_ids:
                rows = db.select("tasks", {
                    "select": "id",
                    "state": "eq.QUEUED",
                    "project_id": f"eq.{pid}",
                    "limit": "1",
                })
                if rows:
                    _log.debug("should_steal: primary project %s has queued work", pid)
                    return False
        else:
            # No primary projects specified; check if ANY local-repo tasks exist.
            local_pids = available_repos()
            if local_pids:
                rows = db.select("tasks", {
                    "select": "id",
                    "state": "eq.QUEUED",
                    "limit": "1",
                })
                if rows:
                    return False
    except Exception:
        _log.debug("should_steal: queue check failed, declining")
        return False

    # Check that there ARE stealable tasks from non-primary projects.
    try:
        local_pids = set(available_repos())
        stealable_pids = local_pids - primary_ids
        if not stealable_pids:
            return False
        for pid in stealable_pids:
            rows = db.select("tasks", {
                "select": "id",
                "state": "eq.QUEUED",
                "project_id": f"eq.{pid}",
                "limit": "1",
            })
            if rows:
                return True
    except Exception:
        _log.debug("should_steal: stealable check failed")
        return False

    return False


def steal_task(runner_id, primary_project_ids=None):
    """Attempt to steal one QUEUED task from a non-primary project.

    Prefers tasks with:
      - No unmet dependencies
      - Lower complexity (confidence as proxy)
      - Projects this runner has previously worked on

    Returns the claimed task dict or None.
    """
    if not _enabled():
        return None

    primary_ids = set(primary_project_ids or [])
    local_pids = set(available_repos())
    stealable_pids = local_pids - primary_ids

    if not stealable_pids:
        _log.debug("steal_task: no stealable projects")
        return None

    # Fetch candidate tasks from stealable projects.
    candidates = []
    try:
        for pid in stealable_pids:
            rows = db.select("tasks", {
                "select": "id,slug,project_id,deps,confidence,created_at,kind,note",
                "state": "eq.QUEUED",
                "project_id": f"eq.{pid}",
                "order": "created_at.asc",
                "limit": "10",
            }) or []
            candidates.extend(rows)
    except Exception:
        _log.debug("steal_task: failed to fetch candidates")
        return None

    if not candidates:
        return None

    # Filter out tasks with unmet deps.
    filtered = []
    for t in candidates:
        deps = t.get("deps") or []
        if isinstance(deps, str):
            try:
                import json
                deps = json.loads(deps)
            except Exception:
                deps = []
        if not deps:
            filtered.append(t)

    # Fall back to all candidates if everything has deps (still worth trying).
    if not filtered:
        filtered = candidates

    # Sort: prefer no-deps, then high confidence (low complexity), then FIFO.
    def _sort_key(t):
        deps = t.get("deps") or []
        if isinstance(deps, str):
            try:
                import json
                deps = json.loads(deps)
            except Exception:
                deps = []
        has_deps = 1 if deps else 0
        # Higher confidence = simpler task = preferred for stealing.
        conf = t.get("confidence")
        if conf is None:
            conf = 0.5
        return (has_deps, -conf, t.get("created_at", ""))

    filtered.sort(key=_sort_key)

    # Verify repo exists locally and attempt optimistic claim.
    steal_start = time.time()
    for t in filtered:
        pid = t.get("project_id")
        # Double-check repo is actually present.
        try:
            projs = db.select("projects", {"select": "repo_path", "id": f"eq.{pid}"}) or []
            if projs:
                repo = projs[0].get("repo_path", "")
                if repo:
                    localized = db.localize_repo_path(repo)
                    if not os.path.isdir(localized):
                        _log.debug("steal_task: repo not local for project %s", pid)
                        continue
        except Exception:
            continue

        # Optimistic claim: only succeeds if task is still QUEUED.
        try:
            result = db.update("tasks",
                               {"id": t["id"], "state": "eq.QUEUED"},
                               {"state": "CLAIMED", "runner": runner_id})
            if result:
                elapsed = time.time() - steal_start
                with _lock:
                    _stats["tasks_stolen"] += 1
                    _stats["idle_time_saved_s"] += elapsed
                    _stats["last_steal_ts"] = time.time()
                _log.info("stolen task=%s slug=%s project=%s runner=%s",
                          t["id"], t.get("slug"), pid, runner_id)
                # Return the task dict with updated state.
                t["state"] = "CLAIMED"
                t["runner"] = runner_id
                return t
        except Exception as e:
            _log.debug("steal_task: claim failed for task %s: %s", t["id"], e)
            continue

    return None
