#!/usr/bin/env python3
"""
failsoft.py - decorator-based fail-soft error handling for the orchestrator.

Slice-3: replaces ad-hoc try/except blocks with a unified decorator that:
  - Catches all exceptions and returns a safe default instead of crashing
  - Logs structured error context (function name, args summary, traceback)
  - Tracks error frequency per function for monitoring
  - Supports configurable retry with exponential backoff
  - Integrates with proactive_error_resolver for pattern detection

Usage:
    from failsoft import failsoft

    @failsoft(default="", retries=1)
    def risky_operation(task_id):
        ...

    @failsoft(default=[], retries=2, backoff=1.0)
    def fetch_tasks():
        ...
"""
import functools, os, sys, threading, time, traceback, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import log as _log_mod
_log = _log_mod.get("failsoft")

_ENABLED = os.environ.get("ORCH_FAILSOFT_ENABLED", "true").lower() in ("true", "1")
_MAX_RETRIES = int(os.environ.get("ORCH_FAILSOFT_MAX_RETRIES", "3"))

_lock = threading.Lock()
_error_counts = collections.Counter()  # fn_name -> count
_last_errors = {}  # fn_name -> (timestamp, error_str)
_WINDOW_SEC = 300  # 5-minute sliding window for frequency


def failsoft(default=None, retries=0, backoff=0.5, log_level="warning"):
    """Decorator: catch exceptions, return default, log, optionally retry.

    Args:
        default: value to return on failure (use callable for mutable defaults)
        retries: number of retry attempts before returning default (0 = no retry)
        backoff: seconds between retries (doubles each attempt)
        log_level: "warning", "error", or "debug"
    """
    if retries > _MAX_RETRIES:
        retries = _MAX_RETRIES

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            if not _ENABLED:
                return fn(*args, **kwargs)

            last_exc = None
            attempts = 1 + max(0, retries)
            delay = backoff

            for attempt in range(attempts):
                try:
                    return fn(*args, **kwargs)
                except Exception as exc:
                    last_exc = exc
                    fn_name = fn.__qualname__
                    with _lock:
                        _error_counts[fn_name] += 1
                        _last_errors[fn_name] = (time.time(), str(exc))

                    if attempt < attempts - 1:
                        _log.debug("failsoft retry %d/%d for %s: %s",
                                   attempt + 1, retries, fn_name, exc)
                        time.sleep(delay)
                        delay *= 2
                    else:
                        tb = traceback.format_exc()
                        getattr(_log, log_level, _log.warning)(
                            "failsoft: %s failed after %d attempt(s): %s\n%s",
                            fn_name, attempts, exc, tb[:500])

            # Return safe default
            if callable(default) and not isinstance(default, (str, int, float, bool, type(None))):
                return default()
            return default

        wrapper._failsoft = True
        return wrapper
    return decorator


def stats():
    """Return error frequency stats for monitoring."""
    with _lock:
        cutoff = time.time() - _WINDOW_SEC
        return {
            "total_errors": sum(_error_counts.values()),
            "by_function": dict(_error_counts.most_common(20)),
            "recent": {k: v for k, (t, v) in _last_errors.items() if t > cutoff},
        }


def reset():
    """Reset counters (for testing)."""
    with _lock:
        _error_counts.clear()
        _last_errors.clear()
