#!/usr/bin/env python3
"""
error_handling_utils.py - structured error wrapper and retry helper.

Provides:
  - StructuredError: wraps raw exceptions with category, severity, retryable flag,
    and a chain of context breadcrumbs so callers never need to parse tracebacks.
  - retry_with_backoff: generic retry helper with exponential backoff, jitter,
    and transient-vs-permanent classification to avoid wasting retries on
    permanent failures.

Fail-soft: all public functions return sensible defaults on internal errors.
Thread-safe.

Env vars:
    ORCH_RETRY_MAX_ATTEMPTS   default 3
    ORCH_RETRY_BASE_DELAY_S   default 1.0
    ORCH_RETRY_MAX_DELAY_S    default 30.0
"""
import os, sys, time, random, functools, traceback, threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

MAX_ATTEMPTS = int(os.environ.get("ORCH_RETRY_MAX_ATTEMPTS", "3"))
BASE_DELAY = float(os.environ.get("ORCH_RETRY_BASE_DELAY_S", "1.0"))
MAX_DELAY = float(os.environ.get("ORCH_RETRY_MAX_DELAY_S", "30.0"))

# ---------- StructuredError ----------

class StructuredError:
    """Immutable wrapper around a raw exception with classification metadata."""

    __slots__ = ("original", "category", "severity", "retryable", "context", "timestamp", "tb")

    def __init__(self, original, *, category="unknown", severity="error",
                 retryable=False, context="", tb=None):
        self.original = original
        self.category = category
        self.severity = severity
        self.retryable = retryable
        self.context = context
        self.timestamp = time.time()
        self.tb = tb or ""

    def to_dict(self):
        return {
            "error": str(self.original),
            "type": type(self.original).__name__,
            "category": self.category,
            "severity": self.severity,
            "retryable": self.retryable,
            "context": self.context,
            "timestamp": self.timestamp,
        }

    def __str__(self):
        return (f"StructuredError({self.category}/{self.severity}, "
                f"retryable={self.retryable}): {self.original}")

    def __repr__(self):
        return self.__str__()


def wrap_error(exc, *, context="", category=None, severity=None, retryable=None):
    """Wrap a raw exception into a StructuredError with auto-classification.

    If category/severity/retryable are not provided, they are inferred from
    the exception type and message using lightweight heuristics.
    """
    try:
        msg = str(exc).lower()
        tb = traceback.format_exc() if sys.exc_info()[2] else ""

        if category is None:
            category = _infer_category(exc, msg)
        if severity is None:
            severity = _infer_severity(category)
        if retryable is None:
            retryable = category in ("transient", "resource")

        return StructuredError(exc, category=category, severity=severity,
                               retryable=retryable, context=context, tb=tb)
    except Exception:
        # fail-soft: return a minimal wrapper
        return StructuredError(exc, context=context)


_TRANSIENT_WORDS = ("timeout", "connection", "reset", "rate limit", "429",
                    "503", "overload", "temporary", "econnrefused", "retry")
_RESOURCE_WORDS = ("memory", "oom", "quota", "disk full", "no space", "budget")
_PERMISSION_WORDS = ("permission", "denied", "forbidden", "403", "unauthorized")


def _infer_category(exc, msg):
    # PermissionError is a subclass of OSError, so check it first
    if isinstance(exc, PermissionError):
        return "permission"
    if isinstance(exc, MemoryError):
        return "resource"
    if isinstance(exc, (ConnectionError, TimeoutError, OSError)):
        return "transient"
    if isinstance(exc, (ValueError, TypeError, KeyError, AttributeError)):
        return "logic"
    if any(w in msg for w in _TRANSIENT_WORDS):
        return "transient"
    if any(w in msg for w in _RESOURCE_WORDS):
        return "resource"
    if any(w in msg for w in _PERMISSION_WORDS):
        return "permission"
    return "unknown"


def _infer_severity(category):
    return {"transient": "warning", "resource": "error", "permission": "fatal",
            "logic": "error"}.get(category, "error")


# ---------- retry_with_backoff ----------

_lock = threading.Lock()
_retry_stats = {"attempts": 0, "successes": 0, "exhausted": 0}


def retry_with_backoff(fn=None, *, max_attempts=None, base_delay=None,
                       max_delay=None, on_transient_only=True):
    """Retry a function with exponential backoff and jitter.

    Can be used as a decorator or called directly:
        @retry_with_backoff
        def flaky(): ...

        @retry_with_backoff(max_attempts=5)
        def flaky(): ...

        result = retry_with_backoff(flaky, max_attempts=5)
    """
    _max = max_attempts or MAX_ATTEMPTS
    _base = base_delay or BASE_DELAY
    _cap = max_delay or MAX_DELAY

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(1, _max + 1):
                try:
                    result = func(*args, **kwargs)
                    with _lock:
                        _retry_stats["attempts"] += attempt
                        _retry_stats["successes"] += 1
                    return result
                except Exception as exc:
                    last_exc = exc
                    se = wrap_error(exc, context=f"retry attempt {attempt}/{_max}")

                    if on_transient_only and not se.retryable:
                        # permanent error — don't waste retries
                        raise

                    if attempt < _max:
                        delay = min(_cap, _base * (2 ** (attempt - 1)))
                        delay *= (0.5 + random.random())  # jitter
                        time.sleep(delay)

            with _lock:
                _retry_stats["attempts"] += _max
                _retry_stats["exhausted"] += 1
            raise last_exc  # type: ignore[misc]
        return wrapper

    # Handle both @retry_with_backoff and @retry_with_backoff(...)
    if fn is not None and callable(fn):
        return decorator(fn)
    return decorator


def retry_stats():
    """Return a copy of retry statistics."""
    with _lock:
        return dict(_retry_stats)


def clear_stats():
    """Reset retry statistics."""
    with _lock:
        _retry_stats["attempts"] = 0
        _retry_stats["successes"] = 0
        _retry_stats["exhausted"] = 0
