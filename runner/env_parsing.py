#!/usr/bin/env python3
"""
env_parsing.py - Safe, fail-soft environment variable parsing.

Provides helpers for parsing numeric and boolean environment variables
that never raise exceptions. Returns sensible defaults on any parsing
error, preventing module-level crashes from misconfigured env vars.

This prevents issues like:
  float(os.environ.get("THRESHOLD", "2.0"))  # crashes if THRESHOLD="bad"
  int(os.environ.get("MAX_COUNT", "50"))     # crashes if MAX_COUNT="xyz"

All functions are safe to call at module level and in tight loops.
"""
import os
from typing import Any, Optional


def parse_int(name: str, default: int, minimum: Optional[int] = None,
              maximum: Optional[int] = None) -> int:
    """Parse an environment variable as int, with bounds checking.

    Args:
        name: Environment variable name
        default: Default value if missing or unparseable
        minimum: Minimum acceptable value (inclusive)
        maximum: Maximum acceptable value (inclusive)

    Returns:
        Parsed int value, default if error, or bounded value if out of range.
        Never raises.
    """
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
        if minimum is not None and value < minimum:
            return minimum
        if maximum is not None and value > maximum:
            return maximum
        return value
    except (ValueError, TypeError):
        return default


def parse_float(name: str, default: float, minimum: Optional[float] = None,
                maximum: Optional[float] = None) -> float:
    """Parse an environment variable as float, with bounds checking.

    Args:
        name: Environment variable name
        default: Default value if missing or unparseable
        minimum: Minimum acceptable value (inclusive)
        maximum: Maximum acceptable value (inclusive)

    Returns:
        Parsed float value, default if error, or bounded value if out of range.
        Never raises.
    """
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
        if minimum is not None and value < minimum:
            return minimum
        if maximum is not None and value > maximum:
            return maximum
        return value
    except (ValueError, TypeError):
        return default


def parse_bool(name: str, default: bool = False) -> bool:
    """Parse an environment variable as bool.

    Recognizes as True: "1", "true", "yes", "on" (case-insensitive)
    Recognizes as False: "0", "false", "no", "off" (case-insensitive)
    Missing or unrecognized values return default.

    Args:
        name: Environment variable name
        default: Default value if missing or unrecognized

    Returns:
        Parsed bool value or default. Never raises.
    """
    raw = os.environ.get(name, "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    return default


def parse_str(name: str, default: str = "") -> str:
    """Parse an environment variable as string.

    Returns the value if present and non-empty, else default.
    Strips leading/trailing whitespace.

    Args:
        name: Environment variable name
        default: Default value if missing or empty

    Returns:
        Parsed string value or default. Never raises.
    """
    raw = os.environ.get(name, "").strip()
    return raw if raw else default
