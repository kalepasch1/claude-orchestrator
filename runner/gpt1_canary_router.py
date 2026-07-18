"""
gpt1_canary_router.py — GPT-1 canary router for A/B model distribution.

Routes a configurable percentage of requests to GPT-1 (canary) vs the
current production model. Env-gated, defaults to 0% canary traffic.
"""
import os
import random

CANARY_ENABLED = os.environ.get('GPT1_CANARY_ENABLED', '0') == '1'
CANARY_PERCENT = float(os.environ.get('GPT1_CANARY_PERCENT', '0'))

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

def get_canary_stats() -> dict:
    """Return current canary configuration."""
    return {
        'enabled': CANARY_ENABLED,
        'percent': CANARY_PERCENT,
    }
