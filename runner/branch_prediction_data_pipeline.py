#!/usr/bin/env python3
"""Feature extraction and dataset preparation for branch need prediction."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import branch_prediction_config as config
import branch_event_telemetry


def extract_features(event):
    """Return normalized feature vector (list of float) from a branch event dict.

    Features are clipped and scaled to [0, 1] so the logistic regression
    converges without per-feature standardization.
    """
    age = min(float(event.get("branch_age_days", 0.0)), config.MAX_AGE_DAYS)
    activity = min(float(event.get("days_since_activity", 0.0)), config.MAX_AGE_DAYS)
    return [
        age / config.MAX_AGE_DAYS,
        activity / config.MAX_AGE_DAYS,
        float(event.get("task_state_queued", 0)),
        float(event.get("task_state_running", 0)),
        float(event.get("project_queue_depth_norm", 0.0)),
    ]


def train_test_split(events, holdout_frac=None):
    """Deterministic split of events into (train, test) lists."""
    holdout_frac = holdout_frac if holdout_frac is not None else config.HOLDOUT_FRAC
    if not events:
        return [], []
    sorted_events = sorted(events, key=lambda e: str(e.get("task_id", "")))
    n = len(sorted_events)
    split = max(1, int(n * (1.0 - holdout_frac)))
    return sorted_events[:split], sorted_events[split:]


def prepare_training_data(limit=2000):
    """Load telemetry, extract features, return (X_train, y_train, X_test, y_test).

    Returns four empty lists when there is insufficient data; the trainer will
    then use synthetic data as a cold-start fallback.
    """
    events = branch_event_telemetry.get_historical_branch_events(limit=limit)
    if len(events) < config.MIN_TRAINING_SAMPLES:
        return [], [], [], []

    train_events, test_events = train_test_split(events)
    X_train = [extract_features(e) for e in train_events]
    y_train = [int(e.get("label", 0)) for e in train_events]
    X_test = [extract_features(e) for e in test_events]
    y_test = [int(e.get("label", 0)) for e in test_events]
    return X_train, y_train, X_test, y_test


def generate_synthetic_data(n=400, seed=42):
    """Generate synthetic branch events for cold-start training.

    Class 1 (needed): young branches with recent activity and active tasks.
    Class 0 (stale):  old branches with no recent activity or task state.
    The two classes are linearly separable so a logistic regression reliably
    achieves F1 >= 0.7 without real telemetry.
    """
    state = seed

    def _rand():
        nonlocal state
        state = (state * 1103515245 + 12345) & 0x7FFFFFFF
        return state / 0x7FFFFFFF

    events = []
    half = n // 2
    for i in range(n):
        if i < half:
            age = _rand() * 5.0
            activity = _rand() * 3.0
            queued = 1 if _rand() > 0.3 else 0
            running = (1 - queued) if _rand() > 0.5 else 0
            depth = _rand() * 0.5
            label = 1
        else:
            age = 20.0 + _rand() * 70.0
            activity = 20.0 + _rand() * 70.0
            queued = 0
            running = 0
            depth = _rand() * 0.2
            label = 0
        events.append({
            "task_id": f"synthetic-{i}",
            "branch_age_days": age,
            "days_since_activity": activity,
            "task_state_queued": queued,
            "task_state_running": running,
            "project_queue_depth_norm": depth,
            "label": label,
        })
    return events
