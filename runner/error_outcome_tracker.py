#!/usr/bin/env python3
"""Adaptive error classification via outcome tracking.

Tracks whether error patterns classified as 'transient' actually led to
successful recovery, then feeds that signal back into retry_policy.classify().
This is the machine-learning layer for error handling: no deep models — just
outcome-driven feedback that makes classification smarter over time.

Usage (called by retry_policy):
    import error_outcome_tracker
    suggestion = error_outcome_tracker.suggest(note)   # "transient"/"terminal"/None
    error_outcome_tracker.record(note, was_transient, succeeded)
"""
import os
import re
import threading

MIN_SAMPLES = int(os.environ.get("ORCH_OUTCOME_MIN_SAMPLES", "5"))
CONFIDENCE = float(os.environ.get("ORCH_OUTCOME_CONFIDENCE", "0.75"))

_lock = threading.Lock()
_stats: dict = {}


def _key(note: str) -> str:
    """Normalize an error note to a stable lookup key.

    Strips numbers, hex hashes, and unix paths so semantically-identical
    errors (different task IDs, different file paths) map to the same key.
    """
    if not note:
        return ""
    n = note.lower()
    n = re.sub(r"\b[0-9a-f]{6,}\b", "HASH", n)  # sha-like tokens
    n = re.sub(r"\d+", "N", n)                   # bare numbers
    n = re.sub(r"(?<!\w)/\S+", "PATH", n)        # unix paths
    n = re.sub(r"\s+", " ", n).strip()
    return n[:80]


def record(note: str, was_classified_transient: bool, succeeded: bool) -> None:
    """Record whether a classification led to a successful outcome.

    Fail-soft: any exception is silently swallowed so callers are never
    interrupted by bookkeeping errors.
    """
    try:
        k = _key(note)
        if not k:
            return
        with _lock:
            if k not in _stats:
                _stats[k] = {"transient_ok": 0, "transient_fail": 0,
                              "terminal_ok": 0, "terminal_fail": 0}
            if was_classified_transient:
                _stats[k]["transient_ok" if succeeded else "transient_fail"] += 1
            else:
                _stats[k]["terminal_ok" if succeeded else "terminal_fail"] += 1
    except Exception:
        pass


def suggest(note: str):
    """Return 'transient', 'terminal', or None (defer to regex).

    Only overrides the static regex when history is both deep enough
    (>= MIN_SAMPLES) and confident enough (>= CONFIDENCE fraction).
    """
    try:
        k = _key(note)
        if not k:
            return None
        with _lock:
            s = dict(_stats.get(k) or {})
        if not s:
            return None
        tot_t = s.get("transient_ok", 0) + s.get("transient_fail", 0)
        if tot_t >= MIN_SAMPLES:
            rate = s["transient_ok"] / tot_t
            if rate >= CONFIDENCE:
                return "transient"
            if rate <= 1.0 - CONFIDENCE:
                return "terminal"
        tot_term = s.get("terminal_ok", 0) + s.get("terminal_fail", 0)
        if tot_term >= MIN_SAMPLES:
            rate = s["terminal_ok"] / tot_term
            if rate >= CONFIDENCE:
                return "terminal"
    except Exception:
        pass
    return None


def stats() -> dict:
    """Return a snapshot of all tracked stats (observability / tests)."""
    with _lock:
        return {k: dict(v) for k, v in _stats.items()}


def reset() -> None:
    """Clear all tracked stats (operator reset / test isolation)."""
    with _lock:
        _stats.clear()
