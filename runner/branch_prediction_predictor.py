#!/usr/bin/env python3
"""Prediction service: load trained branch-prediction model and score branches.

Module-level singleton pattern: call predict_branch_status() directly; it
auto-loads the model on first call and falls back to a heuristic when the
model file is absent (fail-soft, never raises).
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import branch_prediction_config as config
import branch_prediction_data_pipeline as pipeline


class PredictorService:
    """Wraps the saved logistic regression model for branch-need prediction."""

    def __init__(self, model_path=None):
        self._path = model_path or config.MODEL_PATH
        self._weights = None
        self._bias = 0.0
        self._threshold = config.NEEDED_THRESHOLD
        self._loaded = False

    def load_model(self, path=None):
        """Load model weights from JSON. Returns True on success."""
        p = path or self._path
        try:
            import json
            with open(p) as f:
                obj = json.load(f)
            self._weights = obj["weights"]
            self._bias = float(obj["bias"])
            self._threshold = float(obj.get("threshold", config.NEEDED_THRESHOLD))
            self._loaded = True
            return True
        except Exception:
            self._loaded = False
            return False

    def is_loaded(self):
        return self._loaded

    def predict_branch_status(self, branch_age_days=0.0, days_since_activity=0.0,
                               task_state_queued=0, task_state_running=0,
                               project_queue_depth_norm=0.0):
        """Return prediction dict.

        Keys:
            probability  – float [0, 1], P(branch needed)
            decision     – "needed" | "stale"
            loaded       – True when backed by a trained model
        """
        if not self._loaded:
            return self._heuristic(branch_age_days, days_since_activity,
                                    task_state_queued, task_state_running)

        features = pipeline.extract_features({
            "branch_age_days": branch_age_days,
            "days_since_activity": days_since_activity,
            "task_state_queued": task_state_queued,
            "task_state_running": task_state_running,
            "project_queue_depth_norm": project_queue_depth_norm,
        })
        z = sum(w * f for w, f in zip(self._weights, features)) + self._bias
        z = max(-500.0, min(500.0, z))
        prob = 1.0 / (1.0 + math.exp(-z))
        decision = "needed" if prob >= self._threshold else "stale"
        return {"probability": prob, "decision": decision, "loaded": True}

    @staticmethod
    def _heuristic(branch_age_days, days_since_activity, task_state_queued, task_state_running):
        """Simple rule-based fallback when the model file is unavailable."""
        if task_state_queued or task_state_running:
            return {"probability": 0.9, "decision": "needed", "loaded": False}
        if days_since_activity > 30 or branch_age_days > 60:
            return {"probability": 0.1, "decision": "stale", "loaded": False}
        return {"probability": 0.5, "decision": "needed", "loaded": False}


# ── module-level singleton ─────────────────────────────────────────────────────

_service = PredictorService()


def predict_branch_status(branch_age_days=0.0, days_since_activity=0.0,
                           task_state_queued=0, task_state_running=0,
                           project_queue_depth_norm=0.0):
    """Module-level convenience wrapper around the singleton PredictorService.

    Auto-loads the model on first call; never raises (heuristic on any error).
    """
    if not _service.is_loaded():
        _service.load_model()
    return _service.predict_branch_status(
        branch_age_days=branch_age_days,
        days_since_activity=days_since_activity,
        task_state_queued=task_state_queued,
        task_state_running=task_state_running,
        project_queue_depth_norm=project_queue_depth_norm,
    )
