#!/usr/bin/env python3
"""
error_pattern_analyzer.py - pattern-based error log analysis with adaptive config adjustment.

Analyzes error logs to detect recurring failure patterns and recommends (or auto-applies)
configuration changes to prevent repeat failures.  Uses lightweight statistical methods
(frequency counting, recency weighting, pattern co-occurrence) rather than heavy ML models,
keeping the module dependency-free and fail-soft.

When a high-risk pattern is detected (e.g. repeated OOM, build timeouts on a specific
project, or recurring merge conflicts on the same file), the analyzer can:
  1. Emit a structured recommendation (always)
  2. Auto-adjust fleet_config via DB if ORCH_ERROR_AUTO_ADJUST=true

Usage:
    import error_pattern_analyzer
    recs = error_pattern_analyzer.analyze_recent(hours=4)
    # recs: list of {pattern, count, severity, recommendation, auto_applied}
"""
import os
import re
import sys
import threading
import time
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

AUTO_ADJUST = os.environ.get("ORCH_ERROR_AUTO_ADJUST", "false").lower() in ("1", "true", "yes")
MIN_PATTERN_COUNT = int(os.environ.get("ORCH_ERROR_MIN_PATTERN", "3"))
LOOKBACK_HOURS = int(os.environ.get("ORCH_ERROR_LOOKBACK_HOURS", "4"))
HIGH_RISK_THRESHOLD = int(os.environ.get("ORCH_ERROR_HIGH_RISK_THRESHOLD", "5"))

_lock = threading.Lock()
_pattern_history: dict = defaultdict(list)  # pattern_key -> [timestamp, ...]

# Known high-risk patterns and their recommended config adjustments
_RISK_PATTERNS = {
    "oom": {
        "regex": re.compile(r"out of memory|oom|memory.*exhaust|cannot allocate|heap.*limit", re.I),
        "config_key": "ORCH_MAX_CONCURRENT_TASKS",
        "adjustment": lambda current: str(max(1, int(current or "4") - 1)),
        "recommendation": "Reduce concurrent task count to lower memory pressure",
        "severity": "high",
    },
    "build_timeout": {
        "regex": re.compile(r"build.*timeout|timed out.*build|npm.*SIGTERM|yarn.*timeout", re.I),
        "config_key": "ORCH_BUILD_TIMEOUT_SECONDS",
        "adjustment": lambda current: str(int(current or "300") + 120),
        "recommendation": "Increase build timeout to accommodate slow builds",
        "severity": "medium",
    },
    "rate_limit": {
        "regex": re.compile(r"rate.?limit|429|too many requests|throttl", re.I),
        "config_key": "ORCH_POLL_INTERVAL_SECONDS",
        "adjustment": lambda current: str(min(120, int(current or "30") + 15)),
        "recommendation": "Increase poll interval to reduce API pressure",
        "severity": "medium",
    },
    "merge_conflict": {
        "regex": re.compile(r"merge conflict|CONFLICT.*content|cannot merge|rebase.*failed", re.I),
        "config_key": None,
        "adjustment": None,
        "recommendation": "Serialize tasks targeting the same files; consider smaller slices",
        "severity": "high",
    },
    "disk_full": {
        "regex": re.compile(r"no space left|disk full|ENOSPC|cannot write", re.I),
        "config_key": "ORCH_WORKTREE_CLEANUP_AGGRESSIVE",
        "adjustment": lambda _: "true",
        "recommendation": "Enable aggressive worktree cleanup to free disk space",
        "severity": "critical",
    },
}


def _classify(note: str) -> list:
    """Return list of matching risk pattern keys for the given error note."""
    if not note:
        return []
    matches = []
    for key, spec in _RISK_PATTERNS.items():
        if spec["regex"].search(note):
            matches.append(key)
    return matches


def record(note: str, task_id: str = "") -> list:
    """Record an error occurrence and return any matching pattern keys.

    Fail-soft: never raises.
    """
    try:
        keys = _classify(note)
        now = time.time()
        with _lock:
            for k in keys:
                _pattern_history[k].append(now)
                # Prune old entries (older than lookback window)
                cutoff = now - (LOOKBACK_HOURS * 3600)
                _pattern_history[k] = [t for t in _pattern_history[k] if t > cutoff]
        return keys
    except Exception:
        return []


def analyze_recent(hours: int = None) -> list:
    """Analyze recent error patterns and return recommendations.

    Returns list of dicts: {pattern, count, severity, recommendation, auto_applied}
    """
    hours = hours or LOOKBACK_HOURS
    cutoff = time.time() - (hours * 3600)
    recommendations = []

    with _lock:
        for key, timestamps in _pattern_history.items():
            recent = [t for t in timestamps if t > cutoff]
            if len(recent) < MIN_PATTERN_COUNT:
                continue

            spec = _RISK_PATTERNS.get(key, {})
            rec = {
                "pattern": key,
                "count": len(recent),
                "severity": spec.get("severity", "medium"),
                "recommendation": spec.get("recommendation", ""),
                "auto_applied": False,
            }

            # Auto-adjust config if enabled and pattern exceeds high-risk threshold
            if (AUTO_ADJUST and len(recent) >= HIGH_RISK_THRESHOLD
                    and spec.get("config_key") and spec.get("adjustment")):
                rec["auto_applied"] = _apply_config(spec["config_key"], spec["adjustment"])

            recommendations.append(rec)

    return sorted(recommendations, key=lambda r: r["count"], reverse=True)


def _apply_config(config_key: str, adjustment_fn) -> bool:
    """Apply a config adjustment via fleet_config. Returns True on success."""
    try:
        import db
        current = ""
        try:
            rows = db.query("SELECT value FROM fleet_config WHERE key = %s", (config_key,))
            if rows:
                current = rows[0].get("value", "")
        except Exception:
            pass
        new_value = adjustment_fn(current)
        db.query(
            "INSERT INTO fleet_config (key, value) VALUES (%s, %s) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
            (config_key, new_value),
        )
        return True
    except Exception:
        return False


def stats() -> dict:
    """Return current pattern counts for observability."""
    with _lock:
        return {k: len(v) for k, v in _pattern_history.items()}


def reset():
    """Clear all recorded patterns (for testing)."""
    with _lock:
        _pattern_history.clear()
