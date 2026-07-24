#!/usr/bin/env python3
"""
provider_rate_tracker.py - per-provider rate-limit state for parallel-safe routing.

Tracks which providers are currently throttled (due to 429 / "too many requests" / overloaded
responses) so the coder-selection path can prefer unthrottled providers when routing parallel
tasks, instead of piling every task onto the same already-saturated provider.

No secrets, no API calls, no key management. Pure in-memory state (TTL-based cooldown).

Usage:
    import provider_rate_tracker as prt

    # call when the runner detects a rate-limit response from `coder`
    prt.record_rate_limit("deepseek")

    # returns True while the cooldown window is active
    prt.is_throttled("openai")

    # sort providers so unthrottled ones come first
    ordered = prt.preferred_order(["claude", "deepseek", "openai"])
"""
# PEP 604 (`int | None`) in a signature is evaluated at DEFINITION time, which is a
# TypeError on Python 3.9 — the interpreter this fleet runs. Without this import the
# module cannot even be imported, so test_provider_rate_tracker.py aborted collection
# of the WHOLE suite on orchestrator/dev, which is the release_train's verification
# gate. Net effect: nothing could be promoted dev -> master (13 days of divergence).
from __future__ import annotations

import os
import threading
import time
from typing import Optional

_lock = threading.Lock()
_throttle_until: dict[str, float] = {}  # provider -> epoch-seconds when cooldown expires

DEFAULT_COOLDOWN_S = int(os.environ.get("ORCH_RATE_COOLDOWN_S", "60"))
MAX_COOLDOWN_S = int(os.environ.get("ORCH_RATE_MAX_COOLDOWN_S", "300"))


def record_rate_limit(provider: str, cooldown_s: Optional[int] = None) -> None:
    """Mark `provider` as throttled for `cooldown_s` seconds.

    Subsequent calls extend the window multiplicatively (up to MAX_COOLDOWN_S) so a sustained
    rate-limit stream backs off progressively without wedging the tracker.
    """
    if not provider:
        return
    now = time.monotonic()
    want = int(cooldown_s or DEFAULT_COOLDOWN_S)
    with _lock:
        existing = _throttle_until.get(provider, 0.0)
        remaining = max(0.0, existing - now)
        # double remaining time on each new hit, capped at MAX_COOLDOWN_S
        new_cooldown = min(MAX_COOLDOWN_S, want if remaining == 0.0 else int(remaining * 2) + want)
        _throttle_until[provider] = now + new_cooldown


def is_throttled(provider: str) -> bool:
    """Return True while the provider is within its cooldown window."""
    if not provider:
        return False
    with _lock:
        return time.monotonic() < _throttle_until.get(provider, 0.0)


def preferred_order(providers: list[str]) -> list[str]:
    """Return `providers` sorted so unthrottled ones come first.

    Preserves the original relative order within each group so the caller's
    existing priority logic is only minimally perturbed.
    """
    now = time.monotonic()
    with _lock:
        snapshot = dict(_throttle_until)

    def _throttled(p):
        return now < snapshot.get(p, 0.0)

    free = [p for p in providers if not _throttled(p)]
    busy = [p for p in providers if _throttled(p)]
    return free + busy


def clear(provider: Optional[str] = None) -> None:
    """Remove throttle state. Pass None to clear all providers (useful in tests)."""
    with _lock:
        if provider is None:
            _throttle_until.clear()
        else:
            _throttle_until.pop(provider, None)


def status() -> dict[str, float]:
    """Return seconds remaining per throttled provider (0.0 = not throttled). For diagnostics."""
    now = time.monotonic()
    with _lock:
        return {p: max(0.0, round(until - now, 1)) for p, until in _throttle_until.items()}
