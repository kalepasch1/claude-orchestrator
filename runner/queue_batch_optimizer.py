"""queue_batch_optimizer.py — optimal batch size for queue processing.

The cowork executor and runner both claim tasks in batches. Too small wastes
round-trips; too large starves other workers and risks zombie accumulation.
This module computes an optimal batch size from current queue depth, active
workers, and historical throughput.

Fail-soft: returns a conservative default (3) on any calculation error.
"""
from __future__ import annotations

import logging
import math
import os

logger = logging.getLogger(__name__)

DEFAULT_BATCH = int(os.environ.get("ORCH_DEFAULT_BATCH_SIZE", "5"))
MIN_BATCH = int(os.environ.get("ORCH_MIN_BATCH_SIZE", "1"))
MAX_BATCH = int(os.environ.get("ORCH_MAX_BATCH_SIZE", "10"))


def optimal_batch_size(
    queue_depth: int,
    active_workers: int = 1,
    avg_task_duration_s: float = 300.0,
    target_utilization: float = 0.8,
) -> int:
    """Compute optimal batch size.

    Args:
        queue_depth: number of QUEUED tasks
        active_workers: concurrent executor sessions
        avg_task_duration_s: mean seconds per task (from history)
        target_utilization: fraction of worker time that should be busy

    Returns:
        Clamped batch size between MIN_BATCH and MAX_BATCH.
    """
    try:
        if queue_depth <= 0 or active_workers <= 0:
            return MIN_BATCH

        # Fair share: divide queue evenly among workers, with utilization target
        fair_share = math.ceil(queue_depth / active_workers * target_utilization)

        # Don't grab more than what one worker can process in a reasonable window
        # (30 min window / avg duration = max tasks per window)
        window_s = 1800  # 30 minutes
        throughput_cap = max(1, int(window_s / max(avg_task_duration_s, 1)))

        batch = min(fair_share, throughput_cap, MAX_BATCH)
        batch = max(batch, MIN_BATCH)

        logger.debug(
            "batch_optimizer: depth=%d workers=%d fair=%d cap=%d -> %d",
            queue_depth, active_workers, fair_share, throughput_cap, batch,
        )
        return batch

    except Exception as exc:
        logger.warning("batch_optimizer fail-soft: %s", exc)
        return DEFAULT_BATCH


def should_throttle(
    queue_depth: int,
    running_count: int,
    max_running: int = 20,
) -> bool:
    """Whether to pause claiming — too many RUNNING tasks suggests zombies."""
    try:
        if running_count >= max_running:
            return True
        # If running >> queue, something is stuck
        if queue_depth > 0 and running_count > queue_depth * 2:
            return True
        return False
    except Exception:
        return False


def priority_weight(attempt: int, kind: str) -> float:
    """Score for queue ordering — lower attempt and harder kinds first.

    Returns a float where higher = should be claimed sooner.
    """
    try:
        kind_weights = {
            "bugfix": 1.5,
            "build": 1.0,
            "improve": 0.8,
            "test": 0.7,
        }
        base = kind_weights.get((kind or "").lower(), 1.0)
        # Penalize high-attempt tasks slightly (diminishing returns)
        attempt_factor = 1.0 / (1 + max(0, int(attempt or 0)) * 0.2)
        return base * attempt_factor
    except Exception:
        return 1.0
