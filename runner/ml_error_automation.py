#!/usr/bin/env python3
"""
ml_error_automation.py - Machine learning-based automated error recovery.

Learns from historical error patterns and automates recovery for 3 key error classes:
  1. Transient errors (rate limits, timeouts) → auto-retry with backoff
  2. Conflict errors (merge conflicts, branch issues) → auto-rebase/reset
  3. Resource errors (quota, memory) → auto-queue with delay

Uses pattern frequency analysis to identify recoverable errors and applies
targeted recovery strategies based on historical success rates.

Thread-safe. Fail-soft: returns sensible defaults on any internal error.

Env vars:
    ORCH_ML_AUTO_RECOVERY_ENABLED    default true
    ORCH_ML_ERROR_PATTERN_HISTORY_SIZE  default 500
    ORCH_ML_SUCCESS_RATE_THRESHOLD   default 0.7 (70% success rate required)
    ORCH_ML_MIN_PATTERN_OBSERVATIONS  default 5 (need at least 5 occurrences)
"""
import os, sys, time, json, threading, collections, re, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import error_classifier as ec

ENABLED = os.environ.get("ORCH_ML_AUTO_RECOVERY_ENABLED", "true").lower() in ("true", "1")
HISTORY_SIZE = int(os.environ.get("ORCH_ML_ERROR_PATTERN_HISTORY_SIZE", "500"))
SUCCESS_THRESHOLD = float(os.environ.get("ORCH_ML_SUCCESS_RATE_THRESHOLD", "0.7"))
MIN_OBSERVATIONS = int(os.environ.get("ORCH_ML_MIN_PATTERN_OBSERVATIONS", "5"))

# --- Pattern history and learning ---

_lock = threading.Lock()
_error_history = collections.deque(maxlen=HISTORY_SIZE)
_recovery_outcomes = collections.defaultdict(lambda: {"success": 0, "failure": 0})


class PatternSignature:
    """Identifies an error pattern from an error classification."""

    __slots__ = ("category", "pattern_key", "recoverable")

    def __init__(self, category, pattern_key):
        self.category = category
        self.pattern_key = pattern_key
        self.recoverable = category in ("transient", "conflict", "resource")

    def __hash__(self):
        return hash((self.category, self.pattern_key))

    def __eq__(self, other):
        return (self.category, self.pattern_key) == (other.category, other.pattern_key)

    def __repr__(self):
        return f"PatternSignature({self.category}/{self.pattern_key})"


def _extract_pattern_key(classification):
    """Extract a pattern key from error classification.

    Groups similar errors by their root cause (e.g., "rate_limit_429", "timeout_30s").
    """
    cat = classification.get("category", ec.UNKNOWN)
    msg = classification.get("message", "")

    if cat == ec.TRANSIENT:
        if "rate" in msg.lower() and "limit" in msg.lower():
            return "rate_limit"
        if "timeout" in msg.lower() or "deadline" in msg.lower():
            return "timeout"
        if "connection" in msg.lower():
            return "connection_reset"
        return "transient_other"

    elif cat == ec.CONFLICT:
        if "merge" in msg.lower():
            return "merge_conflict"
        if "branch" in msg.lower() or "missing" in msg.lower():
            return "stale_branch"
        if "rebase" in msg.lower():
            return "rebase_conflict"
        return "conflict_other"

    elif cat == ec.RESOURCE:
        if "quota" in msg.lower():
            return "quota_exceeded"
        if "memory" in msg.lower() or "oom" in msg.lower():
            return "out_of_memory"
        if "budget" in msg.lower() or "credit" in msg.lower():
            return "budget_exceeded"
        return "resource_other"

    return f"{cat}_unknown"


def track_error(error, classification=None, task_id=None):
    """Record an error and its classification for learning.

    Returns the pattern signature that was recorded.
    """
    if classification is None:
        classification = ec.classify(error)

    try:
        pattern_key = _extract_pattern_key(classification)
        sig = PatternSignature(classification.get("category"), pattern_key)

        with _lock:
            _error_history.append({
                "ts": time.time(),
                "signature": (sig.category, sig.pattern_key),
                "category": sig.category,
                "message": classification.get("message", "")[:200],
                "task_id": task_id,
                "recoverable": sig.recoverable,
            })
        return sig
    except Exception:
        return None


def record_recovery_outcome(pattern_key, task_id, success):
    """Record whether a recovery attempt succeeded or failed.

    Updates the success rate for a pattern so the learner can decide whether
    to keep trying automated recovery for similar errors.
    """
    try:
        with _lock:
            if success:
                _recovery_outcomes[pattern_key]["success"] += 1
            else:
                _recovery_outcomes[pattern_key]["failure"] += 1
    except Exception:
        pass


def get_success_rate(pattern_key):
    """Get the historical success rate for a recovery pattern.

    Returns (success_rate, num_observations).
    """
    try:
        with _lock:
            stats = _recovery_outcomes.get(pattern_key, {"success": 0, "failure": 0})
        total = stats["success"] + stats["failure"]
        if total < MIN_OBSERVATIONS:
            return (0.0, total)
        return (stats["success"] / total, total)
    except Exception:
        return (0.0, 0)


def should_auto_recover(pattern_key):
    """Determine if we should attempt auto-recovery for this error pattern.

    Returns True if:
    1. Pattern has been seen at least MIN_OBSERVATIONS times
    2. Historical success rate >= SUCCESS_THRESHOLD
    """
    success_rate, observations = get_success_rate(pattern_key)
    return observations >= MIN_OBSERVATIONS and success_rate >= SUCCESS_THRESHOLD


def recommend_recovery_action(error, classification=None):
    """Recommend an automated recovery action for an error.

    Returns {
        "category": error category,
        "pattern_key": specific pattern within category,
        "should_recover": whether auto-recovery should be attempted,
        "action": "retry_with_backoff" | "rebase_and_retry" | "queue_with_delay" | None,
        "success_rate": historical success rate for this pattern,
        "observations": number of historical observations
    }
    """
    if not ENABLED:
        return {
            "category": None,
            "pattern_key": None,
            "should_recover": False,
            "action": None,
            "success_rate": 0.0,
            "observations": 0,
        }

    try:
        if classification is None:
            classification = ec.classify(error)

        pattern_key = _extract_pattern_key(classification)
        cat = classification.get("category", ec.UNKNOWN)

        success_rate, observations = get_success_rate(pattern_key)
        should_recover = observations >= MIN_OBSERVATIONS and success_rate >= SUCCESS_THRESHOLD

        action = None
        if should_recover:
            if cat == ec.TRANSIENT:
                action = "retry_with_backoff"
            elif cat == ec.CONFLICT:
                action = "rebase_and_retry"
            elif cat == ec.RESOURCE:
                action = "queue_with_delay"

        return {
            "category": cat,
            "pattern_key": pattern_key,
            "should_recover": should_recover,
            "action": action,
            "success_rate": round(success_rate, 3),
            "observations": observations,
        }
    except Exception:
        return {
            "category": None,
            "pattern_key": None,
            "should_recover": False,
            "action": None,
            "success_rate": 0.0,
            "observations": 0,
        }


def get_pattern_statistics(window_hours=24):
    """Get statistics on error patterns in a time window.

    Returns {
        "window_hours": hours,
        "total_errors": count,
        "by_category": {"transient": count, ...},
        "by_pattern_key": {"rate_limit": count, ...},
        "recoverable_patterns": [{"pattern_key": x, "success_rate": y, ...}],
    }
    """
    try:
        cutoff = time.time() - (window_hours * 3600)
        with _lock:
            recent = [e for e in _error_history if e.get("ts", 0) > cutoff]

        by_category = collections.Counter(e.get("category") for e in recent)
        by_pattern = collections.Counter(sig[1] for sig in [e.get("signature", (None, None)) for e in recent] if sig[1])

        recoverable = []
        for pattern_key in by_pattern.keys():
            success_rate, observations = get_success_rate(pattern_key)
            if observations >= MIN_OBSERVATIONS:
                recoverable.append({
                    "pattern_key": pattern_key,
                    "success_rate": round(success_rate, 3),
                    "observations": observations,
                    "can_auto_recover": success_rate >= SUCCESS_THRESHOLD,
                })

        return {
            "window_hours": window_hours,
            "total_errors": len(recent),
            "by_category": dict(by_category),
            "by_pattern_key": dict(by_pattern),
            "recoverable_patterns": sorted(
                recoverable,
                key=lambda x: x["observations"],
                reverse=True
            ),
        }
    except Exception:
        return {
            "window_hours": window_hours,
            "total_errors": 0,
            "by_category": {},
            "by_pattern_key": {},
            "recoverable_patterns": [],
        }


def reset_learning():
    """Clear all learned patterns and recovery outcomes. For testing."""
    global _error_history, _recovery_outcomes
    try:
        with _lock:
            _error_history.clear()
            _recovery_outcomes.clear()
    except Exception:
        pass


# --- Query functions for operator/test use ---

def stats():
    """Return summary statistics for monitoring."""
    try:
        with _lock:
            total_errors = len(_error_history)
            total_outcomes = sum(
                stats["success"] + stats["failure"]
                for stats in _recovery_outcomes.values()
            )
        return {
            "total_errors_tracked": total_errors,
            "total_recovery_attempts": total_outcomes,
            "patterns_with_outcomes": len(_recovery_outcomes),
        }
    except Exception:
        return {
            "total_errors_tracked": 0,
            "total_recovery_attempts": 0,
            "patterns_with_outcomes": 0,
        }
