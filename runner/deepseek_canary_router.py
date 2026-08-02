#!/usr/bin/env python3
"""DeepSeek canary traffic router.

Routes DeepSeek coder requests to the 'canary' or 'control' arm based on a
rollout percentage (0-100). Adapted from runner/gpt1_canary_router.py
(canary-gpt-1-slice-4), with deterministic md5-based bucketing so a given
request id lands in the same arm in every process — Python's built-in hash()
is salted per interpreter and cannot provide that guarantee.

Configuration (env vars, read per call so fleet_config pushes apply live):
  ORCH_DEEPSEEK_CANARY_ENABLED  - "true"/"1"/"yes"/"on" to enable (default off)
  ORCH_DEEPSEEK_CANARY_PERCENT  - rollout percent, clamped to 0-100 (default 0)

Fail-soft: any error routes to 'control' so a bad config value can never
wedge the coder pool.
"""
import hashlib
import os

CANARY = "canary"
CONTROL = "control"

_BUCKETS = 10000


def _enabled() -> bool:
    raw = os.environ.get("ORCH_DEEPSEEK_CANARY_ENABLED", "false")
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def _percent() -> float:
    try:
        pct = float(os.environ.get("ORCH_DEEPSEEK_CANARY_PERCENT", "0"))
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(100.0, pct))


def _bucket(request_id) -> int:
    digest = hashlib.md5(str(request_id).encode("utf-8", errors="replace")).hexdigest()
    return int(digest[:8], 16) % _BUCKETS


def route_deepseek_request(request_id, override_percent=None) -> str:
    """Return 'canary' or 'control' for a DeepSeek request.

    Deterministic per request_id: the same id always maps to the same arm for
    a given percentage, and an id in the canary arm at pct stays there for any
    higher pct (buckets are ordered, so rollouts only ever widen the arm).
    """
    try:
        if not _enabled():
            return CONTROL
        if override_percent is None:
            pct = _percent()
        else:
            try:
                pct = max(0.0, min(100.0, float(override_percent)))
            except (TypeError, ValueError):
                pct = _percent()
        if pct <= 0:
            return CONTROL
        if pct >= 100:
            return CANARY
        return CANARY if _bucket(request_id) < pct * (_BUCKETS / 100.0) else CONTROL
    except Exception:
        return CONTROL


def get_canary_stats() -> dict:
    """Return current canary configuration for operators and tests."""
    return {
        "coder": "deepseek",
        "enabled": _enabled(),
        "percent": _percent(),
    }
