"""ML-powered task dispatcher integration.

Integrates duration predictor, dependency inferencer, and runner assignment
optimizer into the main task dispatch pipeline with canary gating.
"""

import os
import time
import random
import logging
from typing import Dict, Any, Optional, List

log = logging.getLogger(__name__)

# Feature gate
ML_ASSIGNMENT_ENABLED = os.environ.get("ORCH_ML_ASSIGNMENT_ENABLED", "false").lower() == "true"
ML_CANARY_PERCENT = int(os.environ.get("ORCH_ML_ASSIGNMENT_CANARY", "10"))


class MLDispatcherIntegration:
    """Wraps ML assignment into the task dispatch pipeline."""

    def __init__(self, prediction_model=None, dependency_inferencer=None,
                 runner_optimizer=None, enabled: bool = None,
                 canary_percent: int = None):
        self._prediction_model = prediction_model
        self._dependency_inferencer = dependency_inferencer
        self._runner_optimizer = runner_optimizer
        self._enabled = enabled if enabled is not None else ML_ASSIGNMENT_ENABLED
        self._canary_percent = canary_percent if canary_percent is not None else ML_CANARY_PERCENT
        self._decisions: List[Dict[str, Any]] = []
        self._model_loaded_at: Optional[float] = None
        self._model_stale_threshold = 3600  # 1 hour

    def load_model(self, model=None):
        """Load or reload the prediction model."""
        if model is not None:
            self._prediction_model = model
        self._model_loaded_at = time.time()
        log.info("ML model loaded at %s", self._model_loaded_at)

    def is_model_stale(self) -> bool:
        """Check if the model needs reloading."""
        if self._model_loaded_at is None:
            return True
        return (time.time() - self._model_loaded_at) > self._model_stale_threshold

    def is_in_canary(self, task: Dict[str, Any]) -> bool:
        """Determine if a task falls in the canary cohort."""
        if not self._enabled:
            return False
        # Use task id hash for deterministic canary assignment
        task_id = task.get("id", str(random.random()))
        hash_val = hash(task_id) % 100
        return hash_val < self._canary_percent

    def enrich_with_dependencies(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """Add dependency predictions to task during DECOMPOSED->QUEUED."""
        if not self._enabled or self._dependency_inferencer is None:
            return task

        try:
            task_type = task.get("type", "unknown")
            deps = self._dependency_inferencer.predict_dependencies(task_type)
            task["predicted_dependencies"] = list(deps)
            log.info("Task %s: predicted deps = %s", task.get("id"), deps)
        except Exception as e:
            log.warning("Dependency inference failed for %s: %s", task.get("id"), e)
            task["predicted_dependencies"] = []

        return task

    def assign_runner(self, task: Dict[str, Any],
                      available_runners: list) -> Optional[Dict[str, Any]]:
        """Assign a runner during QUEUED->RUNNING transition.

        Returns assignment dict or None for fallback to default assignment.
        """
        if not self.is_in_canary(task):
            self._log_decision(task, "skip", "not in canary cohort")
            return None

        if self._runner_optimizer is None:
            self._log_decision(task, "fallback", "no optimizer loaded")
            return None

        try:
            result = self._runner_optimizer(
                task, available_runners,
                prediction_model=self._prediction_model,
                dependency_graph=task.get("predicted_dependencies_graph"),
            )
            assignment = {
                "runner_id": result.runner_id,
                "confidence": result.confidence_score,
                "reason": result.reason,
                "source": "ml",
            }
            self._log_decision(task, "ml_assigned", assignment)
            return assignment
        except Exception as e:
            log.warning("ML assignment failed for %s: %s", task.get("id"), e)
            self._log_decision(task, "fallback", f"error: {e}")
            return None

    def _log_decision(self, task: Dict[str, Any], decision_type: str,
                      detail: Any):
        """Log an assignment decision for outcome tracking."""
        entry = {
            "task_id": task.get("id"),
            "task_type": task.get("type"),
            "decision": decision_type,
            "detail": detail,
            "timestamp": time.time(),
            "canary": self.is_in_canary(task),
        }
        self._decisions.append(entry)
        if len(self._decisions) > 10000:
            self._decisions = self._decisions[-5000:]

    def get_decisions(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Return recent assignment decisions."""
        return self._decisions[-limit:]

    def get_canary_metrics(self) -> Dict[str, Any]:
        """Compute metrics for canary vs control cohorts."""
        canary_decisions = [d for d in self._decisions if d.get("canary")]
        control_decisions = [d for d in self._decisions if not d.get("canary")]
        return {
            "canary_count": len(canary_decisions),
            "control_count": len(control_decisions),
            "canary_ml_assigned": sum(1 for d in canary_decisions if d["decision"] == "ml_assigned"),
            "canary_fallback": sum(1 for d in canary_decisions if d["decision"] == "fallback"),
            "canary_percent": self._canary_percent,
            "enabled": self._enabled,
        }

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, val: bool):
        self._enabled = val
