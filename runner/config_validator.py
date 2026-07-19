#!/usr/bin/env python3
"""
config_validator.py - real-time validation of fleet configuration updates.

Validates config changes against INVARIANTS before they're applied fleet-wide
via fleet_control.py. Catches invalid values, type mismatches, and dangerous
combinations before they propagate.

Rules are defined as simple predicate functions. Each rule receives the
proposed config dict and returns (ok: bool, reason: str).

Env vars:
    ORCH_CONFIG_VALIDATOR          "true" (default) to enable
    ORCH_CONFIG_STRICT_MODE        "false" (default); if "true", reject unknown keys
"""
import os, sys, re

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import log as _log_mod
_log = _log_mod.get("config_validator")

ENABLED = os.environ.get("ORCH_CONFIG_VALIDATOR", "true").lower() in ("1", "true", "yes", "on")
STRICT = os.environ.get("ORCH_CONFIG_STRICT_MODE", "false").lower() in ("1", "true", "yes", "on")

# Known config keys and their expected types/ranges
KNOWN_KEYS = {
    "MAX_PARALLEL": {"type": "int", "min": 1, "max": 20},
    "ORCH_EXTRA_CODERS": {"type": "int", "min": 0, "max": 10},
    "PER_TASK_GB": {"type": "float", "min": 0.5, "max": 32},
    "RAM_FLOOR_GB": {"type": "float", "min": 1, "max": 64},
    "TASK_TIMEOUT": {"type": "int", "min": 60, "max": 7200},
    "ORCH_TEST_ORACLE": {"type": "bool"},
    "ORCH_AUTO_PULL": {"type": "bool"},
    "ORCH_USE_SUBSCRIPTION": {"type": "bool"},
    "MERGE_BATCH_SIZE": {"type": "int", "min": 1, "max": 50},
    "QUEUE_BANKRUPTCY_LIMIT": {"type": "int", "min": 10, "max": 1000},
}

# Keys that must never be set via fleet config
DENY_KEYS = {"SUPABASE_SERVICE_KEY", "ANTHROPIC_API_KEY", "SUPABASE_URL"}
DENY_PATTERNS = re.compile(r"(KEY|SECRET|TOKEN|PASSWORD|PWD|CREDENTIAL)", re.IGNORECASE)


def validate_key_value(key, value):
    """Validate a single key-value pair. Returns (ok, reason)."""
    # Deny list
    if key in DENY_KEYS or DENY_PATTERNS.search(key):
        return False, f"key '{key}' matches deny list (secrets/credentials)"

    # Check ORCH_ prefix convention
    spec = KNOWN_KEYS.get(key)

    if spec is None and STRICT:
        return False, f"unknown config key '{key}' in strict mode"

    if spec is None:
        # Unknown but not in deny list, allow in non-strict mode
        return True, "unknown key, allowed in non-strict mode"

    # Type validation
    expected_type = spec.get("type", "str")
    try:
        if expected_type == "int":
            v = int(value)
            lo, hi = spec.get("min", float("-inf")), spec.get("max", float("inf"))
            if not (lo <= v <= hi):
                return False, f"value {v} out of range [{lo}, {hi}] for {key}"
        elif expected_type == "float":
            v = float(value)
            lo, hi = spec.get("min", float("-inf")), spec.get("max", float("inf"))
            if not (lo <= v <= hi):
                return False, f"value {v} out of range [{lo}, {hi}] for {key}"
        elif expected_type == "bool":
            if value.lower() not in ("true", "false", "1", "0", "yes", "no", "on", "off"):
                return False, f"value '{value}' is not a valid boolean for {key}"
    except (ValueError, TypeError) as e:
        return False, f"type error for {key}: expected {expected_type}, got '{value}'"

    return True, "valid"


def validate_config(config_dict):
    """
    Validate a full config dict. Returns {valid: bool, issues: [{key, reason}]}.
    """
    if not ENABLED:
        return {"valid": True, "issues": []}

    issues = []
    for key, value in config_dict.items():
        ok, reason = validate_key_value(key, str(value))
        if not ok:
            issues.append({"key": key, "reason": reason})
            _log.warning("config validation failed: %s = %s -> %s", key, value, reason)

    return {"valid": len(issues) == 0, "issues": issues}


def validate_before_apply(key, value):
    """Single-key validation hook for fleet_control.py integration."""
    ok, reason = validate_key_value(key, str(value))
    if not ok:
        _log.warning("rejecting config update %s=%s: %s", key, value, reason)
    return ok, reason


# --- Tests ---
def test_valid_int_key():
    ok, reason = validate_key_value("MAX_PARALLEL", "4")
    assert ok, f"Expected valid, got: {reason}"


def test_int_out_of_range():
    ok, reason = validate_key_value("MAX_PARALLEL", "100")
    assert not ok, "Expected rejection for out of range"


def test_deny_key():
    ok, reason = validate_key_value("ANTHROPIC_API_KEY", "sk-xxx")
    assert not ok, "Expected rejection for deny key"


def test_deny_pattern():
    ok, reason = validate_key_value("MY_SECRET_VALUE", "abc")
    assert not ok, "Expected rejection for deny pattern"


def test_bool_valid():
    ok, reason = validate_key_value("ORCH_AUTO_PULL", "true")
    assert ok, f"Expected valid bool, got: {reason}"


def test_bool_invalid():
    ok, reason = validate_key_value("ORCH_AUTO_PULL", "maybe")
    assert not ok, "Expected rejection for invalid bool"


def test_validate_config_mixed():
    result = validate_config({"MAX_PARALLEL": "4", "ANTHROPIC_API_KEY": "sk-xxx"})
    assert not result["valid"]
    assert len(result["issues"]) == 1
    assert result["issues"][0]["key"] == "ANTHROPIC_API_KEY"


def test_unknown_key_non_strict():
    ok, reason = validate_key_value("MY_CUSTOM_SETTING", "hello")
    assert ok, f"Non-strict should allow unknown keys, got: {reason}"


if __name__ == "__main__":
    test_valid_int_key()
    test_int_out_of_range()
    test_deny_key()
    test_deny_pattern()
    test_bool_valid()
    test_bool_invalid()
    test_validate_config_mixed()
    test_unknown_key_non_strict()
    print("All config_validator tests passed")
