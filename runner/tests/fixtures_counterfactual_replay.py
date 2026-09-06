#!/usr/bin/env python3
"""Fixture data for counterfactual replay tests."""
import json
from datetime import datetime, timedelta


def generate_decision_history(num_records=150):
    """Generate synthetic decision history for replay testing.

    Generates records with known divergences to test detection.
    """
    base_date = datetime(2026, 8, 1)
    history = []

    for i in range(num_records):
        task_id = f"task-{i:03d}"
        timestamp = (base_date + timedelta(hours=i)).isoformat()

        # Create patterns: some will diverge under new model
        if i % 3 == 0:
            # Old model chose haiku, new model would choose opus
            old_route = "haiku"
            new_route = "opus"
            old_conf = 0.65
            new_conf = 0.92
            diverges = True
        elif i % 5 == 0:
            # Old model chose sonnet, new model would choose opus
            old_route = "sonnet"
            new_route = "opus"
            old_conf = 0.70
            new_conf = 0.88
            diverges = True
        else:
            # No divergence
            old_route = "opus"
            new_route = "opus"
            old_conf = 0.90
            new_conf = 0.91
            diverges = False

        decision = {
            "task_id": task_id,
            "type": "routing",
            "timestamp": timestamp,
            "model": "old-model",
            "model_version": "1.0",
            "input": {
                "kind": ["build", "review", "merge", "test"][i % 4],
                "complexity": (i % 5) + 1,
                "priority": (i % 3) + 1,
            },
            "output": {
                "route": old_route,
                "confidence": old_conf,
                "policy": "cost_optimized" if i % 2 == 0 else "quality_optimized",
            }
        }
        history.append(decision)

    return history


def get_mock_decision_history():
    """Return standard test decision history."""
    return generate_decision_history(150)


def get_small_decision_history():
    """Return small test decision history for quick tests."""
    return generate_decision_history(10)


def count_expected_divergences(history, model_selector_fn=None):
    """Count how many records would diverge under a new model.

    By default, uses the pattern from generate_decision_history.
    """
    if model_selector_fn:
        divergences = 0
        for record in history:
            if model_selector_fn(record):
                divergences += 1
        return divergences

    # Use default pattern
    count = 0
    for i, record in enumerate(history):
        if i % 3 == 0 or i % 5 == 0:
            count += 1
    return count
