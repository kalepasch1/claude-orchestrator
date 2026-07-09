#!/usr/bin/env python3
"""Train a logistic regression for branch need prediction.

Implements gradient descent with L2 regularization in pure Python stdlib
so it runs without numpy or scikit-learn.

Entry point: train_model_pipeline()
"""
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import branch_prediction_config as config
import branch_prediction_data_pipeline as pipeline


# ── core logistic regression ───────────────────────────────────────────────────

def _sigmoid(x):
    x = max(-500.0, min(500.0, x))
    return 1.0 / (1.0 + math.exp(-x))


def _predict_proba(weights, bias, features):
    z = sum(w * f for w, f in zip(weights, features)) + bias
    return _sigmoid(z)


def train_logistic_regression(X, y, lr=None, epochs=None, l2=None):
    """Fit logistic regression via gradient descent.

    Returns (weights: list[float], bias: float).
    """
    lr = lr if lr is not None else config.TRAIN_LR
    epochs = epochs if epochs is not None else config.TRAIN_EPOCHS
    l2 = l2 if l2 is not None else config.TRAIN_L2

    if not X:
        return [], 0.0

    n_features = len(X[0])
    weights = [0.0] * n_features
    bias = 0.0
    n = len(X)

    for _ in range(epochs):
        dw = [0.0] * n_features
        db = 0.0
        for xi, yi in zip(X, y):
            err = _predict_proba(weights, bias, xi) - yi
            for j, xij in enumerate(xi):
                dw[j] += err * xij
            db += err
        for j in range(n_features):
            weights[j] -= lr * (dw[j] / n + l2 * weights[j])
        bias -= lr * db / n

    return weights, bias


# ── evaluation ─────────────────────────────────────────────────────────────────

def compute_metrics(weights, bias, X, y, threshold=None):
    """Return precision, recall, F1, and accuracy as a dict."""
    threshold = threshold if threshold is not None else config.NEEDED_THRESHOLD
    tp = fp = fn = tn = 0
    for xi, yi in zip(X, y):
        pred = 1 if _predict_proba(weights, bias, xi) >= threshold else 0
        if pred == 1 and yi == 1:
            tp += 1
        elif pred == 1 and yi == 0:
            fp += 1
        elif pred == 0 and yi == 1:
            fn += 1
        else:
            tn += 1
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    rec = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * prec * rec / (prec + rec)) if (prec + rec) else 0.0
    acc = (tp + tn) / max(1, tp + fp + fn + tn)
    return {"precision": prec, "recall": rec, "f1": f1, "accuracy": acc,
            "tp": tp, "fp": fp, "fn": fn, "tn": tn}


# ── persistence ────────────────────────────────────────────────────────────────

def save_model(weights, bias, metrics, path=None):
    """Write model state to a JSON file. Creates parent dirs as needed."""
    path = path or config.MODEL_PATH
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    obj = {
        "weights": weights,
        "bias": bias,
        "feature_names": config.FEATURE_NAMES,
        "metrics": metrics,
        "threshold": config.NEEDED_THRESHOLD,
    }
    with open(path, "w") as f:
        json.dump(obj, f, indent=2)
    return path


def load_model(path=None):
    """Load model JSON. Returns (weights, bias, threshold) or raises on error."""
    path = path or config.MODEL_PATH
    with open(path) as f:
        obj = json.load(f)
    return obj["weights"], obj["bias"], obj.get("threshold", config.NEEDED_THRESHOLD)


# ── pipeline ───────────────────────────────────────────────────────────────────

def train_model_pipeline(use_synthetic_fallback=True, limit=2000, model_path=None):
    """Load data → train → evaluate → save.

    Falls back to synthetic data when the DB is unavailable or has fewer than
    MIN_TRAINING_SAMPLES rows, so the model is always deployable from day one.

    Returns a result dict:
        model_path        – path to saved JSON
        metrics           – {train: {...}, test: {...}, n_train, n_test}
        f1                – test F1 (or train F1 when no test split)
        meets_threshold   – f1 >= MIN_F1_SCORE
        synthetic         – True when synthetic data was used
        error             – present only on hard failure
    """
    X_train, y_train, X_test, y_test = pipeline.prepare_training_data(limit=limit)
    used_synthetic = False

    if not X_train:
        if not use_synthetic_fallback:
            return {"error": "insufficient training data"}
        events = pipeline.generate_synthetic_data(n=400)
        train_ev, test_ev = pipeline.train_test_split(events)
        X_train = [pipeline.extract_features(e) for e in train_ev]
        y_train = [int(e["label"]) for e in train_ev]
        X_test = [pipeline.extract_features(e) for e in test_ev]
        y_test = [int(e["label"]) for e in test_ev]
        used_synthetic = True

    weights, bias = train_logistic_regression(X_train, y_train)
    train_m = compute_metrics(weights, bias, X_train, y_train)
    test_m = compute_metrics(weights, bias, X_test, y_test) if X_test else {}

    metrics = {"train": train_m, "test": test_m,
               "n_train": len(X_train), "n_test": len(X_test)}
    path = save_model(weights, bias, metrics, path=model_path)

    f1 = test_m.get("f1") if test_m else train_m.get("f1", 0.0)
    return {
        "model_path": path,
        "metrics": metrics,
        "f1": f1,
        "meets_threshold": f1 >= config.MIN_F1_SCORE,
        "synthetic": used_synthetic,
    }


if __name__ == "__main__":
    import json as _json
    result = train_model_pipeline()
    print(_json.dumps(result, indent=2, default=str))
