#!/usr/bin/env python3
"""GPT-1 canary traffic router.

Routes requests to 'canary' or 'control' endpoint based on a rollout
percentage (0-100). Deterministic at boundaries, random in between.
"""
import random


def route_gpt1_request_canary(request_context, canary_pct):
    """Return 'canary' or 'control' for a GPT-1 request given a rollout percentage (0-100)."""
    if canary_pct <= 0:
        return "control"
    if canary_pct >= 100:
        return "canary"
    return "canary" if random.random() * 100 < canary_pct else "control"

def get_canary_stats() -> dict:
    """Return current canary configuration."""
    return {
        'enabled': CANARY_ENABLED,
        'percent': CANARY_PERCENT,
    }

def route_request(request_id: str, override_percent: float | None = None) -> str:
    """Route a request to either 'canary' or 'production' model."""
    if not CANARY_ENABLED:
        return 'production'
    pct = override_percent if override_percent is not None else CANARY_PERCENT
    pct = max(0.0, min(100.0, pct))
    # Deterministic hash-based routing for consistency
    hash_val = hash(request_id) % 10000
    if hash_val < pct * 100:
        return 'canary'
    return 'production'

