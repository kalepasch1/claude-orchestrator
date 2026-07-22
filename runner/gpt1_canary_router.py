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
