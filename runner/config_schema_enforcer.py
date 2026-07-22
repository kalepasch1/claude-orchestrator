#!/usr/bin/env python3
"""
config_schema_enforcer.py - schema enforcement and cross-key constraint
validation for centralized fleet configuration.

Extends config_validator.py with:
  - Declarative schema definitions (type, range, default, description, dependencies)
  - Cross-key constraint rules (e.g., RAM_FLOOR_GB < PER_TASK_GB * MAX_PARALLEL)
  - Config diff validation: check what changed between old and new configs
  - Safe-defaults generator: produce a known-good config from schema

Integrates with fleet_control.py's load_config() to validate before applying.

Fail-soft: all public functions return sensible defaults on internal errors.
Thread-safe.

Env vars:
    ORCH_SCHEMA_ENFORCER_ENABLED   default "true"
    ORCH_SCHEMA_STRICT             default "false"
"""
import os, sys, copy, threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import log as _log_mod
_log = _log_mod.get("config_schema_enforcer")

ENABLED = os.environ.get("ORCH_SCHEMA_ENFORCER_ENABLED", "true").lower() in ("1", "true", "yes")
STRICT = os.environ.get("ORCH_SCHEMA_STRICT", "false").lower() in ("1", "true", "yes")

# ---------- Schema definitions ----------

SCHEMA = {
    "MAX_PARALLEL": {
        "type": "int", "min": 1, "max": 20, "default": 4,
        "description": "Maximum parallel task slots per machine",
    },
    "ORCH_EXTRA_CODERS": {
        "type": "int", "min": 0, "max": 10, "default": 1,
        "description": "Additional coder slots beyond MAX_PARALLEL",
    },
    "PER_TASK_GB": {
        "type": "float", "min": 0.5, "max": 32.0, "default": 2.0,
        "description": "RAM budget per task in GB",
    },
    "RAM_FLOOR_GB": {
        "type": "float", "min": 1.0, "max": 64.0, "default": 4.0,
        "description": "Minimum free RAM before claiming new tasks",
    },
    "TASK_TIMEOUT": {
        "type": "int", "min": 60, "max": 7200, "default": 600,
        "description": "Task execution timeout in seconds",
    },
    "ORCH_AUTO_PULL": {
        "type": "bool", "default": True,
        "description": "Auto git pull on each loop",
    },
    "ORCH_TEST_ORACLE": {
        "type": "bool", "default": True,
        "description": "Enable test oracle for quality gate",
    },
    "ORCH_USE_SUBSCRIPTION": {
        "type": "bool", "default": False,
        "description": "Use subscription-mode API keys",
    },
    "MERGE_BATCH_SIZE": {
        "type": "int", "min": 1, "max": 50, "default": 5,
        "description": "Max branches to merge per cycle",
    },
    "QUEUE_BANKRUPTCY_LIMIT": {
        "type": "int", "min": 10, "max": 1000, "default": 200,
        "description": "Queue size that triggers bankruptcy cleanup",
    },
    "ORCH_FAILSOFT_ENABLED": {
        "type": "bool", "default": True,
        "description": "Enable fail-soft error handling",
    },
    "ORCH_ERROR_TAXONOMY_ENABLED": {
        "type": "bool", "default": True,
        "description": "Enable error taxonomy classification",
    },
}

# Cross-key constraints: each is (description, check_fn)
# check_fn receives the full parsed config dict and returns (ok, reason)
CROSS_KEY_CONSTRAINTS = [
    (
        "RAM_FLOOR_GB must accommodate at least one task",
        lambda cfg: (True, "") if cfg.get("RAM_FLOOR_GB", 4) >= cfg.get("PER_TASK_GB", 2)
        else (False, f"RAM_FLOOR_GB ({cfg.get('RAM_FLOOR_GB')}) < PER_TASK_GB ({cfg.get('PER_TASK_GB')})")
    ),
    (
        "TASK_TIMEOUT must be at least 60s",
        lambda cfg: (True, "") if cfg.get("TASK_TIMEOUT", 600) >= 60
        else (False, f"TASK_TIMEOUT ({cfg.get('TASK_TIMEOUT')}) < 60")
    ),
    (
        "MAX_PARALLEL + ORCH_EXTRA_CODERS should not exceed 25",
        lambda cfg: (True, "") if (cfg.get("MAX_PARALLEL", 4) + cfg.get("ORCH_EXTRA_CODERS", 1)) <= 25
        else (False, f"MAX_PARALLEL + ORCH_EXTRA_CODERS = {cfg.get('MAX_PARALLEL', 4) + cfg.get('ORCH_EXTRA_CODERS', 1)} > 25")
    ),
]

# ---------- Parsing ----------

def _parse_value(raw, spec):
    """Parse a raw string value according to the schema spec. Returns (parsed, error)."""
    t = spec.get("type", "str")
    try:
        if t == "int":
            v = int(raw)
            lo, hi = spec.get("min", float("-inf")), spec.get("max", float("inf"))
            if not (lo <= v <= hi):
                return None, f"value {v} out of range [{lo}, {hi}]"
            return v, None
        elif t == "float":
            v = float(raw)
            lo, hi = spec.get("min", float("-inf")), spec.get("max", float("inf"))
            if not (lo <= v <= hi):
                return None, f"value {v} out of range [{lo}, {hi}]"
            return v, None
        elif t == "bool":
            s = str(raw).lower()
            if s in ("true", "1", "yes", "on"):
                return True, None
            elif s in ("false", "0", "no", "off"):
                return False, None
            else:
                return None, f"invalid boolean: '{raw}'"
        else:
            return str(raw), None
    except (ValueError, TypeError) as e:
        return None, f"parse error: {e}"


# ---------- Public API ----------

def validate_config(config_dict):
    """Validate a full config dict against the schema and cross-key constraints.

    Returns:
        {
            "valid": bool,
            "errors": [{"key": str, "error": str}],
            "warnings": [{"key": str, "warning": str}],
            "parsed": {key: parsed_value},  # only valid keys
        }
    """
    try:
        if not ENABLED:
            return {"valid": True, "errors": [], "warnings": [], "parsed": {}}

        errors = []
        warnings = []
        parsed = {}

        for key, raw_value in (config_dict or {}).items():
            spec = SCHEMA.get(key)
            if spec is None:
                if STRICT:
                    errors.append({"key": key, "error": f"unknown key '{key}' in strict mode"})
                else:
                    warnings.append({"key": key, "warning": f"unknown key '{key}', not in schema"})
                continue

            value, err = _parse_value(raw_value, spec)
            if err:
                errors.append({"key": key, "error": err})
            else:
                parsed[key] = value

        # Cross-key constraints (only if we have enough parsed values)
        if parsed:
            # Merge defaults for missing keys so constraints can evaluate
            full = defaults()
            full.update(parsed)
            for desc, check_fn in CROSS_KEY_CONSTRAINTS:
                try:
                    ok, reason = check_fn(full)
                    if not ok:
                        errors.append({"key": "(cross-key)", "error": f"{desc}: {reason}"})
                except Exception as e:
                    warnings.append({"key": "(cross-key)", "warning": f"constraint check failed: {e}"})

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "parsed": parsed,
        }

    except Exception as e:
        _log.warning("config validation failed internally: %s", e)
        return {"valid": True, "errors": [], "warnings": [], "parsed": {}}


def validate_diff(old_config, new_config):
    """Validate only the changed keys between old and new configs.

    Returns the same structure as validate_config, plus a "changes" list.
    """
    try:
        changes = []
        diff = {}
        for key, new_val in (new_config or {}).items():
            old_val = (old_config or {}).get(key)
            if old_val != new_val:
                changes.append({"key": key, "old": old_val, "new": new_val})
                diff[key] = new_val

        result = validate_config(diff)
        result["changes"] = changes
        return result

    except Exception:
        return {"valid": True, "errors": [], "warnings": [], "parsed": {}, "changes": []}


def defaults():
    """Return a dict of all default values from the schema."""
    try:
        return {k: spec["default"] for k, spec in SCHEMA.items() if "default" in spec}
    except Exception:
        return {}


def schema_info(key=None):
    """Return schema info for a key, or all keys if key is None."""
    try:
        if key:
            return SCHEMA.get(key)
        return copy.deepcopy(SCHEMA)
    except Exception:
        return {} if key is None else None
