#!/usr/bin/env python3
"""
error_automation_integration.py - Integration layer between ML error automation and task recovery.

Bridges ml_error_automation (learns from historical patterns) with task recovery actions
(proactive_error_resolver, auto_remediate). Ensures ML recommendations are considered
alongside existing recovery rules.

Thread-safe. Fail-soft: returns sensible defaults on any internal error.
"""
import os, sys, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import db
except Exception:
    db = None

import error_classifier as ec
import ml_error_automation as mla

ENABLED = os.environ.get("ORCH_ERROR_AUTOMATION_INTEGRATION", "true").lower() in ("true", "1")


def classify_and_recommend(error, task_id=None):
    """Classify an error and recommend recovery actions.

    Combines error_classifier (categor ization) with ml_error_automation
    (learned recovery success rates) to produce a combined recommendation.

    Returns {
        "classification": error_classifier.classify() result,
        "ml_recommendation": ml_error_automation.recommend_recovery_action() result,
        "should_recover": bool (from ML if enabled, else from classification),
        "recovery_action": str or None (what to do),
        "confidence": float (0.0 to 1.0 confidence in the recommendation)
    }
    """
    if not ENABLED:
        return _basic_recommendation(error, task_id)

    try:
        classification = ec.classify(error)
        ml_rec = mla.recommend_recovery_action(error, classification)

        # Track the error for learning
        mla.track_error(error, classification, task_id)

        should_recover = ml_rec.get("should_recover", False)
        confidence = ml_rec.get("success_rate", 0.0)
        action = ml_rec.get("action")

        return {
            "classification": classification,
            "ml_recommendation": ml_rec,
            "should_recover": should_recover,
            "recovery_action": action,
            "confidence": confidence,
        }
    except Exception:
        return _basic_recommendation(error, task_id)


def _basic_recommendation(error, task_id=None):
    """Fallback when ML is disabled or errors occur."""
    try:
        classification = ec.classify(error)
        retryable = classification.get("retryable", False)
        category = classification.get("category", ec.UNKNOWN)

        # Simple heuristic: retryable categories should attempt recovery
        action = None
        if retryable:
            if category == ec.TRANSIENT:
                action = "retry_with_backoff"
            elif category == ec.CONFLICT:
                action = "rebase_and_retry"
            elif category == ec.RESOURCE:
                action = "queue_with_delay"

        return {
            "classification": classification,
            "ml_recommendation": None,
            "should_recover": retryable,
            "recovery_action": action,
            "confidence": 0.5 if retryable else 0.0,
        }
    except Exception:
        return {
            "classification": None,
            "ml_recommendation": None,
            "should_recover": False,
            "recovery_action": None,
            "confidence": 0.0,
        }


def record_recovery_result(error_signature, task_id, success, action_taken=None):
    """Record the outcome of a recovery attempt.

    Used by task runners to feed back whether an automated recovery action
    actually worked, so the ML system can update its success rate tracking.

    Args:
        error_signature: The error signature/pattern key from ml_error_automation
        task_id: ID of the task that was recovered
        success: whether the recovery succeeded
        action_taken: string description of action attempted
    """
    if not ENABLED:
        return

    try:
        if error_signature:
            # Extract pattern key from signature if it's a tuple
            if isinstance(error_signature, (tuple, list)):
                pattern_key = error_signature[1] if len(error_signature) > 1 else str(error_signature)
            else:
                pattern_key = str(error_signature)

            mla.record_recovery_outcome(pattern_key, task_id, success)
    except Exception:
        pass


def get_recovery_diagnostics():
    """Return diagnostics for operators/monitoring.

    Shows current error patterns, recovery success rates, and recommendations.
    """
    try:
        ml_stats = mla.get_pattern_statistics(window_hours=6)
        ml_summary = mla.stats()

        return {
            "ml_enabled": ENABLED,
            "error_patterns": ml_stats,
            "recovery_stats": ml_summary,
            "top_recoverable": [
                p for p in ml_stats.get("recoverable_patterns", [])
                if p.get("can_auto_recover")
            ][:5],
        }
    except Exception:
        return {
            "ml_enabled": ENABLED,
            "error_patterns": {},
            "recovery_stats": {},
            "top_recoverable": [],
        }


def enable_ml_automation(enabled=True):
    """Enable/disable ML-based error automation."""
    os.environ["ORCH_ML_AUTO_RECOVERY_ENABLED"] = "true" if enabled else "false"
    os.environ["ORCH_ERROR_AUTOMATION_INTEGRATION"] = "true" if enabled else "false"
    return f"ML error automation {'enabled' if enabled else 'disabled'}"


def clear_learning_state():
    """Clear all learned patterns. For testing and recovery."""
    mla.reset_learning()
    return "Learning state cleared"
