#!/usr/bin/env python3
"""
predictive_error_handler.py - predict and preemptively handle errors using
historical error patterns from error_taxonomy.

Extends the fail-soft error handling by analyzing error frequency trends
and predicting likely failure modes for incoming tasks. When a task matches
a high-risk error pattern, the handler pre-applies mitigation (extra deps,
increased budget, constrained prompt) before execution starts.

Fail-soft: returns empty predictions on any error, never raises.
Env: ORCH_PREDICTIVE_ERROR_ENABLED (default "true").
"""
import os
import re
import sys
import threading
import time
import math

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import log as _log_mod

_log = _log_mod.get("predictive_error_handler")
_ENABLED = os.environ.get("ORCH_PREDICTIVE_ERROR_ENABLED", "true").lower() in ("true", "1", "yes")

# ---------------------------------------------------------------------------
# Error pattern history (thread-safe)
# ---------------------------------------------------------------------------
_lock = threading.Lock()
_task_error_history = {}  # {slug_prefix: [{"error_class": str, "timestamp": float}]}
_WINDOW_SECONDS = int(os.environ.get("ORCH_ERROR_PREDICT_WINDOW", "86400"))  # 24h default
_MIN_SAMPLES = int(os.environ.get("ORCH_ERROR_PREDICT_MIN_SAMPLES", "3"))


def record_error(slug, error_class):
    """Record an error occurrence for a task slug pattern."""
    try:
        prefix = re.sub(r'-slice-\d+$', '', slug)
        with _lock:
            history = _task_error_history.setdefault(prefix, [])
            history.append({"error_class": error_class, "timestamp": time.time()})
            # Cap history at 200 entries per prefix
            if len(history) > 200:
                _task_error_history[prefix] = history[-100:]
    except Exception as exc:
        _log.debug("record_error error: %s", exc)


def _recent_errors(slug_prefix, window=None):
    """Get errors within the time window for a slug prefix."""
    window = window or _WINDOW_SECONDS
    cutoff = time.time() - window
    with _lock:
        history = _task_error_history.get(slug_prefix, [])
        return [e for e in history if e["timestamp"] >= cutoff]


def _dominant_error(errors):
    """Find the most common error class in a list."""
    if not errors:
        return None, 0.0
    counts = {}
    for e in errors:
        cls = e["error_class"]
        counts[cls] = counts.get(cls, 0) + 1
    top_cls = max(counts, key=counts.get)
    return top_cls, counts[top_cls] / len(errors)


# Preemptive mitigation mapping
_PREEMPTIVE_ACTIONS = {
    "import_error": {"action": "pre_install_deps", "prompt_hint": "Ensure all imports are available before execution."},
    "timeout": {"action": "increase_budget", "prompt_hint": "This task pattern tends to exceed time limits; budget has been increased."},
    "test_failure": {"action": "add_test_constraints", "prompt_hint": "Previous attempts had test failures; run tests incrementally."},
    "merge_conflict": {"action": "fresh_rebase", "prompt_hint": "Rebase onto latest base branch before starting work."},
    "syntax_error": {"action": "add_lint_step", "prompt_hint": "Run linter before committing; previous attempts had syntax errors."},
    "build_failure": {"action": "check_build_first", "prompt_hint": "Verify build succeeds before adding new code."},
    "rate_limit": {"action": "throttle_start", "prompt_hint": "Apply rate-limit backoff before starting."},
    "permission_error": {"action": "skip", "prompt_hint": "This task pattern hits permission errors; may need manual intervention."},
}


def predict(task):
    """Predict likely error class for a task and return preemptive action.

    Returns:
        dict with keys: predicted_error, confidence, preemptive_action, prompt_hint
        or empty prediction if insufficient data or disabled.
    """
    if not _ENABLED:
        return {"predicted_error": None, "confidence": 0.0, "preemptive_action": None}

    try:
        slug = task.get("slug", "")
        prefix = re.sub(r'-slice-\d+$', '', slug)
        recent = _recent_errors(prefix)

        if len(recent) < _MIN_SAMPLES:
            return {"predicted_error": None, "confidence": 0.0, "preemptive_action": None,
                    "reason": f"insufficient samples ({len(recent)} < {_MIN_SAMPLES})"}

        dominant_cls, ratio = _dominant_error(recent)
        # Weight by recency: more recent errors count more
        now = time.time()
        recency_weights = [math.exp(-(now - e["timestamp"]) / _WINDOW_SECONDS) for e in recent if e["error_class"] == dominant_cls]
        recency_boost = sum(recency_weights) / len(recency_weights) if recency_weights else 0.5
        confidence = round(min(1.0, ratio * recency_boost * 1.2), 3)

        action_info = _PREEMPTIVE_ACTIONS.get(dominant_cls, {})

        return {
            "predicted_error": dominant_cls,
            "confidence": confidence,
            "preemptive_action": action_info.get("action"),
            "prompt_hint": action_info.get("prompt_hint", ""),
            "sample_count": len(recent),
        }
    except Exception as exc:
        _log.debug("predict error: %s", exc)
        return {"predicted_error": None, "confidence": 0.0, "preemptive_action": None}


def augment_prompt(task, base_prompt):
    """If a prediction is confident enough, prepend a mitigation hint to the prompt."""
    try:
        prediction = predict(task)
        if prediction.get("confidence", 0) >= 0.5 and prediction.get("prompt_hint"):
            hint = f"[PREDICTIVE HINT: {prediction['prompt_hint']}]\n\n"
            return hint + base_prompt, prediction
        return base_prompt, prediction
    except Exception:
        return base_prompt, {"predicted_error": None, "confidence": 0.0}


def stats():
    """Return prediction state for observability."""
    with _lock:
        result = {}
        for prefix, history in _task_error_history.items():
            cutoff = time.time() - _WINDOW_SECONDS
            recent = [e for e in history if e["timestamp"] >= cutoff]
            if recent:
                dominant, ratio = _dominant_error(recent)
                result[prefix] = {
                    "total_errors": len(recent),
                    "dominant_error": dominant,
                    "dominance_ratio": round(ratio, 3),
                }
        return result


if __name__ == "__main__":
    import json
    print(json.dumps(stats(), indent=2, default=str))
