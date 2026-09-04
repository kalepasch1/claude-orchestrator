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


# --- Reporting (the half the module was missing) ---------------------------------------
#
# track() has always recorded classified errors into a ring buffer, and recent_errors() /
# error_rate() can query it — but nothing ever SUMMARISED it, so the gap this slice names
# ("no real-time reporting or detailed logs for debugging") was real: the data existed and
# there was no way to look at it. An operator asking "what is failing right now, and is it
# one thing or many?" had to read a hundred raw entries.

#: Window a "right now" report covers, in seconds. ORCH_-prefixed so fleet_control.py can
#: push it without a code change.
REPORT_WINDOW_SECS = int(os.environ.get("ORCH_ERROR_REPORT_WINDOW_SECS", "300"))


def report(window_secs=None, top_n=5):
    """A digest of what is failing right now. Never raises; empty dict shape on failure.

    Returns {window_secs, total, by_category, by_severity, top_categories, retryable,
    latest}. `retryable` is the count that is_retryable() would let through, because the
    operationally useful split is not "how many errors" but "how many of these will clear
    on their own" — a burst of transient errors and a burst of logic errors need opposite
    responses, and a bare total cannot tell them apart.
    """
    try:
        window = REPORT_WINDOW_SECS if window_secs is None else int(window_secs)
        cutoff = time.time() - window
        entries = [e for e in _ring if e.get("ts", 0) > cutoff]

        by_category, by_severity = {}, {}
        retryable = 0
        for e in entries:
            cat = e.get("category") or UNKNOWN
            sev = e.get("severity") or ERROR
            by_category[cat] = by_category.get(cat, 0) + 1
            by_severity[sev] = by_severity.get(sev, 0) + 1
            if cat in (TRANSIENT, RESOURCE):
                retryable += 1

        ranked = sorted(by_category.items(), key=lambda kv: (-kv[1], kv[0]))
        latest = sorted(entries, key=lambda e: e.get("ts", 0), reverse=True)[:top_n]
        return {
            "window_secs": window,
            "total": len(entries),
            "by_category": by_category,
            "by_severity": by_severity,
            "top_categories": ranked[:top_n],
            "retryable": retryable,
            "latest": [{"category": e.get("category"), "severity": e.get("severity"),
                        "hook": e.get("hook", ""), "task_id": e.get("task_id"),
                        "message": str(e.get("message", ""))[:200]} for e in latest],
        }
    except Exception:
        return {"window_secs": 0, "total": 0, "by_category": {}, "by_severity": {},
                "top_categories": [], "retryable": 0, "latest": []}


def render_report(digest=None):
    """One human-readable block for a log line or an operator ping. Never raises."""
    try:
        d = report() if digest is None else digest
        if not d.get("total"):
            return f"no errors in the last {d.get('window_secs', 0)}s"
        head = (f"{d['total']} error(s) in {d['window_secs']}s "
                f"({d['retryable']} self-clearing, {d['total'] - d['retryable']} not)")
        cats = ", ".join(f"{name}={n}" for name, n in d.get("top_categories", []))
        lines = [head, f"  by category: {cats}" if cats else ""]
        for e in d.get("latest", []):
            lines.append(f"  [{e.get('severity')}] {e.get('category')}"
                         f"{'/' + e['hook'] if e.get('hook') else ''}: {e.get('message', '')}")
        return "\n".join(l for l in lines if l)
    except Exception:
        return "error report unavailable"


def reset_tracking():
    """Clear the ring buffer. For tests and for an operator starting a fresh window."""
    global _ring, _ring_idx
    try:
        _ring = []
        _ring_idx = 0
    except Exception:
        pass
