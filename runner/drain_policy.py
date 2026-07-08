#!/usr/bin/env python3
"""Backlog drain policy for scheduled jobs.

When the queue is deep, the orchestrator should spend lanes on recovery,
prewarm, merge, deploy, dedup, and verified zero-token reuse rather than
continuing to generate net-new work. This module is intentionally tiny and
env-driven so child jobs can adopt drain mode without waiting for the long-lived
runner process to restart.
"""
import os


FALSEY = {"0", "false", "no", "off", "disabled"}
TRUTHY = {"1", "true", "yes", "on", "enabled"}

DEFAULT_SKIP_JOBS = {
    # NOTE: "improve" and "meta_loop.py" intentionally excluded —
    # continuous self-improvement must never be throttled (user directive)
    "scout",
    "spec",
    "bizradar",
    "roadmap",
    "newapp",
    "committees",
    "committeeboard",
    "committeewatch",
    "committeemeta",
    "committeedocket",
    "committeedigest",
    "committeeminutes",
    "committeekg",
    "committeecal",
    "committeerollout",
    "agentmarket",
    "commonbrain",
    "demand_mining.py",
    "capability_radar.py",
    "feedback_review.py",
    "experiment_portfolio.py",
    "predictive_scheduler.py",
    "coder_canary.py",
    "model_historical_canary.py",
}

DEFAULT_ALLOW_JOBS = {
    "autopilot",
    "prewarm",
    "preflight",
    "merge_train.py",
    "releasetrain",
    "release_train.py",
    "deployverify",
    "deploy_watch.py",
    "integration_sweeper.py",
    "queue_elimination.py",
    "batch_fusion.py",
    "backlogcompact",
    "contcompact",
    "dedup",
    "unstick",
    "dagfix",
    "batchmech",
    "quarantine",
    "remediate",
    "worktreegc",
    "resource_governor.py",
    "usage_meter.py",
    "slo_controller.py",
    "capacity_pacer.py",
}


def _csv(name, default):
    raw = os.environ.get(name)
    if raw is None:
        return set(default)
    return {x.strip() for x in raw.split(",") if x.strip()}


def _mode():
    return os.environ.get("ORCH_DRAIN_MODE", "auto").strip().lower()


def _floor():
    try:
        return max(0, int(os.environ.get("ORCH_DRAIN_QUEUE_FLOOR", "800")))
    except Exception:
        return 800


def _approx_queued(limit):
    """Cheap threshold probe; exact counts are left to queue_counters/autopilot."""
    try:
        import db

        rows = db.select("tasks", {"select": "id", "state": "eq.QUEUED", "limit": str(limit)}) or []
        return len(rows)
    except Exception:
        return 0


def enabled(queue_depth=None):
    mode = _mode()
    if mode in FALSEY:
        return False
    if mode in TRUTHY:
        return True
    if mode != "auto":
        return False
    floor = _floor()
    depth = queue_depth if queue_depth is not None else _approx_queued(floor + 1)
    return depth >= floor


def should_skip(job, queue_depth=None):
    if job in _csv("ORCH_DRAIN_ALLOW_JOBS", DEFAULT_ALLOW_JOBS):
        return False
    if job not in _csv("ORCH_DRAIN_SKIP_JOBS", DEFAULT_SKIP_JOBS):
        return False
    return enabled(queue_depth=queue_depth)


def skip_reason(job, queue_depth=None):
    if not should_skip(job, queue_depth=queue_depth):
        return ""
    mode = _mode()
    if mode in TRUTHY:
        return f"drain_mode={mode}"
    return f"drain_mode=auto queue>={_floor()}"


def status():
    return {
        "enabled": enabled(),
        "mode": _mode(),
        "floor": _floor(),
        "skip_jobs": sorted(_csv("ORCH_DRAIN_SKIP_JOBS", DEFAULT_SKIP_JOBS)),
        "allow_jobs": sorted(_csv("ORCH_DRAIN_ALLOW_JOBS", DEFAULT_ALLOW_JOBS)),
    }
