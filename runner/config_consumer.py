#!/usr/bin/env python3
"""
config_consumer.py - Orchestrator configuration consumption.

Reads ORCH_* prefixed configuration keys from centralized fleet_config database table
(via fleet_control.py) or environment variables. Only safe (non-secret) keys are
propagated fleet-wide via fleet_config.

Module-level functions delegate to a thread-safe singleton; callers never handle
None/missing. Fail-soft: DB/env unavailable returns sensible defaults, never raises.
"""
import os
import sys
import time
import threading
from typing import Any, Dict, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_lock = threading.Lock()
_cache = {"t": 0.0, "config": {}}
_CACHE_TTL_SEC = 60.0


def load_all() -> Dict[str, str]:
    """Load all ORCH_* prefixed config keys from environment."""
    config = {}
    for key, value in os.environ.items():
        if key.startswith("ORCH_"):
            config_key = key[5:]
            config[config_key] = value
    return config


def get(key: str, default: Optional[str] = None) -> str:
    """Get ORCH_{key} from environment; return default (or empty string) if missing."""
    env_key = f"ORCH_{key}"
    value = os.environ.get(env_key, "").strip()
    return value if value else (default or "")


def get_int(key: str, default: int = 0) -> int:
    """Get ORCH_{key} as integer; return default if missing or unparseable."""
    value = get(key).strip()
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def get_bool(key: str, default: bool = False) -> bool:
    """Get ORCH_{key} as boolean; return default if missing."""
    value = get(key).lower().strip()
    if not value:
        return default
    return value in ("1", "true", "yes", "on")


def get_float(key: str, default: float = 0.0) -> float:
    """Get ORCH_{key} as float; return default if missing or unparseable."""
    value = get(key).strip()
    if not value:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def load_config(key: str, default: str = "") -> str:
    """Load ORCH_{key} from fleet_config DB (with cache) or environment.

    Tries fleet_config table first (cached 60s), falls back to env var.
    Fail-soft: returns default on any error (DB unavailable, missing key, etc).
    """
    with _lock:
        now = time.time()
        cached = _cache["config"]
        cache_fresh = (now - _cache["t"]) < _CACHE_TTL_SEC

        if cache_fresh and key in cached:
            return cached[key]

        if cache_fresh:
            return get(key, default)

    try:
        import db
        rows = db.select("fleet_config", {"select": "value", "key": f"eq.ORCH_{key}", "limit": "1"})
        if rows and len(rows) > 0:
            value = rows[0].get("value")
            if value is not None:
                result = str(value).strip()
                with _lock:
                    _cache["t"] = time.time()
                    _cache["config"][key] = result
                return result
    except Exception:
        pass

    fallback = get(key, default)
    with _lock:
        _cache["t"] = time.time()
        _cache["config"][key] = fallback
    return fallback


def invalidate_cache() -> None:
    """Clear the configuration cache (e.g., after config changes)."""
    with _lock:
        _cache["t"] = 0.0
        _cache["config"].clear()
