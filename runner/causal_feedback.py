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

# Minimum relative movement (fraction, not percent) before an outcome is called
# positive/negative instead of neutral. Fleet-tunable via fleet_control.py.
_OUTCOME_THRESHOLD = float(os.environ.get("ORCH_CAUSAL_OUTCOME_THRESHOLD", "0.05"))
# Absorbs binary-rounding error so a boundary-exact move classifies deterministically.
_EPS = 1e-9

CONFIDENCE_FLOOR = float(os.environ.get("ORCH_CAUSAL_CONFIDENCE_FLOOR", "0.8"))
NONBLOCKING_WRITE = os.environ.get("ORCH_CAUSAL_NONBLOCKING", "true").lower() == "true"


def write(bottleneck_key, remediation_slug, signal_before, signal_after, outcome_metric=None,
          task_id=None, proof_id=None, confidence=None, metadata=None):
    """Record a causal feedback tuple (non-blocking I/O, fail-soft).

    Args:
        bottleneck_key (str): Bottleneck identifier (e.g., "cycle_time_hours")
        remediation_slug (str): Task slug of remediation attempt (e.g., "improve-cycle-time")
        signal_before (float): Metric value before remediation. Must be > 0 — it is the
            denominator for delta_pct and the outcome ratio.
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

    # signal_before is the denominator of every delta/ratio downstream; a zero or
    # negative baseline yields an undefined or sign-flipped improvement, so reject
    # it here rather than persisting an uninterpretable row.
    if signal_before <= 0:
        return False

    # `confidence or 0.5` silently rewrote a legitimate 0.0 (no confidence) to the
    # 0.5 default, and float() raised on non-numeric input; both are handled here.
    if confidence is None:
        confidence = 0.5
    else:
        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            confidence = 0.5
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
    Returns None if either side is missing or non-numeric, or if before <= 0."""
    if before is None or after is None:
        return None
    # Coerce before comparing: `before <= 0` raised TypeError on a non-numeric
    # baseline (e.g. a stringified metric), escaping this fail-soft helper.
    try:
        before = float(before)
        after = float(after)
    except (TypeError, ValueError):
        return None
    if before <= 0:
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
        before = float(signal_before)
        after = float(signal_after)
    except (TypeError, ValueError):
        return "pending"
    if before == 0:
        # No baseline to measure movement against; never guess a label.
        return "pending"
    # Compare the relative change against the threshold directly rather than
    # against `before * 0.95`: an exactly-5% move is a real move and must classify,
    # but binary rounding of the scaled bound (100 * 0.95) put it on the wrong side.
    improvement = (before - after) / before
    if improvement >= _OUTCOME_THRESHOLD - _EPS:
        return "positive"
    if improvement <= -_OUTCOME_THRESHOLD + _EPS:
        return "negative"
    return "neutral"


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


#: Weight of the learned prior when a candidate has evidence. A remediation the fleet has
#: watched work is preferred, but never to the point of freezing exploration — an
#: unevidenced candidate still scores 0.0 rather than -inf, so it stays selectable.
LEARNED_WEIGHT = float(os.environ.get("ORCH_CAUSAL_LEARNED_WEIGHT", "1.0"))


def rank_remediations(bottleneck_key, candidates, confidence_floor=None, lookup_fn=None):
    """Order candidate remediation slugs by what actually worked on this bottleneck.

    THE GAP THIS CLOSES. This module's own docstring says lookup() exists so the
    "router queries to weight next action selection", and write() records an outcome on
    every task completion. The writes happen; the weighting never did — grep on
    origin/master finds NO caller of causal_feedback anywhere in runner/. The fleet was
    accumulating evidence about which remediations reduce which bottlenecks and then
    picking the next action without consulting any of it.

    This is the consuming half: a PURE ordering over candidates, with the DB read
    injected, so the selection rule is unit-testable without a database — the same
    shape as the rest of the module, where I/O is fail-soft and logic is separable.

    SCORING. Each candidate scores `positive - negative`, scaled by average confidence
    and nudged by average delta, all multiplied by LEARNED_WEIGHT. A candidate with no
    recorded evidence scores exactly 0.0, which puts it above anything that has measurably
    made this bottleneck WORSE and below anything that has measurably helped — the right
    default for an action nobody has evidence about. Ties keep the caller's original
    order, so this never silently reshuffles a list it has nothing to say about.

    Fail-soft: any error returns the candidates unchanged. A learning signal must never be
    able to stop the router from choosing something.
    """
    try:
        ordered = [c for c in (candidates or []) if isinstance(c, str) and c.strip()]
        if not ordered or not bottleneck_key:
            return list(ordered)

        fn = lookup_fn or lookup
        evidence = {}
        for row in (fn(bottleneck_key, confidence_floor) or []):
            slug = (row or {}).get("remediation_slug")
            if isinstance(slug, str) and slug:
                evidence[slug] = row

        scored = [
            (index, candidate, _learned_score(evidence.get(candidate)))
            for index, candidate in enumerate(ordered)
        ]
        scored.sort(key=lambda item: (-item[2], item[0]))
        return [candidate for _index, candidate, _score in scored]
    except Exception:
        return list(candidates or [])


def _learned_score(row):
    """Score one candidate from its evidence row. 0.0 when there is no evidence."""
    if not isinstance(row, dict):
        return 0.0
    try:
        positive = int(row.get("positive_count", 0) or 0)
        negative = int(row.get("negative_count", 0) or 0)
        confidence = float(row.get("avg_confidence", 0.0) or 0.0)
        delta_pct = float(row.get("avg_delta_pct", 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0
    # Confidence scales the count evidence; delta only breaks ties between candidates
    # with comparable records, so a single huge delta cannot outvote a consistent record.
    return LEARNED_WEIGHT * ((positive - negative) * max(confidence, 0.0) + delta_pct / 1000.0)


def explain_ranking(bottleneck_key, candidates, confidence_floor=None, lookup_fn=None):
    """[(candidate, score, evidence_or_None)] in ranked order — for logs and audits.

    A router that silently reorders its options is unreviewable; this makes the reason
    inspectable without re-deriving it.
    """
    try:
        fn = lookup_fn or lookup
        evidence = {}
        for row in (fn(bottleneck_key, confidence_floor) or []):
            slug = (row or {}).get("remediation_slug")
            if isinstance(slug, str) and slug:
                evidence[slug] = row
        ranked = rank_remediations(bottleneck_key, candidates, confidence_floor,
                                   lookup_fn=lambda *_a, **_k: list(evidence.values()))
        return [(c, _learned_score(evidence.get(c)), evidence.get(c)) for c in ranked]
    except Exception:
        return [(c, 0.0, None) for c in (candidates or [])]


def stats():
    """Return write statistics (for monitoring and testing)."""
    with _write_lock:
        return dict(_stats)


def invalidate():
    """Clear statistics (for testing)."""
    global _stats
    with _write_lock:
        _stats = {"writes": 0, "errors": 0, "skipped": 0}
