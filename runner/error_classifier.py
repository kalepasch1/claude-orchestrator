#!/usr/bin/env python3
"""
error_classifier.py — Structured error classification for runner error handling.

Instead of bare `except Exception` blocks that swallow errors silently, this module
provides classification, severity assessment, and recommended actions for errors
encountered during task execution. Integrates with error_outcome_tracker for
fleet-wide error pattern learning.

Fail-soft: every public function returns a sensible default on any internal error.
"""
import os
import re
import sys
import traceback
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# --- Error categories ---
TRANSIENT = "transient"        # retry-safe: network, rate limit, overload
RESOURCE = "resource"          # capacity/budget/memory
MODEL = "model"                # model-specific: context too long, bad response
TOOLCHAIN = "toolchain"        # missing tools, broken build env
CONFLICT = "conflict"          # git conflicts, branch issues
PERMISSION = "permission"      # auth, secrets, access denied
LOGIC = "logic"                # code/logic errors in the orchestrator itself
UNKNOWN = "unknown"            # unclassifiable

# --- Severity levels ---
FATAL = "fatal"       # stop immediately, no retry
ERROR = "error"       # task fails, may retry
WARNING = "warning"   # log and continue
INFO = "info"         # informational, no action needed

# --- Classification patterns ---
_PATTERNS = [
    (TRANSIENT, re.compile(r"connection reset|urlopen|errno|timeout|overload|503|"
                           r"high demand|rate.?limit|429|too many requests|"
                           r"temporarily.*limit|ECONNREFUSED|ETIMEDOUT", re.I)),
    (RESOURCE, re.compile(r"budget cap|capacity circuit|usage limit|out of credits|"
                          r"insufficient_quota|quota|memory|OOM|MemoryError|"
                          r"disk.*full|no space left", re.I)),
    (MODEL, re.compile(r"prompt is too long|context.*limit|max.*tokens|"
                       r"invalid.*response|malformed.*json|single-exchange.*compact|"
                       r"content.*filter|safety.*filter", re.I)),
    (TOOLCHAIN, re.compile(r"command not found|not found.*(npm|yarn|node|python|cargo)|"
                           r"cannot find module|ModuleNotFoundError|ENOENT.*node_modules|"
                           r"nuxt.*not found|vite.*not found|prisma.*not found", re.I)),
    (CONFLICT, re.compile(r"merge conflict|CONFLICT \(content\)|rebase.*conflict|"
                          r"branch.*missing|ref.*not found|detached HEAD", re.I)),
    (PERMISSION, re.compile(r"permission denied|access denied|unauthorized|forbidden|"
                            r"auth.*fail|credential.*miss|secret.*not.*set|"
                            r"EACCES|403", re.I)),
]


def classify(error):
    """Classify an error into category and severity.

    Args:
        error: Exception instance, string, or dict with 'error'/'message' keys.

    Returns:
        dict with keys: category, severity, retryable, message, recommendation
    """
    try:
        msg = _extract_message(error)
        category = UNKNOWN
        for cat, pattern in _PATTERNS:
            if pattern.search(msg):
                category = cat
                break

        severity = _severity_for(category)
        retryable = category in (TRANSIENT, RESOURCE, CONFLICT)

        return {
            "category": category,
            "severity": severity,
            "retryable": retryable,
            "message": msg[:500],
            "recommendation": _recommendation(category, msg),
        }
    except Exception:
        return {
            "category": UNKNOWN,
            "severity": ERROR,
            "retryable": False,
            "message": str(error)[:500] if error else "",
            "recommendation": "Inspect manually",
        }


def _extract_message(error):
    """Extract a string message from various error representations."""
    if isinstance(error, Exception):
        return f"{type(error).__name__}: {error}"
    if isinstance(error, dict):
        return str(error.get("error") or error.get("message") or error.get("note") or error)
    return str(error or "")


def _severity_for(category):
    """Map category to default severity."""
    if category == PERMISSION:
        return FATAL
    if category in (TRANSIENT, RESOURCE, CONFLICT):
        return WARNING
    if category in (MODEL, TOOLCHAIN):
        return ERROR
    return ERROR


def _recommendation(category, msg):
    """Return a short actionable recommendation."""
    recs = {
        TRANSIENT: "Retry after backoff; likely a temporary provider issue",
        RESOURCE: "Check budget/capacity limits; may need to wait or increase quota",
        MODEL: "Reduce prompt size, switch model, or split the task",
        TOOLCHAIN: "Run toolchain check; install missing dependencies",
        CONFLICT: "Rebase on fresh base branch before retrying",
        PERMISSION: "Check credentials and access permissions; may need manual intervention",
        LOGIC: "Orchestrator bug; inspect traceback and fix the runner code",
        UNKNOWN: "Inspect the full error context manually",
    }
    return recs.get(category, recs[UNKNOWN])


def is_retryable(error):
    """Quick check: should this error be retried?"""
    try:
        return classify(error)["retryable"]
    except Exception:
        return False


def safe_error_note(error, prefix="", max_len=400):
    """Build a safe, truncated error note for DB storage.

    Strips tracebacks to essential info, caps length, never raises.
    """
    try:
        cls = classify(error)
        msg = cls["message"][:max_len - len(prefix) - 30]
        return f"{prefix}[{cls['category']}] {msg}"
    except Exception:
        raw = str(error)[:max_len]
        return f"{prefix}{raw}"


# --- Error tracking (in-memory ring buffer for recent errors) ---

_RING_SIZE = int(os.environ.get("ORCH_ERROR_RING_SIZE", "100"))
_ring = []
_ring_idx = 0


def track(error, task_id=None, hook=None):
    """Record an error in the in-memory ring buffer for pattern detection.

    Returns the classification dict. Never raises.
    """
    global _ring_idx
    try:
        cls = classify(error)
        entry = {
            "ts": time.time(),
            "task_id": task_id,
            "hook": hook or "",
            **cls,
        }
        if len(_ring) < _RING_SIZE:
            _ring.append(entry)
        else:
            _ring[_ring_idx % _RING_SIZE] = entry
        _ring_idx += 1
        return cls
    except Exception:
        return classify(error)


def recent_errors(category=None, last_n=20):
    """Return recent tracked errors, optionally filtered by category."""
    try:
        entries = list(_ring)
        if category:
            entries = [e for e in entries if e.get("category") == category]
        return sorted(entries, key=lambda e: e.get("ts", 0), reverse=True)[:last_n]
    except Exception:
        return []


def error_rate(category=None, window_secs=300):
    """Count errors in the last `window_secs` seconds."""
    try:
        cutoff = time.time() - window_secs
        entries = [e for e in _ring if e.get("ts", 0) > cutoff]
        if category:
            entries = [e for e in entries if e.get("category") == category]
        return len(entries)
    except Exception:
        return 0
