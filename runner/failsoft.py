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

#: (timestamp, fn_name) per caught exception, pruned to _WINDOW_SEC on every read
#: and write. This used to be a plain Counter that only ever incremented, so
#: `stats()["total_errors"]` and `["by_function"]` were LIFETIME totals while the
#: module documented a five-minute window and called them "error frequency stats
#: for monitoring". Anything alerting on them would latch after one burst and never
#: recover — the classic never-decaying counter. `recent` was the only field that
#: honoured the window. maxlen is a memory backstop for a pathological error rate;
#: the window is what defines the numbers.
_MAX_TRACKED_EVENTS = 10000
_error_events = collections.deque(maxlen=_MAX_TRACKED_EVENTS)
_last_errors = {}  # fn_name -> (timestamp, error_str)
_WINDOW_SEC = 300  # 5-minute sliding window for frequency


def _prune(now=None):
    """Drop events older than the window. Caller holds _lock."""
    cutoff = (now if now is not None else time.time()) - _WINDOW_SEC
    while _error_events and _error_events[0][0] <= cutoff:
        _error_events.popleft()


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
                    now = time.time()
                    with _lock:
                        _prune(now)
                        _error_events.append((now, fn_name))
                        _last_errors[fn_name] = (now, str(exc))

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
    """Error FREQUENCY over the last _WINDOW_SEC, for monitoring.

    Every field now honours the window. `total_errors` and `by_function` used to
    be lifetime totals taken from a counter nothing ever decremented, so a monitor
    reading them could only ever ratchet upward — one bad minute and the number
    stayed high for the life of the process, which is the opposite of what a
    frequency signal is for.
    """
    now = time.time()
    with _lock:
        _prune(now)
        by_function = collections.Counter(name for _ts, name in _error_events)
        cutoff = now - _WINDOW_SEC
        return {
            "total_errors": len(_error_events),
            "by_function": dict(by_function.most_common(20)),
            "recent": {k: v for k, (t, v) in _last_errors.items() if t > cutoff},
            "window_sec": _WINDOW_SEC,
        }


def reset():
    """Reset counters (for testing)."""
    with _lock:
        _error_events.clear()
        _last_errors.clear()
