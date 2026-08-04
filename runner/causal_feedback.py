#!/usr/bin/env python3
"""
causal_feedback.py - Causal attribution system that traces remediation outcomes back to
triggering bottleneck signals. Enables the orchestrator to learn which remediation actions
reduce/eliminate specific measured bottlenecks.

Provides:
  - write(bottleneck_key, remediation_slug, signal_before, signal_after, ...) — non-blocking
    feedback write on every task completion (fail-soft, <50ms)
  - lookup(bottleneck_key, confidence_floor=0.8) — router queries to weight next action
    selection based on 80th-percentile confidence threshold
  - for_remediation(slug) — audit trail of all outcomes for a given remediation action
"""
import os
import sys
import json
import threading
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

_write_lock = threading.Lock()
_stats = {"writes": 0, "errors": 0, "skipped": 0}

CONFIDENCE_FLOOR = float(os.environ.get("ORCH_CAUSAL_CONFIDENCE_FLOOR", "0.8"))
NONBLOCKING_WRITE = os.environ.get("ORCH_CAUSAL_NONBLOCKING", "true").lower() == "true"


def write(bottleneck_key, remediation_slug, signal_before, signal_after, outcome_metric=None,
          task_id=None, proof_id=None, confidence=None, metadata=None):
    """Record a causal feedback tuple (non-blocking I/O, fail-soft).

    Args:
        bottleneck_key (str): Bottleneck identifier (e.g., "cycle_time_hours")
        remediation_slug (str): Task slug of remediation attempt (e.g., "improve-cycle-time")
        signal_before (float): Metric value before remediation
        signal_after (float): Metric value after remediation
        outcome_metric (str, optional): Human name of metric (e.g., "Median cycle time")
        task_id (str, optional): Reference to tasks.id
        proof_id (str, optional): Reference to execution_proof_envelopes.id
        confidence (float, optional): [0.0, 1.0] confidence in this measurement
        metadata (dict, optional): Additional context (model, attempt count, etc.)

    Returns:
        bool: True if write was queued/recorded; False on validation failure.
    """
    if not bottleneck_key or not remediation_slug:
        return False

    try:
        signal_before = float(signal_before) if signal_before is not None else None
        signal_after = float(signal_after) if signal_after is not None else None
    except (TypeError, ValueError):
        return False

    if signal_before is None or signal_after is None:
        return False

    confidence = float(confidence or 0.5)
    if confidence < 0.0 or confidence > 1.0:
        confidence = 0.5

    delta_pct = _compute_delta_pct(signal_before, signal_after)
    outcome_status = _classify_outcome(signal_before, signal_after)

    row = {
        "bottleneck_key": bottleneck_key,
        "remediation_slug": remediation_slug,
        "signal_before": signal_before,
        "signal_after": signal_after,
        "outcome_metric": outcome_metric,
        "delta_pct": delta_pct,
        "task_id": task_id,
        "proof_id": proof_id,
        "outcome_status": outcome_status,
        "confidence_0to1": confidence,
        "metadata": metadata or {},
    }

    if NONBLOCKING_WRITE:
        return _write_async(row)
    return _write_sync(row)


def _compute_delta_pct(before, after):
    """Compute percentage change: ((before - after) / before) * 100.
    For 'lower is better' metrics: positive delta = improvement.
    Returns None if before is 0 or negative."""
    if before is None or after is None or before <= 0:
        return None
    try:
        return round(((before - after) / before) * 100.0, 2)
    except (TypeError, ZeroDivisionError):
        return None


def _classify_outcome(signal_before, signal_after):
    """Classify outcome as positive (improved), neutral, or negative (worsened).
    Assumes lower is better (common for bottleneck metrics like cycle_time, queue_depth)."""
    if signal_before is None or signal_after is None:
        return "pending"
    try:
        if signal_after < signal_before * 0.95:
            return "positive"
        elif signal_after > signal_before * 1.05:
            return "negative"
        else:
            return "neutral"
    except (TypeError, ValueError):
        return "pending"


def _write_sync(row):
    """Synchronous database write (blocking). Fail-soft: returns False on any error."""
    global _stats
    try:
        with _write_lock:
            result = db.insert("causal_feedback", row)
            if result:
                _stats["writes"] += 1
                return True
            else:
                _stats["skipped"] += 1
                return False
    except Exception as exc:
        _stats["errors"] += 1
        return False


def _write_async(row):
    """Queue a write in a background thread (fail-soft, non-blocking)."""
    global _stats

    def _do_write():
        try:
            with _write_lock:
                result = db.insert("causal_feedback", row)
                if result:
                    _stats["writes"] += 1
                else:
                    _stats["skipped"] += 1
        except Exception:
            _stats["errors"] += 1

    try:
        t = threading.Thread(target=_do_write, daemon=True)
        t.start()
        return True
    except Exception:
        return False


def lookup(bottleneck_key, confidence_floor=None):
    """Query router: return high-confidence remediation patterns for a bottleneck.

    Args:
        bottleneck_key (str): Bottleneck to query (e.g., "cycle_time_hours")
        confidence_floor (float, optional): Min confidence [0.0, 1.0], defaults to CONFIDENCE_FLOOR

    Returns:
        list[dict]: Remediation patterns ranked by confidence and positive outcome count:
            [{"remediation_slug": "...", "positive_count": N, "avg_confidence": 0.85,
              "avg_delta_pct": 23.4, "neutral_count": 0, "negative_count": 0}, ...]
    """
    if not bottleneck_key:
        return []

    if confidence_floor is None:
        confidence_floor = CONFIDENCE_FLOOR

    try:
        confidence_floor = float(confidence_floor)
        if confidence_floor < 0.0 or confidence_floor > 1.0:
            confidence_floor = CONFIDENCE_FLOOR
    except (TypeError, ValueError):
        confidence_floor = CONFIDENCE_FLOOR

    try:
        rows = db.rpc("causal_feedback_for_bottleneck", {
            "bottleneck_key_in": bottleneck_key,
            "confidence_floor": confidence_floor
        })
    except Exception:
        return []

    if not rows:
        return []

    if isinstance(rows, dict):
        rows = [rows]

    return [
        {
            "remediation_slug": r.get("remediation_slug"),
            "positive_count": int(r.get("positive_count", 0)),
            "neutral_count": int(r.get("neutral_count", 0)),
            "negative_count": int(r.get("negative_count", 0)),
            "avg_confidence": float(r.get("avg_confidence", 0.0)),
            "avg_delta_pct": float(r.get("avg_delta_pct", 0.0)),
        }
        for r in rows if r.get("remediation_slug")
    ]


def for_remediation(remediation_slug):
    """Audit trail: all feedback for a given remediation action.

    Args:
        remediation_slug (str): Task slug to audit (e.g., "improve-cycle-time")

    Returns:
        list[dict]: Feedback records ordered by created_at descending:
            [{"id": "...", "bottleneck_key": "...", "signal_before": 96.4,
              "signal_after": 42.1, "outcome_status": "positive", "confidence_0to1": 0.9,
              "delta_pct": 56.2, "created_at": "2026-08-03T12:34:56+00:00"}, ...]
    """
    if not remediation_slug:
        return []

    try:
        rows = db.rpc("causal_feedback_for_remediation", {"slug_in": remediation_slug})
    except Exception:
        return []

    if not rows:
        return []

    if isinstance(rows, dict):
        rows = [rows]

    return [
        {
            "id": r.get("id"),
            "bottleneck_key": r.get("bottleneck_key"),
            "signal_before": float(r.get("signal_before", 0.0)) if r.get("signal_before") else None,
            "signal_after": float(r.get("signal_after", 0.0)) if r.get("signal_after") else None,
            "outcome_status": r.get("outcome_status"),
            "confidence_0to1": float(r.get("confidence_0to1", 0.0)),
            "delta_pct": float(r.get("delta_pct", 0.0)) if r.get("delta_pct") else None,
            "created_at": r.get("created_at"),
        }
        for r in rows
    ]


def stats():
    """Return write statistics (for monitoring and testing)."""
    with _write_lock:
        return dict(_stats)


def invalidate():
    """Clear statistics (for testing)."""
    global _stats
    with _write_lock:
        _stats = {"writes": 0, "errors": 0, "skipped": 0}
