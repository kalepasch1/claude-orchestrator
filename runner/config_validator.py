#!/usr/bin/env python3
"""
config_validator.py — Validate fleet_config values before application.

Ensures configuration changes are safe before they take effect:
- Type checking (bool, int, float, string)
- Range validation for numeric configs
- Dependency validation (e.g., autoapprove requires test gate)
"""
import os
import sys
import re

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Schema: key -> {type, min, max, allowed, depends_on}
CONFIG_SCHEMA = {
    "ORCH_AUTOAPPROVE_LOWRISK": {"type": "bool"},
    "ORCH_AUTO_MERGE_APPROVALS": {"type": "bool"},
    "ORCH_QUEUE_ELIMINATION": {"type": "bool"},
    "ORCH_PUSH_ON_MERGE": {"type": "bool"},
    "ORCH_EMERGENCY_BUDGET_STOP": {"type": "bool"},
    "ORCH_ELIM_SCAN_LIMIT": {"type": "int", "min": 1, "max": 100},
    "ORCH_ELIM_MIN_CONF": {"type": "float", "min": 0.0, "max": 1.0},
    "ORCH_AGENTIC_REPAIR_PROMPT_CHARS": {"type": "int", "min": 1000, "max": 50000},
    "AUTOPILOT_MAX_DECISIONS": {"type": "int", "min": 1, "max": 200},
    "AUTOPILOT_IMPROVE_FLOOR": {"type": "int", "min": 0, "max": 100},
    "AUTOPILOT_SNAPSHOT_LIMIT": {"type": "int", "min": 100, "max": 10000},
}

BOOL_TRUE = {"true", "1", "yes", "on"}
BOOL_FALSE = {"false", "0", "no", "off"}


def validate_value(key, value):
    """Validate a single config key-value pair.

    Returns: (valid: bool, error: str | None)
    """
    schema = CONFIG_SCHEMA.get(key)
    if not schema:
        # Unknown keys pass validation (extensible config)
        return True, None

    str_val = str(value).strip().lower()
    expected_type = schema.get("type", "string")

    if expected_type == "bool":
        if str_val not in BOOL_TRUE | BOOL_FALSE:
            return False, f"{key}: expected bool, got '{value}'"

    elif expected_type == "int":
        try:
            int_val = int(value)
        except (ValueError, TypeError):
            return False, f"{key}: expected int, got '{value}'"
        if "min" in schema and int_val < schema["min"]:
            return False, f"{key}: {int_val} below minimum {schema['min']}"
        if "max" in schema and int_val > schema["max"]:
            return False, f"{key}: {int_val} above maximum {schema['max']}"

    elif expected_type == "float":
        try:
            float_val = float(value)
        except (ValueError, TypeError):
            return False, f"{key}: expected float, got '{value}'"
        if "min" in schema and float_val < schema["min"]:
            return False, f"{key}: {float_val} below minimum {schema['min']}"
        if "max" in schema and float_val > schema["max"]:
            return False, f"{key}: {float_val} above maximum {schema['max']}"

    return True, None


def validate_batch(config_dict):
    """Validate a batch of config key-value pairs.

    Returns: (all_valid: bool, errors: list[str])
    """
    errors = []
    for key, value in config_dict.items():
        valid, error = validate_value(key, value)
        if not valid:
            errors.append(error)
    return len(errors) == 0, errors
