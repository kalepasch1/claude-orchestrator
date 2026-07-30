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


def parse_iso_timestamp(iso_str: str) -> Optional[datetime.datetime]:
    """Parse an ISO 8601 timestamp string safely.

    Args:
        iso_str: ISO timestamp string (with or without timezone)

    Returns:
        datetime object or None if parsing fails
    """
    if not iso_str or not isinstance(iso_str, str):
        return None
    try:
        if iso_str.endswith('Z'):
            iso_str = iso_str[:-1] + '+00:00'
        return datetime.datetime.fromisoformat(iso_str)
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
