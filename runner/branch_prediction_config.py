#!/usr/bin/env python3
"""Configuration constants for the branch-prediction ML model."""
import os

_RUNNER_DIR = os.path.dirname(os.path.abspath(__file__))
_RUNTIME_DIR = os.path.join(os.path.dirname(_RUNNER_DIR), ".runtime")

MODEL_PATH = os.environ.get(
    "BRANCH_PRED_MODEL_PATH",
    os.path.join(_RUNTIME_DIR, "branch_prediction_model.json"),
)

FEATURE_NAMES = [
    "branch_age_days",
    "days_since_activity",
    "task_state_queued",
    "task_state_running",
    "project_queue_depth_norm",
]

# Probability >= threshold → branch "needed"
NEEDED_THRESHOLD = float(os.environ.get("BRANCH_PRED_NEEDED_THRESHOLD", "0.5"))
MIN_F1_SCORE = float(os.environ.get("BRANCH_PRED_MIN_F1", "0.7"))

# Logistic regression hyperparameters
TRAIN_LR = float(os.environ.get("BRANCH_PRED_LR", "0.05"))
TRAIN_EPOCHS = int(os.environ.get("BRANCH_PRED_EPOCHS", "400"))
TRAIN_L2 = float(os.environ.get("BRANCH_PRED_L2", "0.01"))

# Feature clipping (normalize to [0, 1] before these max values)
MAX_AGE_DAYS = 90.0
MAX_QUEUE_DEPTH = 20.0

# Data split / minimum size
HOLDOUT_FRAC = 0.2
MIN_TRAINING_SAMPLES = 20
