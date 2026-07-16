#!/usr/bin/env python3
"""
gauntlet_gate.py — confidence-threshold admission policy with hard-fail override.

Decides whether a gauntlet result should be admitted (no human needed),
sent to human_review, or rejected outright.

Hard failures (unresolved citation, source, or precedent) always reject.
Otherwise the confidence score is compared against ORCH_GAUNTLET_ADMIT_FLOOR
(env var, default 0.50):
  - confidence >= floor  → admit
  - 0 < confidence < floor → human_review

Pure function; stdlib only.
"""
import os, sys, threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

DEFAULT_ADMIT_FLOOR = 0.50

HARD_FAILURE_KEYS = frozenset([
    "unresolved_citation",
    "unresolved_source",
    "unresolved_precedent",
])

_stats_lock = threading.Lock()
_stats = {
    "decisions": 0,
    "admits": 0,
    "human_reviews": 0,
    "rejects": 0,
    "hard_failures": 0,
}


def _get_admit_floor(thresholds=None):
    """Return the admission floor from thresholds dict, env var, or default."""
    if thresholds and "admit_floor" in thresholds:
        return float(thresholds["admit_floor"])
    return float(os.environ.get("ORCH_GAUNTLET_ADMIT_FLOOR", str(DEFAULT_ADMIT_FLOOR)))


def _has_hard_failure(gauntlet_result):
    """Check if any hard-failure flag is set in the result."""
    failures = gauntlet_result.get("failures") or []
    if isinstance(failures, list):
        for f in failures:
            key = f.get("type", "") if isinstance(f, dict) else str(f)
            if key in HARD_FAILURE_KEYS:
                return True, key
    for key in HARD_FAILURE_KEYS:
        if gauntlet_result.get(key):
            return True, key
    return False, None


def decide_entry(gauntlet_result, thresholds=None):
    """
    Decide admission based on gauntlet result.

    Args:
        gauntlet_result: dict with at least 'confidence' (float 0-1)
                         and optionally 'failures' list or hard-failure keys.
        thresholds: optional dict with 'admit_floor' override.

    Returns:
        dict with 'decision' ('admit'|'human_review'|'reject') and 'reason' str.
    """
    try:
        hard, failure_key = _has_hard_failure(gauntlet_result)
        if hard:
            with _stats_lock:
                _stats["decisions"] += 1
                _stats["rejects"] += 1
                _stats["hard_failures"] += 1
            return {
                "decision": "reject",
                "reason": f"hard failure: {failure_key}",
            }

        floor = _get_admit_floor(thresholds)
        confidence = float(gauntlet_result.get("confidence", 0))

        if confidence >= floor:
            with _stats_lock:
                _stats["decisions"] += 1
                _stats["admits"] += 1
            return {
                "decision": "admit",
                "reason": f"confidence {confidence:.2f} >= floor {floor:.2f}",
            }

        with _stats_lock:
            _stats["decisions"] += 1
            _stats["human_reviews"] += 1
        return {
            "decision": "human_review",
            "reason": f"confidence {confidence:.2f} < floor {floor:.2f}",
        }
    except Exception as exc:
        # fail-soft: on any error, route to human review
        with _stats_lock:
            _stats["decisions"] += 1
            _stats["human_reviews"] += 1
        return {
            "decision": "human_review",
            "reason": f"gate error (fail-soft): {exc}",
        }


def stats():
    """Return a copy of current gate statistics."""
    with _stats_lock:
        return dict(_stats)


def reset_stats():
    """Reset all counters to zero."""
    with _stats_lock:
        for k in _stats:
            _stats[k] = 0
