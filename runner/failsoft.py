#!/usr/bin/env python3
"""
failsoft.py - fail-soft error handling utilities for critical operations.

Provides decorators and context managers that catch exceptions in database
operations and external API calls, log them for review, and return sensible
defaults instead of crashing the process.

Usage:
    @failsoft(default=None)
    def fetch_data():
        return db.select("tasks", ...)

    with failsoft_ctx("merge_train.integrate"):
        risky_operation()

Conventions (from CLAUDE.md):
- Return empty string "" or sensible defaults on any error
- Never raise on bad input (None, missing path, permission errors)
- Log errors for review without crashing
"""
import os, sys, time, functools, threading, traceback
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import log as _log_mod

_log = _log_mod.get("failsoft")

_ENABLED = os.environ.get("ORCH_FAILSOFT_ENABLED", "true").lower() == "true"
_MAX_LOG_ERRORS = int(os.environ.get("ORCH_FAILSOFT_MAX_LOG", "500") or 500)

_lock = threading.Lock()
_error_log = []  # recent errors for stats/review
_stats = {
    "total_caught": 0,
    "by_source": {},  # source_name -> count
}


def _record_error(source, exc, tb_str):
    """Record an error for later review without raising."""
    with _lock:
        _stats["total_caught"] += 1
        _stats["by_source"][source] = _stats["by_source"].get(source, 0) + 1
        if len(_error_log) < _MAX_LOG_ERRORS:
            _error_log.append({
                "source": source,
                "error": str(exc),
                "type": type(exc).__name__,
                "traceback": tb_str[:500],
                "ts": time.time(),
            })
    _log.warning("failsoft caught in %s: %s: %s", source, type(exc).__name__, exc)


def failsoft(default=None, source=None):
    """Decorator: catch all exceptions, log them, return default.

    @failsoft(default=[])
    def get_tasks():
        return db.select("tasks", ...)
    """
    def decorator(fn):
        _source = source or f"{fn.__module__}.{fn.__qualname__}"

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            if not _ENABLED:
                return fn(*args, **kwargs)
            try:
                return fn(*args, **kwargs)
            except Exception as exc:
                tb_str = traceback.format_exc()
                _record_error(_source, exc, tb_str)
                return default() if callable(default) else default

        return wrapper
    return decorator


def failsoft_call(fn, *args, default=None, source="failsoft_call", **kwargs):
    """Call fn(*args, **kwargs) with fail-soft wrapping. Returns default on error."""
    if not _ENABLED:
        return fn(*args, **kwargs)
    try:
        return fn(*args, **kwargs)
    except Exception as exc:
        tb_str = traceback.format_exc()
        _record_error(source, exc, tb_str)
        return default() if callable(default) else default


class failsoft_ctx:
    """Context manager for fail-soft blocks.

    with failsoft_ctx("merge_train.integrate"):
        do_risky_thing()
    # execution continues even if do_risky_thing() raised
    """

    def __init__(self, source="failsoft_ctx", default=None):
        self.source = source
        self.default = default
        self.error = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None and _ENABLED:
            tb_str = traceback.format_exc()
            _record_error(self.source, exc_val, tb_str)
            self.error = exc_val
            return True  # suppress exception
        return False


def failsoft_db(fn):
    """Specialized decorator for database operations. Returns None on error."""
    return failsoft(default=None, source=f"db.{fn.__name__}")(fn)


def failsoft_api(fn):
    """Specialized decorator for external API calls. Returns None on error."""
    return failsoft(default=None, source=f"api.{fn.__name__}")(fn)


def stats():
    """Return fail-soft statistics for monitoring."""
    with _lock:
        return {
            "total_caught": _stats["total_caught"],
            "by_source": dict(_stats["by_source"]),
            "recent_errors": len(_error_log),
        }


def recent_errors(limit=20):
    """Return recent errors for review."""
    with _lock:
        return list(_error_log[-limit:])


def clear():
    """Reset stats and error log."""
    with _lock:
        _error_log.clear()
        _stats["total_caught"] = 0
        _stats["by_source"].clear()
