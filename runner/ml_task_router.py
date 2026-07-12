#!/usr/bin/env python3
"""
ml_task_router.py - predict optimal task routing using historical outcomes.

Uses a lightweight statistical model (no external ML deps) trained on the
outcomes table to predict which account/model combination is most likely to
succeed for a given task kind and complexity.

predict_route(task) -> {"account": str, "model": str, "confidence": float, "reason": str}
train()            -> retrain from recent outcomes
stats()            -> model performance metrics
"""
import os, sys, time, threading, math, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import log as _log_mod

_log = _log_mod.get("ml_task_router")

_ENABLED = os.environ.get("ORCH_ML_ROUTER_ENABLED", "true").lower() == "true"
_MIN_SAMPLES = int(os.environ.get("ORCH_ML_MIN_SAMPLES", "5") or 5)
_RETRAIN_INTERVAL = float(os.environ.get("ORCH_ML_RETRAIN_HOURS", "1") or 1)

_lock = threading.Lock()
_model = {}  # (kind, account) -> {successes, failures, avg_attempts}
_last_train = 0.0
_stats_data = {"predictions": 0, "train_count": 0, "accuracy_hits": 0}


def _complexity_bucket(prompt):
    """Classify task complexity from prompt length and keywords."""
    if not prompt:
        return "simple"
    length = len(prompt)
    if length > 2000 or any(k in prompt.lower() for k in ("refactor", "redesign", "migration", "architecture")):
        return "complex"
    if length > 500:
        return "medium"
    return "simple"


def train():
    """Retrain the routing model from the outcomes table."""
    global _last_train
    if not _ENABLED:
        return
    try:
        import db
        outcomes = db.select("outcomes", {
            "select": "kind,account,model,attempts,tests_passed,integrated",
            "order": "created_at.desc",
            "limit": "2000",
        }) or []

        new_model = {}
        for o in outcomes:
            kind = o.get("kind", "unknown")
            account = o.get("account", "unknown")
            key = (kind, account)
            if key not in new_model:
                new_model[key] = {"successes": 0, "failures": 0, "total_attempts": 0, "count": 0}
            entry = new_model[key]
            entry["count"] += 1
            entry["total_attempts"] += (o.get("attempts") or 1)
            if o.get("integrated") or o.get("tests_passed"):
                entry["successes"] += 1
            else:
                entry["failures"] += 1

        with _lock:
            _model.clear()
            _model.update(new_model)
            _stats_data["train_count"] += 1
            _last_train = time.time()

        _log.info("ml_task_router trained on %d outcomes, %d route keys", len(outcomes), len(new_model))
    except Exception as exc:
        _log.warning("ml_task_router train failed: %s", exc)


def predict_route(task):
    """Predict the best account/model for a task based on historical success rates.

    Returns {"account": str, "model": str, "confidence": float, "reason": str}
    """
    if not _ENABLED:
        return {"account": "", "model": "", "confidence": 0.0, "reason": "ml router disabled"}

    # Auto-retrain if stale
    if time.time() - _last_train > _RETRAIN_INTERVAL * 3600:
        train()

    kind = ""
    if isinstance(task, dict):
        kind = task.get("kind", "build")

    with _lock:
        candidates = []
        for (k, account), entry in _model.items():
            if k != kind:
                continue
            if entry["count"] < _MIN_SAMPLES:
                continue
            success_rate = entry["successes"] / max(entry["count"], 1)
            avg_attempts = entry["total_attempts"] / max(entry["count"], 1)
            # Score: high success rate + low attempts = best
            score = success_rate / max(avg_attempts, 0.5)
            candidates.append((score, account, success_rate, avg_attempts, entry["count"]))

        _stats_data["predictions"] += 1

    if not candidates:
        return {"account": "", "model": "", "confidence": 0.0,
                "reason": f"no historical data for kind={kind}"}

    candidates.sort(reverse=True)
    best_score, best_account, best_rate, best_avg, best_n = candidates[0]
    confidence = min(1.0, best_rate * math.log2(max(best_n, 2)) / 5)

    return {
        "account": best_account,
        "model": "",
        "confidence": round(confidence, 3),
        "reason": f"best for kind={kind}: {best_account} (rate={best_rate:.2f}, avg_attempts={best_avg:.1f}, n={best_n})",
    }


def stats():
    """Return router statistics."""
    with _lock:
        return {
            "predictions": _stats_data["predictions"],
            "train_count": _stats_data["train_count"],
            "route_keys": len(_model),
            "last_train": _last_train,
        }
