#!/usr/bin/env python3
"""
common_utils.py - Shared utility functions extracted from zombie-reaper and pricing modules.

Consolidates duplicate patterns for:
  - ISO timestamp parsing and comparison
  - Safe string truncation at byte limits
  - Tiered/sequential logic evaluation
  - Safe string coercion from model outputs
"""
import datetime
import json
import re
from typing import Optional, Tuple, Any, List, Callable


def safe_string_coerce(v: Any) -> str:
    """Safely coerce any model-returned value to a sliceable string.

    The model intermittently returns dict/list where schema says string;
    `somedict[:1500]` then throws KeyError: slice. This function ensures
    any value can be safely sliced as a string.

    Args:
        v: Any value (None, str, dict, list, etc.)

    Returns:
        Safe string representation that can be sliced
    """
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    try:
        return json.dumps(v, ensure_ascii=False)
    except Exception:
        return str(v)


def truncate_string_at_bytes(s: str, max_bytes: int = 1000) -> str:
    """Safely truncate a string to a maximum byte length.

    Args:
        s: The string to truncate
        max_bytes: Maximum byte length (default 1000)

    Returns:
        Truncated string (encoded as UTF-8, then decoded)
    """
    if not s:
        return s
    encoded = str(s).encode('utf-8')
    if len(encoded) <= max_bytes:
        return s
    truncated = encoded[:max_bytes]
    try:
        return truncated.decode('utf-8', errors='ignore')
    except Exception:
        return truncated.decode('utf-8', errors='replace')


#: Fractional-second digits, captured so they can be padded to what
#: datetime.fromisoformat() accepts on Python < 3.11.
_FRACTIONAL_SECONDS = re.compile(r"(\.\d+)")


def parse_iso_timestamp(iso_str: str) -> Optional[datetime.datetime]:
    """Parse an ISO 8601 timestamp string safely.

    THE BUG THIS FIXES (found 2026-08-30)
    -------------------------------------
    Before Python 3.11, datetime.fromisoformat() accepts EXACTLY 3 or 6
    fractional-second digits and raises ValueError on anything else. Postgres
    renders timestamptz with trailing zeros trimmed, so it emits 1-6 digits
    depending on the value — roughly one row in ten lands on a width this parser
    rejected. This machine runs Python 3.9.6.

    That silent ~10% failure rate wedged the fleet. integration_owner._live_hosts()
    treats an unparseable last_seen as LIVE (deliberately: refusing to integrate is
    safer than racing another host). The newest runner_heartbeats row read

        {"hostname": "Mac.lan", "last_seen": "2026-08-27T18:52:05.72819+00:00"}

    Five digits. It failed to parse, so a host that had been dead for 75 hours
    counted as live, won the ownership election, and every merge_train pass on the
    real host refused with "not the integration owner". 532 consecutive passes
    considered 0 branches. The module's own docstring promises this cannot happen:
    "if the owner stops heartbeating it drops out of live". It never did.

    Pad the fraction to 6 digits instead of hoping it arrives at a lucky width.

    Args:
        iso_str: ISO timestamp string (with or without timezone)

    Returns:
        datetime object or None if parsing fails
    """
    if not iso_str or not isinstance(iso_str, str):
        return None
    text = iso_str.strip()
    if text.endswith('Z'):
        text = text[:-1] + '+00:00'
    text = _FRACTIONAL_SECONDS.sub(
        lambda m: '.' + m.group(1)[1:][:6].ljust(6, '0'), text, count=1)
    try:
        return datetime.datetime.fromisoformat(text)
    except (ValueError, AttributeError, TypeError):
        return None


def is_older_than(iso_str: str, cutoff_iso: str) -> bool:
    """Check if a timestamp is older than a cutoff.

    Args:
        iso_str: ISO timestamp to check
        cutoff_iso: Cutoff ISO timestamp

    Returns:
        True if iso_str < cutoff_iso (treating invalid timestamps as very old)
    """
    if not iso_str or not isinstance(iso_str, str):
        return True
    if not cutoff_iso or not isinstance(cutoff_iso, str):
        return False
    parsed = parse_iso_timestamp(iso_str)
    cutoff = parse_iso_timestamp(cutoff_iso)
    if parsed is None:
        return True
    if cutoff is None:
        return False
    return parsed < cutoff


def apply_tiered_logic(tiers: List[Tuple[Callable, Any]], default: Any = None) -> Any:
    """Evaluate tiered conditions in order, returning first truthy result.

    Replaces multiple if/elif chains with declarative tier definitions.

    Args:
        tiers: List of (condition_fn, result) tuples
        default: Value to return if no tier matches

    Returns:
        Result value from first matching tier, or default

    Example:
        result = apply_tiered_logic([
            (lambda: account in live_runners, "runner_alive"),
            (lambda: is_older_than(updated_at, cutoff), "stale"),
        ], default="unknown")
    """
    for condition_fn, result in tiers:
        try:
            if callable(condition_fn):
                if condition_fn():
                    return result
            elif condition_fn:
                return result
        except Exception:
            continue
    return default


def consume_from_tier(current: int, tier_min: int, tier_max: Optional[int],
                      amount: int) -> Tuple[int, int]:
    """Calculate how many units can be consumed from a single tier.

    Used for tiered pricing, resource allocation, or sequential consumption.

    Args:
        current: Current position/units used
        tier_min: Minimum units for this tier
        tier_max: Maximum units for this tier (None = unlimited)
        amount: Amount to consume

    Returns:
        Tuple of (units_consumed, units_remaining)
    """
    if amount <= 0:
        return 0, amount
    if tier_max is None:
        consumed = amount
    else:
        start = max(current, tier_min - 1)
        capacity = tier_max - start
        consumed = min(amount, max(0, capacity))
    return consumed, amount - consumed
