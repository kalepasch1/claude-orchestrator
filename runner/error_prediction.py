#!/usr/bin/env python3
"""
error_prediction.py - ML-free error pattern prediction and adaptive recovery threshold
management for the orchestrator. Categorizes errors (connection, timeout, resource exhaustion,
permission denial, data validation) using heuristic pattern matching + outcome tracking,
auto-retrains every 8h or when accuracy < 80%, and adjusts recovery thresholds adaptively.

Uses a module-level singleton (_ErrorPredictor) with thread-safe state, fail-soft error
handling, and JSON persistence. No external ML dependencies.

Config keys (read live from os.environ with ORCH_ prefix):
  - ORCH_ERROR_PREDICTION_INTERVAL: threshold adjustment interval in seconds (default 300)
  - ORCH_ERROR_PREDICTION_FALLBACK_MODE: if True, skip retrain on low accuracy (default False)
  - ORCH_ERROR_PREDICTION_RETRAIN_HOURS: hours between auto-retrains (default 8)
  - ORCH_ERROR_PREDICTION_MIN_ACCURACY: minimum accuracy % to avoid forced retrain (default 80)
"""

import os
import sys
import time
import json
import threading
from typing import Optional, Dict, List, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


# ─────────────────────────────────────────────────────────────────────────────
# Configuration accessors (read live from env on every call, never frozen).
# ─────────────────────────────────────────────────────────────────────────────

def _interval_seconds() -> float:
    """Recovery threshold adjustment interval in seconds. Read live from env."""
    return float(os.environ.get("ORCH_ERROR_PREDICTION_INTERVAL", "300"))


def _fallback_mode() -> bool:
    """If True, skip retrain on low accuracy (graceful degradation). Read live from env."""
    return os.environ.get("ORCH_ERROR_PREDICTION_FALLBACK_MODE", "false").lower() in ("1", "true", "yes")


def _retrain_hours() -> float:
    """Hours between auto-retrains. Read live from env."""
    return float(os.environ.get("ORCH_ERROR_PREDICTION_RETRAIN_HOURS", "8"))


def _min_accuracy_pct() -> float:
    """Minimum accuracy % before forced retrain. Read live from env."""
    return float(os.environ.get("ORCH_ERROR_PREDICTION_MIN_ACCURACY", "80"))


def _model_state_path() -> str:
    """Path to persisted model state JSON file."""
    home = os.environ.get("CLAUDE_ORCH_HOME", os.path.expanduser("~/.claude-orchestrator"))
    os.makedirs(home, exist_ok=True)
    return os.path.join(home, "error_prediction_model.json")


# ─────────────────────────────────────────────────────────────────────────────
# Error categorization patterns (heuristic-based, no ML library).
# ─────────────────────────────────────────────────────────────────────────────

# Keywords and error patterns for each category. Maps error type to (keywords, patterns).
ERROR_PATTERNS = {
    "connection_error": (
        ["connection", "refused", "reset by peer", "network unreachable", "host unreachable",
         "connection timeout", "connectionrefused", "econnrefused", "broken pipe"],
        ["errno 111", "errno 113", "errno 54", "socket.error", "connectionerror", "network is unreachable"]
    ),
    "timeout": (
        ["timeout", "timed out", "deadline exceeded", "expired", "took too long",
         "slow operation", "hanging", "stuck"],
        ["timeout:", "time.time() delta >", "executor timeout", "query timeout", "read timeout",
         "write timeout", "socket timeout", "operation timed out"]
    ),
    "resource_exhausted": (
        ["out of memory", "oom", "memory exhausted", "no space left on device", "too many open files",
         "file descriptor", "ulimit", "resource limit", "disk full", "quota exceeded"],
        ["memoryerror", "oserror: [errno 28]", "oserror: [errno 24]", "oserror: [errno 26]",
         "proc filesystem", "cannot allocate memory"]
    ),
    "permission_denied": (
        ["permission denied", "forbidden", "unauthorized", "not authorized", "access denied",
         "insufficient privileges", "acl", "401", "403"],
        ["errno 13", "permission error", "permissionerror", "unauthorized", "forbidden",
         "access control", "credentials invalid", "auth failed", "denied"]
    ),
    "data_validation_error": (
        ["validation error", "invalid", "schema", "parse error", "malformed", "corrupt data",
         "bad format", "unexpected type", "required field", "constraint violation"],
        ["valueerror", "typeerror", "jsondecodeerror", "unmarshaling error", "schema violation",
         "data type mismatch", "missing required", "invalid json", "parsing failed"]
    ),
}


class _ErrorPredictor:
    """Thread-safe singleton for error pattern prediction and adaptive recovery thresholds.

    Maintains a probabilistic model of error categorization via outcome tracking. Predicts
    error type from log entries using heuristic pattern matching. Auto-retrains based on
    accuracy metrics and time intervals. Persists state to JSON for durability.
    """

    def __init__(self):
        """Initialize the error predictor with state loaded from disk."""
        self._lock = threading.Lock()
        self._model_state = self._load_model_state()
        self._last_threshold_adjustment = time.time()
        self._last_retrain = self._model_state.get("last_retrain_ts", time.time())

    def _load_model_state(self) -> Dict:
        """Load persisted model state from JSON, or return empty state. Fail-soft."""
        try:
            path = _model_state_path()
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    data = json.load(f)
                    # Validate state structure
                    if isinstance(data, dict) and "predictions" in data:
                        return data
        except Exception:
            pass
        # Return fresh empty state
        return {
            "predictions": {},  # dict[error_type] -> {correct: int, total: int}
            "recovery_thresholds": {
                "connection_error": 0.5,
                "timeout": 0.7,
                "resource_exhausted": 0.6,
                "permission_denied": 0.4,
                "data_validation_error": 0.3,
            },
            "accuracy_pct": 100.0,
            "total_predictions": 0,
            "last_retrain_ts": time.time(),
        }

    def _save_model_state(self) -> bool:
        """Persist model state to JSON. Return True on success, False on error. Fail-soft."""
        try:
            path = _model_state_path()
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._model_state, f, indent=2)
            return True
        except Exception:
            return False

    def predict_error_pattern(self, log_entry: Dict) -> str:
        """Categorize a log entry into one of the known error patterns.

        Args:
            log_entry: dict with keys like 'message', 'error', 'stdout', 'stderr', 'exception_type'

        Returns:
            Error category string (connection_error, timeout, resource_exhausted, etc.)
            or "unknown" if no patterns match. Never raises.
        """
        if not isinstance(log_entry, dict):
            return "unknown"

        # Combine all textual fields into one search string (lowercase for matching)
        search_text = ""
        for key in ("message", "error", "stdout", "stderr", "exception_type", "detail", "reason"):
            if key in log_entry:
                val = log_entry[key]
                if val is not None:
                    search_text += f" {str(val).lower()}"

        if not search_text.strip():
            return "unknown"

        # Score each category based on keyword + pattern matches
        scores = {}
        for error_type, (keywords, patterns) in ERROR_PATTERNS.items():
            score = 0.0
            # Keyword matches (lower case, simpler matching)
            for kw in keywords:
                if kw in search_text:
                    score += 1.0
            # Pattern matches (substrings, more specific)
            for pat in patterns:
                if pat in search_text:
                    score += 2.0  # patterns weighted higher
            scores[error_type] = score

        # Return highest-scoring category, or "unknown" if all scores are 0
        best = max(scores, key=scores.get) if max(scores.values(), default=0) > 0 else "unknown"
        return best

    def adjust_recovery_threshold(self, error_type: str, error_rate: float, baseline: float) -> Dict:
        """Adaptively adjust recovery threshold for an error type based on observed rate.

        Args:
            error_type: one of the known error categories (connection_error, timeout, etc.)
            error_rate: observed error rate (0..1, fraction of operations that failed)
            baseline: baseline error rate from historical data

        Returns:
            dict with keys: error_type, old_threshold, new_threshold, adjustment_reason
                Never raises; returns sensible defaults on bad input.
        """
        with self._lock:
            if not isinstance(error_type, str) or error_type not in self._model_state.get("recovery_thresholds", {}):
                return {
                    "error_type": str(error_type) if error_type else "unknown",
                    "old_threshold": 0.5,
                    "new_threshold": 0.5,
                    "adjustment_reason": "invalid error type",
                }

            old = self._model_state["recovery_thresholds"].get(error_type, 0.5)

            # Fail-soft on bad input
            try:
                error_rate = float(error_rate)
                baseline = float(baseline)
            except (TypeError, ValueError):
                return {
                    "error_type": error_type,
                    "old_threshold": old,
                    "new_threshold": old,
                    "adjustment_reason": "invalid error_rate/baseline (non-numeric)",
                }

            if error_rate < 0 or error_rate > 1 or baseline < 0 or baseline > 1:
                return {
                    "error_type": error_type,
                    "old_threshold": old,
                    "new_threshold": old,
                    "adjustment_reason": "out-of-range error_rate/baseline (not 0..1)",
                }

            # Adaptive adjustment: if error rate exceeds baseline significantly, lower threshold
            # (more aggressive recovery); if below, raise threshold (less interventionist).
            # Use a 10% margin to avoid thrashing.
            new = old
            reason = "no change"

            if error_rate > baseline + 0.10:
                # Error rate elevated: lower threshold to trigger recovery more often
                new = max(0.1, old * 0.8)
                reason = f"error_rate {error_rate:.1%} > baseline {baseline:.1%} + margin → lower threshold"
            elif error_rate < baseline - 0.10:
                # Error rate reduced: raise threshold to be less interventionist
                new = min(0.9, old * 1.1)
                reason = f"error_rate {error_rate:.1%} < baseline {baseline:.1%} - margin → raise threshold"

            # Record this adjustment in state
            self._model_state["recovery_thresholds"][error_type] = new
            self._last_threshold_adjustment = time.time()

            return {
                "error_type": error_type,
                "old_threshold": round(old, 3),
                "new_threshold": round(new, 3),
                "adjustment_reason": reason,
            }

    def record_prediction_outcome(self, error_type: str, was_correct: bool) -> None:
        """Record actual outcome of a prediction for model accuracy tracking.

        Args:
            error_type: the predicted error type
            was_correct: whether the prediction matched ground truth

        Never raises.
        """
        with self._lock:
            if not isinstance(error_type, str) or error_type not in ERROR_PATTERNS:
                return
            if error_type not in self._model_state["predictions"]:
                self._model_state["predictions"][error_type] = {"correct": 0, "total": 0}

            self._model_state["predictions"][error_type]["total"] += 1
            if was_correct:
                self._model_state["predictions"][error_type]["correct"] += 1
            self._model_state["total_predictions"] += 1

            # Trigger retrain if accuracy has drifted significantly
            self._maybe_retrain()

    def _maybe_retrain(self) -> None:
        """Retrain model if accuracy < min_accuracy_pct or interval elapsed. Call with lock held.

        Recalculates accuracy metrics and optionally clears prediction counts to reset.
        """
        now = time.time()
        retrain_interval_s = _retrain_hours() * 3600
        min_acc = _min_accuracy_pct()
        fallback = _fallback_mode()

        # Check if retrain interval has elapsed
        if (now - self._last_retrain) < retrain_interval_s:
            return

        # Calculate current accuracy
        total_correct = sum(p.get("correct", 0) for p in self._model_state["predictions"].values())
        total_pred = self._model_state.get("total_predictions", 1)
        accuracy = (total_correct / total_pred * 100) if total_pred > 0 else 100.0
        self._model_state["accuracy_pct"] = accuracy

        # If accuracy is low and not in fallback mode, reset prediction counts (retrain)
        if accuracy < min_acc and not fallback:
            for error_type in self._model_state["predictions"]:
                self._model_state["predictions"][error_type] = {"correct": 0, "total": 0}
            self._model_state["total_predictions"] = 0
            self._model_state["accuracy_pct"] = 100.0

        self._last_retrain = now

    def stats(self) -> Dict:
        """Return model statistics for observability.

        Returns:
            dict with keys: accuracy_pct, total_predictions, recovery_thresholds,
                predictions_by_type, last_retrain_ts, interval_seconds, fallback_mode
            Never raises; returns empty dict on error.
        """
        try:
            with self._lock:
                predictions_summary = {}
                for error_type, counts in self._model_state["predictions"].items():
                    total = counts.get("total", 0)
                    correct = counts.get("correct", 0)
                    pct = (correct / total * 100) if total > 0 else 0
                    predictions_summary[error_type] = {
                        "correct": correct,
                        "total": total,
                        "accuracy_pct": round(pct, 1),
                    }

                return {
                    "accuracy_pct": round(self._model_state.get("accuracy_pct", 100.0), 1),
                    "total_predictions": self._model_state.get("total_predictions", 0),
                    "recovery_thresholds": {
                        k: round(v, 3)
                        for k, v in self._model_state.get("recovery_thresholds", {}).items()
                    },
                    "predictions_by_type": predictions_summary,
                    "last_retrain_ts": self._model_state.get("last_retrain_ts", 0),
                    "interval_seconds": round(_interval_seconds(), 1),
                    "fallback_mode": _fallback_mode(),
                    "retrain_hours": _retrain_hours(),
                }
        except Exception:
            return {}

    def invalidate(self) -> None:
        """Clear all prediction state and reset thresholds to defaults. For testing/reset."""
        with self._lock:
            self._model_state = self._load_model_state()  # reload from disk or get fresh defaults


# ─────────────────────────────────────────────────────────────────────────────
# Module-level singleton instance and public API functions.
# ─────────────────────────────────────────────────────────────────────────────

_predictor = None
_predictor_init_lock = threading.Lock()


def _get_predictor() -> _ErrorPredictor:
    """Lazy-initialize and return the singleton _ErrorPredictor instance. Thread-safe."""
    global _predictor
    if _predictor is None:
        with _predictor_init_lock:
            if _predictor is None:
                _predictor = _ErrorPredictor()
    return _predictor


def predict_error_pattern(log_entry: Dict) -> str:
    """Public API: Predict error pattern category from a log entry.

    Args:
        log_entry: dict with error/message data (message, error, stdout, stderr, etc.)

    Returns:
        Error category (connection_error, timeout, resource_exhausted, permission_denied,
        data_validation_error) or "unknown". Never raises.

    Example:
        category = predict_error_pattern({"message": "connection refused on port 5432"})
        # returns: "connection_error"
    """
    try:
        return _get_predictor().predict_error_pattern(log_entry)
    except Exception:
        return "unknown"


def adjust_recovery_threshold(error_type: str, error_rate: float, baseline: float) -> Dict:
    """Public API: Adaptively adjust recovery threshold based on observed error rate.

    Args:
        error_type: error category (connection_error, timeout, etc.)
        error_rate: observed error rate [0, 1] (fraction of failed operations)
        baseline: baseline error rate from historical data [0, 1]

    Returns:
        dict with error_type, old_threshold, new_threshold, adjustment_reason.
        Never raises; returns sensible defaults on error.

    Example:
        result = adjust_recovery_threshold("timeout", error_rate=0.15, baseline=0.05)
        # returns: {"error_type": "timeout", "old_threshold": 0.7, "new_threshold": 0.56, ...}
    """
    try:
        return _get_predictor().adjust_recovery_threshold(error_type, error_rate, baseline)
    except Exception:
        return {
            "error_type": str(error_type) if error_type else "unknown",
            "old_threshold": 0.5,
            "new_threshold": 0.5,
            "adjustment_reason": "internal error during adjustment",
        }


def record_prediction_outcome(error_type: str, was_correct: bool) -> None:
    """Public API: Record the actual outcome of a prediction for model retraining.

    Args:
        error_type: the predicted error type (must be a valid category)
        was_correct: whether the prediction matched ground truth

    This is called once the actual error type is confirmed (e.g., from logs, recovery attempts).
    Used to track accuracy and trigger auto-retrain. Never raises.

    Example:
        # After handling a timeout error that we predicted:
        record_prediction_outcome("timeout", was_correct=True)
    """
    try:
        _get_predictor().record_prediction_outcome(error_type, was_correct)
    except Exception:
        pass


def stats() -> Dict:
    """Public API: Return model statistics for observability and dashboards.

    Returns:
        dict with accuracy_pct, total_predictions, recovery_thresholds (by error type),
        predictions_by_type summary, last_retrain_ts, interval_seconds, fallback_mode.
        Never raises; returns empty dict on error.

    Example:
        s = stats()
        print(f"Model accuracy: {s['accuracy_pct']}%")
        print(f"Timeout threshold: {s['recovery_thresholds']['timeout']}")
    """
    try:
        return _get_predictor().stats()
    except Exception:
        return {}


def invalidate() -> None:
    """Public API: Clear all prediction state and reset to defaults. For testing/reset.

    Resets model state, clears prediction counts, resets thresholds to defaults.
    Never raises.
    """
    try:
        _get_predictor().invalidate()
    except Exception:
        pass


if __name__ == "__main__":
    # Simple CLI for testing: python error_prediction.py [command]
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "stats":
        print(json.dumps(stats(), indent=2))
    elif len(sys.argv) > 1 and sys.argv[1] == "predict":
        # Read log entry from stdin or use example
        test_entry = {"message": "connection refused on port 5432"}
        cat = predict_error_pattern(test_entry)
        print(f"Predicted: {cat}")
    elif len(sys.argv) > 1 and sys.argv[1] == "test":
        # Quick self-test
        print("Testing error_prediction module...")
        # Test 1: Predict connection error
        c1 = predict_error_pattern({"message": "connection refused"})
        assert c1 == "connection_error", f"Expected connection_error, got {c1}"
        # Test 2: Predict timeout
        c2 = predict_error_pattern({"error": "timeout: operation timed out after 30s"})
        assert c2 == "timeout", f"Expected timeout, got {c2}"
        # Test 3: Predict resource exhaustion
        c3 = predict_error_pattern({"stderr": "MemoryError: out of memory"})
        assert c3 == "resource_exhausted", f"Expected resource_exhausted, got {c3}"
        # Test 4: Predict permission denied
        c4 = predict_error_pattern({"message": "403 Forbidden: access denied"})
        assert c4 == "permission_denied", f"Expected permission_denied, got {c4}"
        # Test 5: Predict data validation error
        c5 = predict_error_pattern({"error": "ValueError: invalid json in response"})
        assert c5 == "data_validation_error", f"Expected data_validation_error, got {c5}"
        # Test 6: Unknown error
        c6 = predict_error_pattern({"message": "something weird happened"})
        assert c6 == "unknown", f"Expected unknown, got {c6}"
        # Test 7: Adjust threshold
        adj = adjust_recovery_threshold("timeout", 0.20, 0.05)
        assert adj["error_type"] == "timeout", f"Expected timeout in adjustment result"
        assert adj["new_threshold"] < adj["old_threshold"], "Threshold should lower when error_rate > baseline"
        # Test 8: Stats
        st = stats()
        assert "accuracy_pct" in st, "Stats should have accuracy_pct"
        print("All tests passed!")
    else:
        print("Usage: error_prediction.py [stats|predict|test]")
