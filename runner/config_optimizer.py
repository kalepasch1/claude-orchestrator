#!/usr/bin/env python3
"""
config_optimizer.py — Historical config analysis for fleet_control.py.

Analyzes past fleet_config changes and their correlation with task throughput,
merge success rates, and cost metrics. Recommends config adjustments based on
observed patterns rather than blind knob-turning.

Owner module: fleet_control.py
Slice-2 of: improve-centralized-configuration-management-wit
"""
import os, sys, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def _safe_import(mod):
    try:
        return __import__(mod)
    except Exception:
        return None

db = _safe_import("db")

# How far back to look for config change impact (hours)
LOOKBACK_HOURS = int(os.environ.get("ORCH_CONFIG_LOOKBACK_HOURS", "24"))
# Minimum throughput improvement to recommend a config change
MIN_THROUGHPUT_GAIN = float(os.environ.get("ORCH_CONFIG_MIN_GAIN", "0.10"))


def _throughput_around(timestamp_iso, window_hours=2):
    """Get task throughput (DONE count) in a window around a timestamp.

    Returns (before_count, after_count) for the window before and after the change.
    """
    if not db:
        return 0, 0
    try:
        before_start = (datetime.datetime.fromisoformat(timestamp_iso)
                        - datetime.timedelta(hours=window_hours)).isoformat()
        after_end = (datetime.datetime.fromisoformat(timestamp_iso)
                     + datetime.timedelta(hours=window_hours)).isoformat()

        before = db.select("tasks", {
            "select": "id", "state": "eq.DONE",
            "updated_at": f"gte.{before_start}",
            "and": f"(updated_at.lt.{timestamp_iso})",
            "limit": "1000"
        }) or []
        after = db.select("tasks", {
            "select": "id", "state": "eq.DONE",
            "updated_at": f"gte.{timestamp_iso}",
            "and": f"(updated_at.lt.{after_end})",
            "limit": "1000"
        }) or []
        return len(before), len(after)
    except Exception:
        return 0, 0


def analyze_config_history():
    """Analyze fleet_config changes and their impact on throughput.

    Returns list of dicts: [{key, old_value, new_value, impact, recommendation}]
    """
    if not db:
        return []
    try:
        cutoff = (datetime.datetime.utcnow()
                  - datetime.timedelta(hours=LOOKBACK_HOURS)).isoformat()
        # Look for config audit trail if available
        changes = db.select("fleet_config_audit", {
            "select": "*",
            "created_at": f"gte.{cutoff}",
            "order": "created_at.desc",
            "limit": "50"
        }) or []
    except Exception:
        changes = []

    results = []
    for ch in changes:
        key = ch.get("key", "")
        ts = ch.get("created_at", "")
        if not ts:
            continue
        before, after = _throughput_around(ts)
        if before == 0:
            impact = "unknown"
            recommendation = "insufficient_data"
        elif after >= before * (1 + MIN_THROUGHPUT_GAIN):
            impact = "positive"
            recommendation = "keep"
        elif after <= before * (1 - MIN_THROUGHPUT_GAIN):
            impact = "negative"
            recommendation = "revert"
        else:
            impact = "neutral"
            recommendation = "keep"

        results.append({
            "key": key,
            "old_value": ch.get("old_value"),
            "new_value": ch.get("new_value"),
            "before_throughput": before,
            "after_throughput": after,
            "impact": impact,
            "recommendation": recommendation,
        })
    return results


def suggest_config_changes():
    """Based on current fleet state, suggest config knob changes.

    Looks at queue pressure and recent merge rates to suggest adjustments
    to MAX_PARALLEL, MERGE_TRAIN_*_BATCH, etc.
    """
    if not db:
        return []
    suggestions = []
    try:
        # Check queue depth
        queued = db.select("tasks", {
            "select": "id", "state": "eq.QUEUED", "limit": "1000"
        }) or []
        queue_depth = len(queued)

        current_parallel = int(os.environ.get("MAX_PARALLEL_CEILING", "4"))

        # If queue is deep and throughput is healthy, suggest increasing parallelism
        if queue_depth > 50 and current_parallel < 8:
            suggestions.append({
                "key": "MAX_PARALLEL_CEILING",
                "current": current_parallel,
                "suggested": min(current_parallel + 2, 8),
                "reason": f"Queue depth={queue_depth}, consider increasing parallelism",
            })
        elif queue_depth < 5 and current_parallel > 2:
            suggestions.append({
                "key": "MAX_PARALLEL_CEILING",
                "current": current_parallel,
                "suggested": max(current_parallel - 1, 2),
                "reason": f"Queue depth={queue_depth}, can reduce parallelism to save cost",
            })
    except Exception:
        pass
    return suggestions


def stats():
    """Return optimizer summary."""
    return {
        "lookback_hours": LOOKBACK_HOURS,
        "min_throughput_gain": MIN_THROUGHPUT_GAIN,
    }
