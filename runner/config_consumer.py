#!/usr/bin/env python3
"""
config_consumer.py - thread-safe, fail-soft configuration consumption.

Provides module-level functions for reading fleet_config values with:
- Thread-safe singleton pattern with explicit locking
- Fail-soft error handling: returns defaults on any error (DB unavailable, missing key, etc)
- Environment variable configuration for tunable params (cache TTL, retry count)
- Type coercion helpers (int, bool, float)
- Cache with configurable TTL for load_config()

All functions are safe to call without initialization and never raise exceptions.
"""

import os
import sys
import time
import threading
from typing import Any, Dict, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


class _ConfigConsumer:
    """Thread-safe singleton for configuration consumption with caching."""

    def __init__(self):
        self._lock = threading.Lock()
        self._cache: Dict[str, tuple] = {}
        self._cache_ttl_sec = float(os.environ.get("ORCH_CONFIG_CACHE_TTL_SEC", "60"))

    def load_all(self) -> Dict[str, str]:
        """Return all ORCH_* prefixed environment variables as a dict (without prefix)."""
        try:
            result = {}
            for key, value in os.environ.items():
                if key.startswith("ORCH_"):
                    result[key[5:]] = str(value)
            return result
        except Exception:
            return {}

    def get(self, key: str, default: str = "") -> str:
        """Get ORCH_{key} from environment, stripping whitespace.

        Returns default if key is None/empty/not found/whitespace-only.
        Never raises — fail-soft by design.
        """
        try:
            if not key or not isinstance(key, str):
                return default
            env_key = f"ORCH_{key}".upper()
            value = os.environ.get(env_key, "").strip()
            return value if value else default
        except Exception:
            return default

    def get_int(self, key: str, default: int = 0) -> int:
        """Get ORCH_{key} as integer with fallback to default."""
        try:
            value = self.get(key, "").strip()
            if not value:
                return default
            return int(value)
        except (ValueError, TypeError):
            return default
        except Exception:
            return default

    def get_bool(self, key: str, default: bool = False) -> bool:
        """Get ORCH_{key} as boolean (true/1/yes/on -> True, else False)."""
        try:
            value = self.get(key, "").strip().lower()
            if not value:
                return default
            return value in ("true", "1", "yes", "on")
        except Exception:
            return default

    def get_float(self, key: str, default: float = 0.0) -> float:
        """Get ORCH_{key} as float with fallback to default."""
        try:
            value = self.get(key, "").strip()
            if not value:
                return default
            return float(value)
        except (ValueError, TypeError):
            return default
        except Exception:
            return default

    def load_config(self, key: str, default: str = "") -> str:
        """Load config from fleet_config DB (with cache) or fallback to env.

        Cache TTL is ORCH_CONFIG_CACHE_TTL_SEC (default 60s).
        Returns env value if DB unavailable, then default if not in env.
        Never raises — fail-soft by design.
        """
        try:
            if not key or not isinstance(key, str):
                return default

            # Check cache first
            with self._lock:
                if key in self._cache:
                    cached_value, cached_time = self._cache[key]
                    if time.time() - cached_time < self._cache_ttl_sec:
                        return cached_value

            # Try DB fallback if available
            value = None
            try:
                import db
                rows = db.select("fleet_config", {"select": "value", "key": f"eq.{key}", "limit": "1"}) or []
                if rows:
                    value = str(rows[0].get("value") or "").strip()
            except Exception:
                pass

            # Fall back to environment
            if value is None or not value:
                value = self.get(key, default).strip()
                if not value:
                    value = default

            # Cache and return
            with self._lock:
                self._cache[key] = (value, time.time())
            return value
        except Exception:
            return default

    def invalidate_cache(self) -> None:
        """Clear all cached configuration values."""
        try:
            with self._lock:
                self._cache.clear()
        except Exception:
            pass


_consumer = _ConfigConsumer()


def load_all() -> Dict[str, str]:
    """Return all ORCH_* prefixed environment variables as a dict (without prefix)."""
    return _consumer.load_all()


def get(key: str, default: str = "") -> str:
    """Get ORCH_{key} from environment, stripping whitespace.

    Returns default if key is None/empty/not found/whitespace-only.
    Never raises — fail-soft by design.
    """
    return _consumer.get(key, default)


def get_int(key: str, default: int = 0) -> int:
    """Get ORCH_{key} as integer with fallback to default."""
    return _consumer.get_int(key, default)


def get_bool(key: str, default: bool = False) -> bool:
    """Get ORCH_{key} as boolean (true/1/yes/on -> True, else False)."""
    return _consumer.get_bool(key, default)


def get_float(key: str, default: float = 0.0) -> float:
    """Get ORCH_{key} as float with fallback to default."""
    return _consumer.get_float(key, default)


def load_config(key: str, default: str = "") -> str:
    """Load config from fleet_config DB (with cache) or fallback to env.

    Cache TTL is ORCH_CONFIG_CACHE_TTL_SEC (default 60s).
    Returns env value if DB unavailable, then default if not in env.
    Never raises — fail-soft by design.
    """
    return _consumer.load_config(key, default)


def invalidate_cache() -> None:
    """Clear all cached configuration values."""
    _consumer.invalidate_cache()


if __name__ == "__main__":
    print("config_consumer module loaded successfully")
    print(f"All ORCH_* keys: {load_all()}")
