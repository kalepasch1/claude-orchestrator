#!/usr/bin/env python3
"""
config_policy_engine.py — rule engine for fleet_config validation.

Validates config key/value pairs against safety rules before they are applied
fleet-wide. Rejects keys containing credential markers and keys outside the
allowed prefix set.

Fail-soft: returns validation result dict; never raises.
"""
import os
import sys
import re
import logging

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

log = logging.getLogger("config_policy_engine")

_SAFE_PREFIXES = (
    "ORCH_", "MAX_PARALLEL", "PER_TASK_GB", "RAM_FLOOR_GB", "RAM_",
    "RELEASE_", "QUEUE_", "CONT_", "JANITOR_", "REMEDIATION_",
    "DEFAULT_TEST_CMD", "TASK_TIMEOUT", "ENABLE_", "SESSION_",
    "ACCOUNT_COOLDOWN", "MERGE_", "DEPLOY_", "INTEGRATE_", "COST_",
)
_DENY_MARKERS = ("KEY", "SECRET", "TOKEN", "PASSWORD", "PWD", "CREDENTIAL")

# Value constraints: max length, no control chars
MAX_VALUE_LEN = 4096
_CONTROL_RE = re.compile(r"[\x00-\x08\x0e-\x1f]")


def is_safe_config_key(key):
    """Check if a config key is safe for fleet-wide application.

    Returns True if the key matches allowed prefixes and contains no
    credential markers.
    """
    if not key or not isinstance(key, str):
        return False
    ku = key.upper()
    if any(m in ku for m in _DENY_MARKERS):
        return False
    return any(ku.startswith(p) for p in _SAFE_PREFIXES)


def validate_value(value):
    """Validate a config value. Returns (ok, reason)."""
    if value is None:
        return False, "value is None"
    s = str(value)
    if len(s) > MAX_VALUE_LEN:
        return False, f"value exceeds {MAX_VALUE_LEN} chars"
    if _CONTROL_RE.search(s):
        return False, "value contains control characters"
    return True, ""


def validate_batch(entries):
    """Validate a batch of config entries.

    Args:
        entries: list of dicts with 'key' and 'value'.

    Returns:
        dict with 'rejected' (list of {key, reason}) and 'valid' (bool).
    """
    rejected = []
    try:
        for entry in (entries or []):
            k = entry.get("key", "")
            v = entry.get("value")
            if not is_safe_config_key(k):
                rejected.append({"key": k, "reason": "unsafe key"})
                continue
            ok, reason = validate_value(v)
            if not ok:
                rejected.append({"key": k, "reason": reason})
    except Exception as exc:
        log.warning("validate_batch error: %s", exc)
    return {"rejected": rejected, "valid": len(rejected) == 0}


def validate_and_filter(entries):
    """Return only the valid entries from a batch.

    Args:
        entries: list of dicts with 'key' and 'value'.

    Returns:
        tuple of (valid_entries, rejected_entries).
    """
    valid = []
    rejected = []
    try:
        for entry in (entries or []):
            k = entry.get("key", "")
            v = entry.get("value")
            if not is_safe_config_key(k):
                rejected.append({"key": k, "reason": "unsafe key"})
                continue
            ok, reason = validate_value(v)
            if not ok:
                rejected.append({"key": k, "reason": reason})
                continue
            valid.append(entry)
    except Exception as exc:
        log.warning("validate_and_filter error: %s", exc)
    return valid, rejected
