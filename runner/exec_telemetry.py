#!/usr/bin/env python3
"""
exec_telemetry.py — execution pipeline instrumentation.

Records per-task timing for every hook in the pre-execution chain, plus failure
attribution (which hook killed/requeued the task). This data feeds the dashboard
so operators can see where the 72% silent failures originate and which hooks are
worth the latency they add.

Usage in runner.py:
    import exec_telemetry
    _tel = exec_telemetry.TaskTelemetry(task_id)
    with _tel.hook("fleet_topology"):
        ...  # hook code
    _tel.finish(outcome="executed" | "requeued" | "blocked")
    # Writes to Supabase exec_telemetry table
"""
import os, sys, time, threading, json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_ENABLED = None
_log = None


def _enabled():
    global _ENABLED
    if _ENABLED is None:
        _ENABLED = os.environ.get("ORCH_HOOK_TELEMETRY", "true").lower() in ("true", "1", "yes")
    return _ENABLED


def _logger():
    global _log
    if _log is None:
        import logging
        _log = logging.getLogger("exec_telemetry")
    return _log


class HookTimer:
    """Context manager that records a hook's duration and outcome."""
    __slots__ = ("name", "t0", "duration_ms", "outcome", "error")

    def __init__(self, name):
        self.name = name
        self.t0 = 0.0
        self.duration_ms = 0
        self.outcome = "ok"
        self.error = None

    def __enter__(self):
        self.t0 = time.time()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.duration_ms = int((time.time() - self.t0) * 1000)
        if exc_type:
            self.outcome = "error"
            self.error = str(exc_val)[:200] if exc_val else exc_type.__name__
        return False  # don't suppress exceptions


class TaskTelemetry:
    """Per-task telemetry collector.  Accumulates hook timings, writes on finish()."""

    def __init__(self, task_id, slug=""):
        self.task_id = task_id
        self.slug = slug
        self.hooks = []  # list of {name, duration_ms, outcome, error}
        self.t0 = time.time()
        self._requeue_hook = None

    def hook(self, name):
        """Return a context manager that records this hook's timing."""
        timer = HookTimer(name)
        self.hooks.append(timer)
        return timer

    def record_requeue(self, hook_name, reason=""):
        """Record which hook caused a task to be requeued."""
        self._requeue_hook = hook_name

    def finish(self, outcome="executed", note=""):
        """Write telemetry to Supabase."""
        if not _enabled():
            return
        total_ms = int((time.time() - self.t0) * 1000)
        hook_data = []
        for h in self.hooks:
            hook_data.append({
                "name": h.name,
                "ms": h.duration_ms,
                "outcome": h.outcome,
                "error": h.error,
            })

        # Sort by duration descending for quick diagnosis
        hook_data.sort(key=lambda x: x["ms"], reverse=True)

        record = {
            "task_id": str(self.task_id),
            "slug": self.slug,
            "outcome": outcome,
            "total_prehook_ms": total_ms,
            "hook_count": len(hook_data),
            "slowest_hook": hook_data[0]["name"] if hook_data else "",
            "slowest_ms": hook_data[0]["ms"] if hook_data else 0,
            "requeue_hook": self._requeue_hook or "",
            "hooks_json": json.dumps(hook_data[:20]),  # top 20 by duration
            "note": note[:500],
            "created_at": "now()",
        }

        try:
            import db
            db.insert("exec_telemetry", record)
        except Exception as e:
            _logger().debug("exec_telemetry write failed: %s", e)

    def summary(self):
        """Return a human-readable summary for log notes."""
        total = sum(h.duration_ms for h in self.hooks)
        slow = sorted(self.hooks, key=lambda h: h.duration_ms, reverse=True)
        top3 = ", ".join(f"{h.name}={h.duration_ms}ms" for h in slow[:3])
        errors = [h for h in self.hooks if h.outcome == "error"]
        err_str = f", {len(errors)} errors" if errors else ""
        return f"hooks={len(self.hooks)} total={total}ms top=[{top3}]{err_str}"


# ── Module-level convenience ──────────────────────────────────────────────

def start(task_id, slug=""):
    """Create a new TaskTelemetry instance."""
    return TaskTelemetry(task_id, slug)
