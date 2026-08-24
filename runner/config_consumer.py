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

# Optional at module level so callers and tests have a seam to patch, and so a
# missing or broken gateway degrades to env-only config instead of an import error.
try:
    import fleet_control
except Exception:
    fleet_control = None


DEFAULT_CACHE_TTL_SEC = 60.0
DEFAULT_CACHE_MAX_ENTRIES = 1000


def _env_number(name: str, default: float, cast=float, minimum=None):
    """Read a numeric ORCH_ knob. Never raises; a bad value logs and falls back.

    This module is imported by most of the runner, so a malformed value must not be
    able to raise. It previously did: the TTL was cast with a bare float() inside
    __init__, which runs at import time via the module-level singleton, so
    ORCH_CONFIG_CACHE_TTL_SEC=abc raised ValueError and took down every importer of
    the configuration layer — the one module whose whole contract is "never raises".
    """
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        value = cast(str(raw).strip())
        if minimum is not None and value < minimum:
            raise ValueError(f"must be >= {minimum}, got {value}")
        return value
    except Exception as exc:
        print(f"[config_consumer] {name} unusable ({exc}); using default {default}", flush=True)
        return default


def env_str(name: str, default: str = "") -> str:
    """Read an environment variable by its FULL name, fail-soft.

    The get/get_int/... family reads ORCH_-prefixed keys. These four read the literal
    name instead, because ~1000 module-scope constants across runner/ are spelled
    `int(os.environ.get("ORCH_X", "8"))` — a bare cast that runs at *import* time.
    A single malformed fleet push of any one of those keys raises ValueError while the
    module is being imported, which takes down every importer, not just the caller of
    that constant. That is the exact failure this configuration layer exists to prevent,
    and it cannot be fixed by the ORCH_-prefixed getters because the call sites are not
    prefixed uniformly and are evaluated before any consumer object exists.

    Use these at module scope: `MAX = config_consumer.env_int("ORCH_MAX", 8)`.
    Never raises.
    """
    try:
        if not name or not isinstance(name, str):
            return default
        value = os.environ.get(name, "")
        value = value.strip() if isinstance(value, str) else ""
        return value if value else default
    except Exception:
        return default


def env_int(name: str, default: int = 0, minimum: Optional[int] = None) -> int:
    """Integer env knob. Returns ``default`` on anything unparseable or below minimum."""
    raw = env_str(name, "")
    if not raw:
        return default
    try:
        value = int(raw)
    except (ValueError, TypeError):
        print(f"[config_consumer] {name}={raw!r} is not an int; using {default}", flush=True)
        return default
    except Exception:
        return default
    if minimum is not None and value < minimum:
        print(f"[config_consumer] {name}={value} below minimum {minimum}; using {default}",
              flush=True)
        return default
    return value


def env_float(name: str, default: float = 0.0, minimum: Optional[float] = None) -> float:
    """Float env knob. Returns ``default`` on anything unparseable or below minimum."""
    raw = env_str(name, "")
    if not raw:
        return default
    try:
        value = float(raw)
    except (ValueError, TypeError):
        print(f"[config_consumer] {name}={raw!r} is not a float; using {default}", flush=True)
        return default
    except Exception:
        return default
    if minimum is not None and value < minimum:
        print(f"[config_consumer] {name}={value} below minimum {minimum}; using {default}",
              flush=True)
        return default
    return value


def env_bool(name: str, default: bool = False) -> bool:
    """Boolean env knob.

    Unlike get_bool, an unrecognised word returns ``default`` rather than False —
    at module scope a knob is often a kill switch, and silently flipping a
    default-on switch off because someone typed "maybe" is worse than ignoring them.
    """
    raw = env_str(name, "").lower()
    if not raw:
        return default
    if raw in ("true", "1", "yes", "on"):
        return True
    if raw in ("false", "0", "no", "off"):
        return False
    print(f"[config_consumer] {name}={raw!r} is not a bool; using {default}", flush=True)
    return default


class _ConfigConsumer:
    """Thread-safe singleton for configuration consumption with caching."""

    def __init__(self):
        self._lock = threading.Lock()
        self._cache: Dict[str, tuple] = {}

    @property
    def _cache_ttl_sec(self) -> float:
        """Re-read on every use so a fleet-pushed TTL takes effect without a restart.

        Reading it once in __init__ meant the value was frozen at process start; a
        fleet_config push of ORCH_CONFIG_CACHE_TTL_SEC changed nothing until every
        runner was restarted, which is the failure mode this config layer exists to
        prevent for everyone else.
        """
        return _env_number("ORCH_CONFIG_CACHE_TTL_SEC", DEFAULT_CACHE_TTL_SEC,
                           float, minimum=0.0)

    @property
    def _cache_max_entries(self) -> int:
        return int(_env_number("ORCH_CONFIG_CACHE_MAX_ENTRIES",
                               DEFAULT_CACHE_MAX_ENTRIES, int, minimum=1))

    def _evict_locked(self) -> None:
        """Bound the cache. Caller must hold the lock.

        load_config() keys the cache on caller-supplied strings, so an unbounded dict
        is a slow leak in a process that runs for weeks. Oldest entries go first.
        """
        limit = self._cache_max_entries
        if len(self._cache) <= limit:
            return
        for key in sorted(self._cache, key=lambda k: self._cache[k][1])[:len(self._cache) - limit]:
            self._cache.pop(key, None)

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
            env_key = f"ORCH_{key}"
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

            # Read through the fleet_control gateway. CLAUDE.md is explicit that
            # fleet-wide config goes through that in-process gateway rather than
            # ad-hoc table reads; this used to call db.select("fleet_config", ...)
            # directly, which bypassed the gateway's own guards and left callers
            # (and tests) with no seam to patch.
            value = None
            if fleet_control is not None:
                try:
                    got = fleet_control.get_fleet_config(key, "")
                    if got:
                        value = str(got).strip()
                except Exception:
                    value = None

            if not value:  # gateway absent or empty -> direct read as a last resort
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
                self._evict_locked()
            return value
        except Exception:
            return default

    def invalidate_cache(self, key: Optional[str] = None) -> None:
        """Clear cached configuration. One key when given, otherwise everything.

        Per-key invalidation lets a caller that just pushed one value re-read it
        immediately without throwing away every other cached key.
        """
        try:
            with self._lock:
                if key:
                    self._cache.pop(key, None)
                else:
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


def invalidate_cache(key: Optional[str] = None) -> None:
    """Clear cached configuration values — one key when given, otherwise all."""
    _consumer.invalidate_cache(key)


if __name__ == "__main__":
    print("config_consumer module loaded successfully")
    print(f"All ORCH_* keys: {load_all()}")
