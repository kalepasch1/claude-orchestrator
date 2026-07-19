#!/usr/bin/env python3
"""
cowork_dispatch.py — track and monitor Cowork-based task execution.
============================================================================
The orchestrator executes tasks via local Claude Code CLI subprocesses on Mac
machines (~8 tasks/hr). This module monitors a parallel execution path where
Cowork scheduled tasks independently claim and execute tasks from the same
Supabase queue. Both paths use the same atomic optimistic claiming protocol
(PATCH state=QUEUED→RUNNING), so they naturally load-balance without
double-claiming.

Cowork sessions identify themselves with account names starting with "cowork-".

Functions (module-level, delegating to thread-safe singleton):
  cowork_stats()              -> dict with throughput metrics for the fleet dashboard
  is_cowork_claimed(task)     -> True if a task was claimed by a Cowork session
  cowork_throughput_per_hour()-> recent Cowork tasks/hr from the DB
  adjust_local_lanes(limit)   -> reduces local runner's effective limit when Cowork active

All results are cached for 60s to avoid hammering the DB. Fail-soft: returns
sensible defaults on any error, never raises.
"""
import os, sys, threading, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

# ---------------------------------------------------------------------------
# Configuration (env vars with ORCH_ prefix, sensible defaults)
# ---------------------------------------------------------------------------
COWORK_ACCOUNT_PREFIX = os.environ.get("ORCH_COWORK_ACCOUNT_PREFIX", "cowork-")
CACHE_TTL = int(os.environ.get("ORCH_COWORK_CACHE_TTL", "60") or 60)
THROUGHPUT_WINDOW_HOURS = int(os.environ.get("ORCH_COWORK_THROUGHPUT_WINDOW", "4") or 4)
# When Cowork throughput exceeds this threshold (tasks/hr), start reducing local lanes
LANE_REDUCTION_THRESHOLD = float(os.environ.get("ORCH_COWORK_LANE_THRESHOLD", "0.5") or 0.5)
# Maximum fraction of local lanes to yield to Cowork (0.0–1.0)
MAX_LANE_REDUCTION = float(os.environ.get("ORCH_COWORK_MAX_LANE_REDUCTION", "0.75") or 0.75)


# ---------------------------------------------------------------------------
# Singleton tracker
# ---------------------------------------------------------------------------
class _CoworkTracker:
    def __init__(self):
        self._lock = threading.Lock()
        self._cache = {}       # key -> (timestamp, value)

    # -- cache helper ------------------------------------------------------
    def _cached(self, key, fn):
        """Return cached value if fresh, otherwise call fn() and cache it."""
        with self._lock:
            entry = self._cache.get(key)
            if entry and (time.time() - entry[0]) < CACHE_TTL:
                return entry[1]
        # Do DB I/O outside the lock
        try:
            val = fn()
        except Exception:
            # fail-soft: return stale cache if available, else default
            with self._lock:
                entry = self._cache.get(key)
                return entry[1] if entry else None
            return None
        with self._lock:
            self._cache[key] = (time.time(), val)
        return val

    def invalidate(self, key=None):
        """Clear one cache key or all."""
        with self._lock:
            if key:
                self._cache.pop(key, None)
            else:
                self._cache.clear()

    # -- core queries ------------------------------------------------------
    def _fetch_cowork_tasks(self):
        """Fetch tasks claimed by Cowork sessions (RUNNING/DONE/MERGED)."""
        rows = db.select("tasks", {
            "select": "id,slug,project_id,state,account,created_at,updated_at",
            "account": f"like.{COWORK_ACCOUNT_PREFIX}*",
            "state": "in.(RUNNING,DONE,MERGED)",
            "order": "updated_at.desc",
            "limit": "500",
        }) or []
        return rows

    def _fetch_cowork_running(self):
        """Fetch tasks currently RUNNING on Cowork sessions."""
        rows = db.select("tasks", {
            "select": "id,slug,project_id,state,account,created_at,updated_at",
            "account": f"like.{COWORK_ACCOUNT_PREFIX}*",
            "state": "eq.RUNNING",
        }) or []
        return rows

    def _fetch_cowork_done_window(self):
        """Fetch tasks completed by Cowork in the throughput window."""
        import datetime
        cutoff = (datetime.datetime.utcnow()
                  - datetime.timedelta(hours=THROUGHPUT_WINDOW_HOURS)).isoformat() + "Z"
        rows = db.select("tasks", {
            "select": "id,slug,state,account,updated_at",
            "account": f"like.{COWORK_ACCOUNT_PREFIX}*",
            "state": "in.(DONE,MERGED)",
            "updated_at": f"gte.{cutoff}",
        }) or []
        return rows

    # -- public interface --------------------------------------------------
    def is_cowork_claimed(self, task):
        """True if a task dict was claimed by a Cowork session."""
        if not task:
            return False
        account = ""
        if isinstance(task, dict):
            account = task.get("account") or ""
        return account.startswith(COWORK_ACCOUNT_PREFIX)

    def cowork_throughput_per_hour(self):
        """Calculate recent Cowork tasks/hr from DB. Cached."""
        def _calc():
            rows = self._fetch_cowork_done_window()
            if not rows:
                return 0.0
            return len(rows) / max(1, THROUGHPUT_WINDOW_HOURS)
        val = self._cached("throughput", _calc)
        return val if val is not None else 0.0

    def cowork_stats(self):
        """Return dict with throughput metrics for the fleet dashboard."""
        def _calc():
            all_tasks = self._cached("all_cowork", self._fetch_cowork_tasks)
            if all_tasks is None:
                all_tasks = []
            running = [t for t in all_tasks if t.get("state") == "RUNNING"]
            done = [t for t in all_tasks if t.get("state") in ("DONE", "MERGED")]

            # Avg execution time: difference between created_at and updated_at
            # for completed tasks (rough proxy — updated_at is set on state transition)
            durations = []
            for t in done:
                try:
                    import datetime
                    created = t.get("created_at", "")
                    updated = t.get("updated_at", "")
                    if created and updated:
                        # ISO parse (good enough for the metric)
                        c = datetime.datetime.fromisoformat(created.replace("Z", "+00:00"))
                        u = datetime.datetime.fromisoformat(updated.replace("Z", "+00:00"))
                        delta = (u - c).total_seconds()
                        if 0 < delta < 86400:  # sanity: < 24h
                            durations.append(delta)
                except Exception:
                    pass

            avg_dur = round(sum(durations) / len(durations), 1) if durations else 0.0
            tph = self.cowork_throughput_per_hour()

            # Unique Cowork session accounts
            accounts = set()
            for t in all_tasks:
                acc = t.get("account") or ""
                if acc.startswith(COWORK_ACCOUNT_PREFIX):
                    accounts.add(acc)

            return {
                "cowork_running": len(running),
                "cowork_done": len(done),
                "cowork_total": len(all_tasks),
                "cowork_throughput_per_hour": round(tph, 2),
                "cowork_avg_duration_s": avg_dur,
                "cowork_active_sessions": len(accounts),
                "cowork_active": tph > 0 or len(running) > 0,
            }

        val = self._cached("stats", _calc)
        if val is None:
            return {
                "cowork_running": 0, "cowork_done": 0, "cowork_total": 0,
                "cowork_throughput_per_hour": 0.0, "cowork_avg_duration_s": 0.0,
                "cowork_active_sessions": 0, "cowork_active": False,
            }
        return val

    def adjust_local_lanes(self, current_limit):
        """Reduce local runner's effective parallel limit when Cowork is actively
        processing, to avoid resource contention on git worktrees.

        Returns an int >= 1 (never shuts down local execution entirely).
        """
        if not isinstance(current_limit, (int, float)) or current_limit < 1:
            return max(1, int(current_limit or 1))
        try:
            tph = self.cowork_throughput_per_hour()
            if tph < LANE_REDUCTION_THRESHOLD:
                return int(current_limit)
            # Scale reduction linearly: at threshold → 0% reduction,
            # at 2x threshold → MAX_LANE_REDUCTION
            ratio = min(1.0, (tph - LANE_REDUCTION_THRESHOLD) / max(0.1, LANE_REDUCTION_THRESHOLD))
            # Re-read from env each call so hot_reload can change it without restart
            max_red = float(os.environ.get("ORCH_COWORK_MAX_LANE_REDUCTION", "0.75") or 0.75)
            reduction = ratio * max_red
            adjusted = int(current_limit * (1.0 - reduction))
            return max(1, adjusted)
        except Exception:
            return int(current_limit)

    def stats_dict(self):
        """Alias for dashboard compatibility."""
        return self.cowork_stats()


# ---------------------------------------------------------------------------
# Module-level singleton + delegating functions
# ---------------------------------------------------------------------------
_tracker = _CoworkTracker()


def cowork_stats():
    """Return dict with throughput metrics for the fleet dashboard."""
    return _tracker.cowork_stats()


def is_cowork_claimed(task):
    """True if a task was claimed by a Cowork session."""
    return _tracker.is_cowork_claimed(task)


def cowork_throughput_per_hour():
    """Calculate recent Cowork tasks/hr from the DB."""
    return _tracker.cowork_throughput_per_hour()


def adjust_local_lanes(current_limit):
    """Reduce local runner's effective limit when Cowork is actively processing."""
    return _tracker.adjust_local_lanes(current_limit)


def invalidate(key=None):
    """Clear cached data (for testing or forced refresh)."""
    _tracker.invalidate(key)


def stats():
    """Alias matching the codebase stats() convention."""
    return _tracker.cowork_stats()


if __name__ == "__main__":
    import json
    print(json.dumps(cowork_stats(), indent=2))
