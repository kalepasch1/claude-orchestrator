#!/usr/bin/env python3
"""
risk_predictor.py - simple merge-risk prediction using logistic regression.

Uses historical pass/fail outcomes to predict whether a proposed change
(characterized by feature vector: lines_changed, files_changed, has_tests,
author_history_pass_rate, test_coverage_pct) is likely to pass or fail merge.

Fail-soft: returns a neutral 0.5 risk score on any error.
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


class RiskPredictor:
    """Simple logistic regression risk predictor trained on merge outcomes."""

    def __init__(self, weights=None, bias=0.0):
        # Default weights: [lines_changed, files_changed, has_tests, author_pass_rate, test_coverage]
        self.weights = weights or [0.002, 0.01, -0.8, -1.5, -0.02]
        self.bias = bias

    def _sigmoid(self, z):
        z = max(-500, min(500, z))
        return 1.0 / (1.0 + math.exp(-z))

    def predict_risk(self, lines_changed=0, files_changed=0, has_tests=True,
                     author_pass_rate=1.0, test_coverage_pct=80.0):
        """Return risk score 0.0 (safe) to 1.0 (risky). Fail-soft: returns 0.5 on error."""
        try:
            features = [
                max(0, lines_changed or 0),
                max(0, files_changed or 0),
                1.0 if has_tests else 0.0,
                max(0.0, min(1.0, author_pass_rate if author_pass_rate is not None else 0.5)),
                max(0.0, min(100.0, test_coverage_pct if test_coverage_pct is not None else 0.0)),
            ]
            z = self.bias + sum(w * f for w, f in zip(self.weights, features))
            return round(self._sigmoid(z), 4)
        except Exception:
            return 0.5

    def train(self, examples, lr=0.01, epochs=100):
        """Train on list of (features_dict, passed_bool). Mutates weights/bias in place."""
        if not examples:
            return
        for _ in range(epochs):
            for feat, passed in examples:
                score = self.predict_risk(**feat)
                target = 0.0 if passed else 1.0
                error = score - target
                features = [
                    feat.get("lines_changed", 0),
                    feat.get("files_changed", 0),
                    1.0 if feat.get("has_tests", True) else 0.0,
                    feat.get("author_pass_rate", 1.0),
                    feat.get("test_coverage_pct", 80.0),
                ]
                for i in range(len(self.weights)):
                    self.weights[i] -= lr * error * features[i]
                self.bias -= lr * error


# Module-level singleton
_predictor = RiskPredictor()


def predict_risk(**kwargs):
    return _predictor.predict_risk(**kwargs)
