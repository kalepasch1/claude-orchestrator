#!/usr/bin/env python3
"""
speculative_executor.py — Speculative parallel executor with dynamic pool sizing.

Slice-1 foundation: accepts a list of task candidates, runs them concurrently
using ThreadPoolExecutor, dynamically adjusts pool size based on system load,
and returns results as they complete.  Higher-priority results can cancel
remaining in-flight work.

Env vars:
    ORCH_SPEC_EXECUTOR_ENABLED      – "true" (default) / "false"
    ORCH_SPEC_EXECUTOR_MIN_WORKERS  – minimum pool threads (default 2)
    ORCH_SPEC_EXECUTOR_MAX_WORKERS  – maximum pool threads (default: cpu_count or 8)
    ORCH_SPEC_EXECUTOR_LOAD_CEILING – cpu% above which pool shrinks (default 80)
    ORCH_SPEC_EXECUTOR_POLL_INTERVAL– seconds between load checks (default 5)
"""
import os
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor, Future, as_completed
from typing import Any, Callable, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import log as _log_mod

_log = _log_mod.get("speculative_executor")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

ENABLED = os.environ.get("ORCH_SPEC_EXECUTOR_ENABLED", "true").lower() == "true"
MIN_WORKERS = int(os.environ.get("ORCH_SPEC_EXECUTOR_MIN_WORKERS", "2"))
MAX_WORKERS = int(os.environ.get("ORCH_SPEC_EXECUTOR_MAX_WORKERS",
                                  str(os.cpu_count() or 8)))
LOAD_CEILING = float(os.environ.get("ORCH_SPEC_EXECUTOR_LOAD_CEILING", "80"))
POLL_INTERVAL = float(os.environ.get("ORCH_SPEC_EXECUTOR_POLL_INTERVAL", "5"))

# ---------------------------------------------------------------------------
# System load helpers
# ---------------------------------------------------------------------------

def _get_cpu_percent() -> float:
    """Return current CPU usage percentage.  Uses psutil if available, falls
    back to os.getloadavg() scaled by cpu_count, or returns 0.0."""
    try:
        import psutil  # type: ignore[import-untyped]
        return psutil.cpu_percent(interval=0.1)
    except ImportError:
        pass
    try:
        load1, _, _ = os.getloadavg()
        cpus = os.cpu_count() or 1
        return min((load1 / cpus) * 100.0, 100.0)
    except (OSError, AttributeError):
        return 0.0


def _recommended_pool_size() -> int:
    """Compute a pool size between MIN_WORKERS and MAX_WORKERS based on load."""
    load = _get_cpu_percent()
    if load >= LOAD_CEILING:
        size = MIN_WORKERS
    elif load <= 10.0:
        size = MAX_WORKERS
    else:
        # Linear interpolation: low load -> more workers
        ratio = 1.0 - (load / LOAD_CEILING)
        size = int(MIN_WORKERS + ratio * (MAX_WORKERS - MIN_WORKERS))
    size = max(MIN_WORKERS, min(MAX_WORKERS, size))
    _log.debug("cpu=%.1f%% recommended_pool=%d", load, size)
    return size


# ---------------------------------------------------------------------------
# Task candidate schema
# ---------------------------------------------------------------------------

class TaskCandidate:
    """Lightweight wrapper for a unit of speculative work."""

    __slots__ = ("id", "priority", "fn", "args", "kwargs", "timeout")

    def __init__(self, task_id: str, fn: Callable[..., Any], *,
                 priority: int = 0, args: tuple = (), kwargs: Optional[dict] = None,
                 timeout: Optional[float] = None):
        self.id = task_id
        self.priority = priority          # higher = more important
        self.fn = fn
        self.args = args
        self.kwargs = kwargs or {}
        self.timeout = timeout


class TaskResult:
    """Outcome of a single speculative task."""

    __slots__ = ("task_id", "priority", "value", "error", "cancelled", "elapsed")

    def __init__(self, task_id: str, priority: int, *, value: Any = None,
                 error: Optional[Exception] = None, cancelled: bool = False,
                 elapsed: float = 0.0):
        self.task_id = task_id
        self.priority = priority
        self.value = value
        self.error = error
        self.cancelled = cancelled
        self.elapsed = elapsed

    @property
    def ok(self) -> bool:
        return self.error is None and not self.cancelled

    def __repr__(self) -> str:
        status = "ok" if self.ok else ("cancelled" if self.cancelled else "error")
        return f"<TaskResult {self.task_id} {status} {self.elapsed:.2f}s>"


# ---------------------------------------------------------------------------
# Core executor
# ---------------------------------------------------------------------------

_stats_lock = threading.Lock()
_stats: Dict[str, int] = {
    "submitted": 0,
    "completed": 0,
    "cancelled": 0,
    "errors": 0,
    "early_exits": 0,
}


def get_stats() -> Dict[str, int]:
    """Return a snapshot of executor statistics."""
    with _stats_lock:
        return dict(_stats)


def _inc(key: str, n: int = 1) -> None:
    with _stats_lock:
        _stats[key] = _stats.get(key, 0) + n


def execute_speculative(
    candidates: List[TaskCandidate],
    *,
    cancel_on_priority: bool = True,
    max_results: Optional[int] = None,
) -> List[TaskResult]:
    """Run *candidates* in parallel, returning results as they finish.

    Parameters
    ----------
    candidates:
        Tasks to execute speculatively.
    cancel_on_priority:
        If True, when a result from a higher-priority task arrives, cancel all
        remaining lower-priority tasks.
    max_results:
        Stop after collecting this many successful results (None = all).

    Returns
    -------
    List of TaskResult, ordered by completion time.
    """
    if not ENABLED:
        _log.info("speculative executor disabled; returning empty")
        return []

    if not candidates:
        return []

    pool_size = _recommended_pool_size()
    pool_size = min(pool_size, len(candidates))
    _log.info("launching %d candidates with pool_size=%d (cancel_on_priority=%s)",
              len(candidates), pool_size, cancel_on_priority)

    results: List[TaskResult] = []
    best_priority = float("-inf")
    futures: Dict[Future, TaskCandidate] = {}

    executor = ThreadPoolExecutor(max_workers=pool_size,
                                  thread_name_prefix="spec-exec")
    try:
        # Submit all candidates
        for c in candidates:
            fut = executor.submit(_run_candidate, c)
            futures[fut] = c
            _inc("submitted")

        # Collect as they complete
        for fut in as_completed(futures, timeout=None):
            candidate = futures[fut]
            t_result = _future_to_result(fut, candidate)
            results.append(t_result)

            if t_result.ok:
                _inc("completed")
                _log.info("task %s completed (priority=%d, %.2fs)",
                          t_result.task_id, t_result.priority, t_result.elapsed)

                # Early cancellation logic
                if cancel_on_priority and t_result.priority > best_priority:
                    best_priority = t_result.priority
                    _cancel_lower_priority(futures, best_priority)

                if max_results and sum(1 for r in results if r.ok) >= max_results:
                    _log.info("reached max_results=%d; cancelling remaining", max_results)
                    _inc("early_exits")
                    _cancel_all_pending(futures)
                    break
            elif t_result.cancelled:
                _inc("cancelled")
            else:
                _inc("errors")
                _log.warning("task %s failed: %s", t_result.task_id, t_result.error)
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    _log.info("speculative batch done: %d results (%d ok, %d cancelled, %d errors)",
              len(results),
              sum(1 for r in results if r.ok),
              sum(1 for r in results if r.cancelled),
              sum(1 for r in results if r.error and not r.cancelled))
    return results


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _run_candidate(candidate: TaskCandidate) -> Any:
    """Execute a single candidate's callable."""
    return candidate.fn(*candidate.args, **candidate.kwargs)


def _future_to_result(fut: Future, candidate: TaskCandidate) -> TaskResult:
    """Convert a completed Future into a TaskResult."""
    elapsed = 0.0
    if fut.cancelled():
        return TaskResult(candidate.id, candidate.priority, cancelled=True)
    try:
        value = fut.result(timeout=candidate.timeout)
        return TaskResult(candidate.id, candidate.priority, value=value)
    except Exception as exc:
        return TaskResult(candidate.id, candidate.priority, error=exc)


def _cancel_lower_priority(futures: Dict[Future, TaskCandidate],
                           threshold: int) -> None:
    """Cancel futures whose candidate priority is below *threshold*."""
    for fut, cand in futures.items():
        if cand.priority < threshold and not fut.done():
            if fut.cancel():
                _log.debug("cancelled lower-priority task %s (pri=%d < %d)",
                           cand.id, cand.priority, threshold)


def _cancel_all_pending(futures: Dict[Future, TaskCandidate]) -> None:
    """Best-effort cancel of all unfinished futures."""
    for fut in futures:
        if not fut.done():
            fut.cancel()


# ---------------------------------------------------------------------------
# Adaptive pool monitor (background thread for long-running batches)
# ---------------------------------------------------------------------------

class _AdaptiveMonitor(threading.Thread):
    """Periodically logs load and recommended pool size.  Slice-1 is
    observation-only; slice-2 will hot-resize the pool."""

    daemon = True

    def __init__(self) -> None:
        super().__init__(name="spec-exec-monitor")
        self._stop_evt = threading.Event()

    def run(self) -> None:
        while not self._stop_evt.wait(POLL_INTERVAL):
            size = _recommended_pool_size()
            _log.debug("adaptive monitor: recommended_pool=%d", size)

    def stop(self) -> None:
        self._stop_evt.set()


# Module-level monitor instance (started lazily)
_monitor: Optional[_AdaptiveMonitor] = None
_monitor_lock = threading.Lock()


def start_monitor() -> None:
    """Start the adaptive load monitor (idempotent)."""
    global _monitor
    with _monitor_lock:
        if _monitor is None or not _monitor.is_alive():
            _monitor = _AdaptiveMonitor()
            _monitor.start()
            _log.info("adaptive monitor started (poll=%.1fs)", POLL_INTERVAL)


def stop_monitor() -> None:
    """Stop the adaptive load monitor."""
    global _monitor
    with _monitor_lock:
        if _monitor is not None:
            _monitor.stop()
            _monitor = None
            _log.info("adaptive monitor stopped")
