#!/usr/bin/env python3
"""
priority_queue.py - Priority queue (pinned express-lane) for critical tasks.

Enables routing of certain tasks to an express-lane queue path for fast-track
processing, bypassing normal scheduling delays. Pinned tasks are matched against
configurable prefixes (e.g., 'recovery', 'breach-remediation') and processed
within ~10% of normal queue time.

Key functions:
  acquire() -> _PriorityQueue singleton          # get the singleton instance
  classify_task(task) -> {"is_pinned": bool}    # determine if task is pinned
  dispatch(task) -> wait_time_ms                 # dispatch task to express lane if pinned
  stats() -> {"total_pinned": N, ...}            # return queue statistics

Configuration (fleet_config):
  ORCH_PRIORITY_QUEUE_ENABLED (bool, default False)
  ORCH_PINNED_TASK_PREFIXES (str, comma-separated, default "")
  ORCH_PINNED_MIN_ROI (float, default "" = disabled)

Slug prefixes only express-lane work we can name in advance. High-ROI fixes are
identified by score at queue time, not by naming convention, so they used to wait
behind the normal lane no matter how valuable they were. ORCH_PINNED_MIN_ROI pins
any task whose roi / ev_score / value_per_minute meets the threshold, so the two
pin paths (name-based and value-based) are ORed together.

Fail-soft: missing/invalid config doesn't wedge queue; falls back to normal behavior.
Thread-safe: uses explicit lock to protect shared state.
"""
import os, sys, time, threading
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Fail-soft import: db may not be available in all contexts
try:
    import db
    _DB_AVAILABLE = True
except Exception:
    _DB_AVAILABLE = False


class _PriorityQueue:
    """Internal singleton managing pinned task dispatch."""

    def __init__(self):
        """Initialize the priority queue state."""
        self._lock = threading.Lock()
        self._total_pinned = 0
        self._total_pinned_by_roi = 0     # subset of _total_pinned, for rollout telemetry
        self._pinned_wait_times = []      # milliseconds
        self._normal_wait_times = []      # milliseconds
        self._max_samples = 1000          # keep only recent samples
        self._enabled = False
        self._pinned_prefixes = []
        self._min_roi = None              # None = value-based pinning disabled
        self._last_config_load = 0
        self._config_ttl = 60             # reload config every 60 seconds

    # Score fields are checked in descending order of directness: an explicit roi
    # wins over a modelled ev_score, which wins over a throughput proxy.
    ROI_FIELDS = ("roi", "ev_score", "value_per_minute")

    def _load_config(self):
        """Load priority queue config from environment (via fleet_config).

        Fail-soft: any error keeps previous config intact.
        """
        now = time.time()
        # Only reload config if TTL expired (avoid thrashing)
        if now - self._last_config_load < self._config_ttl:
            return

        self._last_config_load = now

        try:
            # Read from environment (fleet_control loads fleet_config into env)
            enabled_str = os.environ.get("ORCH_PRIORITY_QUEUE_ENABLED", "false").lower()
            self._enabled = enabled_str in ("true", "1", "yes")

            prefixes_str = os.environ.get("ORCH_PINNED_TASK_PREFIXES", "").strip()
            self._pinned_prefixes = [p.strip() for p in prefixes_str.split(",") if p.strip()]

            # Value-based pinning. Unset or unparseable leaves it disabled rather than
            # defaulting to 0.0, which would express-lane the entire queue.
            min_roi_str = os.environ.get("ORCH_PINNED_MIN_ROI", "").strip()
            if min_roi_str:
                try:
                    self._min_roi = float(min_roi_str)
                except (TypeError, ValueError):
                    self._min_roi = None
            else:
                self._min_roi = None
        except Exception:
            # Fail-soft: keep previous config
            pass

    def _roi_of(self, task):
        """Best available ROI/EV score for a task, or None if it carries no usable score.

        Fail-soft: a non-numeric or missing score is treated as "no signal" so the task
        falls through to the normal lane instead of raising.
        """
        for field in self.ROI_FIELDS:
            raw = task.get(field)
            if raw is None or isinstance(raw, bool):
                continue
            try:
                return float(raw)
            except (TypeError, ValueError):
                continue
        return None

    def _pin_reason(self, task):
        """Why (if at all) a task belongs in the express lane.

        Returns: str - "prefix", "roi", or "" when the task stays in the normal lane.
        Prefix wins over roi when both apply, so operator-named lanes stay explainable.
        """
        if not self._enabled:
            return ""

        # Check slug (e.g., "recovery-fix-001", "breach-remediation-2026-08-04")
        slug = (task.get("slug") or "").lower()
        branch = (task.get("branch") or "").lower()

        for prefix in self._pinned_prefixes:
            p = prefix.lower()
            if slug.startswith(p) or branch.startswith(p):
                return "prefix"

        # High-ROI fixes go to the front even when nobody named them in advance.
        if self._min_roi is not None:
            roi = self._roi_of(task)
            if roi is not None and roi >= self._min_roi:
                return "roi"

        return ""

    def _is_pinned(self, task):
        """Determine if a task should take the express lane.

        Returns: bool - True on a pinned-prefix match or an ROI at/above the threshold.
        """
        return bool(self._pin_reason(task))

    def classify_task(self, task):
        """Classify a task as pinned or normal.

        Args:
            task: dict with 'slug', 'branch', 'created_at' fields

        Returns:
            {"is_pinned": bool, "reason": str}
        """
        with self._lock:
            self._load_config()
            pin_reason = self._pin_reason(task)
            return {
                "is_pinned": bool(pin_reason),
                "pin_reason": pin_reason,
                "reason": {
                    "prefix": "matches pinned prefix",
                    "roi": "roi at or above ORCH_PINNED_MIN_ROI",
                }.get(pin_reason, "normal queue"),
            }

    def dispatch(self, task):
        """Dispatch a task to appropriate queue lane.

        Pinned tasks return immediately (0ms wait); normal tasks follow standard scheduling.
        In practice, pinned tasks would be moved to a high-priority dispatch queue
        (a design choice left to the scheduler integration).

        Args:
            task: dict with task metadata

        Returns:
            {"wait_ms": int, "lane": str, "pinned": bool}
        """
        with self._lock:
            self._load_config()
            pin_reason = self._pin_reason(task)

            if pin_reason:
                # Express-lane: immediate dispatch (0ms wait)
                self._total_pinned += 1
                if pin_reason == "roi":
                    self._total_pinned_by_roi += 1
                return {
                    "wait_ms": 0,
                    "lane": "express",
                    "pinned": True,
                    "pin_reason": pin_reason,
                }
            else:
                # Normal queue: standard scheduling
                return {
                    "wait_ms": None,  # scheduler decides
                    "lane": "normal",
                    "pinned": False,
                    "pin_reason": "",
                }

    def record_wait_time(self, task, wait_ms):
        """Record actual wait time for a task (used for stats).

        Args:
            task: dict with task metadata
            wait_ms: int - actual wait time in milliseconds
        """
        if not isinstance(wait_ms, (int, float)) or wait_ms < 0:
            return

        with self._lock:
            self._load_config()
            is_pinned = self._is_pinned(task)

            times = self._pinned_wait_times if is_pinned else self._normal_wait_times
            times.append(int(wait_ms))

            # Keep only recent samples (FIFO eviction)
            if len(times) > self._max_samples:
                times.pop(0)

    def stats(self):
        """Return queue statistics.

        Returns:
            {
                "enabled": bool,
                "total_pinned": int,
                "pinned_prefixes": [str],
                "avg_pinned_wait_ms": float,
                "avg_normal_wait_ms": float,
                "sample_count_pinned": int,
                "sample_count_normal": int,
            }
        """
        with self._lock:
            self._load_config()

            avg_pinned = None
            if self._pinned_wait_times:
                avg_pinned = sum(self._pinned_wait_times) / len(self._pinned_wait_times)

            avg_normal = None
            if self._normal_wait_times:
                avg_normal = sum(self._normal_wait_times) / len(self._normal_wait_times)

            return {
                "enabled": self._enabled,
                "total_pinned": self._total_pinned,
                "total_pinned_by_roi": self._total_pinned_by_roi,
                "min_roi": self._min_roi,
                "pinned_prefixes": list(self._pinned_prefixes),
                "avg_pinned_wait_ms": round(avg_pinned, 2) if avg_pinned is not None else None,
                "avg_normal_wait_ms": round(avg_normal, 2) if avg_normal is not None else None,
                "sample_count_pinned": len(self._pinned_wait_times),
                "sample_count_normal": len(self._normal_wait_times),
            }

    def invalidate(self):
        """Reset singleton state and force config reload on the next call.

        This is the lifecycle/test reset for a process-wide singleton. Previously it reset
        only the config timestamp, so counters and wait samples leaked between callers and
        made both telemetry and tests order-dependent.
        """
        with self._lock:
            self._last_config_load = 0
            self._enabled = False
            self._pinned_prefixes = []
            self._min_roi = None
            self._total_pinned = 0
            self._total_pinned_by_roi = 0
            self._pinned_wait_times = []
            self._normal_wait_times = []


# Module-level singleton
_priority_queue = _PriorityQueue()


def acquire():
    """Get the singleton priority queue instance."""
    return _priority_queue


def classify_task(task):
    """Classify a task as pinned or normal. Delegates to singleton."""
    return _priority_queue.classify_task(task)


def dispatch(task):
    """Dispatch a task to appropriate queue lane. Delegates to singleton."""
    return _priority_queue.dispatch(task)


def record_wait_time(task, wait_ms):
    """Record actual wait time for a task. Delegates to singleton."""
    return _priority_queue.record_wait_time(task, wait_ms)


def stats():
    """Return queue statistics. Delegates to singleton."""
    return _priority_queue.stats()


if __name__ == "__main__":
    import json
    # Quick diagnostic: show current priority queue state
    result = stats()
    print(json.dumps(result, indent=2, default=str))
