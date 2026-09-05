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


class _Absent:
    """Cache sentinel: no configuration source defines this key.

    A distinct object rather than None or "", both of which a source could legitimately
    produce, and which is what let a caller's default get cached as if it were a value.
    """

    __slots__ = ()

    def __repr__(self):  # pragma: no cover - debugging aid
        return "<config_consumer.ABSENT>"

    def __bool__(self):
        return False


_ABSENT = _Absent()


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

    def _env_lookup(self, key: str) -> str:
        """Resolve ORCH_{key} from the environment, upper-case first.

        Recovered defect (orch-config-consumption, 2026-08-24): this consumer
        read `f"ORCH_{key}"` verbatim while fleet_control.get_fleet_config reads
        `f"ORCH_{key}".upper()`. Environment variables are conventionally
        upper-case and fleet_control writes them that way, so any caller passing
        a lower- or mixed-case key silently got the DEFAULT here while the very
        same key resolved correctly through fleet_control — a fleet-wide config
        push would appear to apply on one path and be ignored on the other.

        Upper-case is tried first so the two paths agree; the verbatim key is
        kept as a fallback so an existing exactly-cased ORCH_ variable that is
        NOT upper-case keeps working. Fail-soft: never raises.
        """
        try:
            if not key or not isinstance(key, str):
                return ""
            for env_key in (f"ORCH_{key}".upper(), f"ORCH_{key}"):
                value = os.environ.get(env_key, "").strip()
                if value:
                    return value
            return ""
        except Exception:
            return ""

    def get(self, key: str, default: str = "") -> str:
        """Get ORCH_{key} from environment, stripping whitespace.

        Case-insensitive on the key (see _env_lookup) so this agrees with
        fleet_control.get_fleet_config. Returns default if key is
        None/empty/not found/whitespace-only. Never raises — fail-soft by design.
        """
        try:
            if not key or not isinstance(key, str):
                return default
            value = self._env_lookup(key)
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

            # Check cache first.
            #
            # A cache entry records what the SOURCES said, never what a caller passed as
            # its default. The cache is keyed by key alone, so caching the resolved
            # default meant the first caller's default leaked to every later one:
            #
            #     load_config("MAX_RETRIES", "3")   -> "3"   (absent everywhere)
            #     load_config("MAX_RETRIES", "10")  -> "3"   <-- someone else's default
            #
            # Silent, and near-impossible to trace from the call site. _ABSENT keeps the
            # negative caching (a missing key still costs one DB read per TTL) while
            # letting each caller apply its own default at return time.
            with self._lock:
                if key in self._cache:
                    cached_value, cached_time = self._cache[key]
                    if time.time() - cached_time < self._cache_ttl_sec:
                        return default if cached_value is _ABSENT else cached_value

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

            # Fall back to environment. `get(key, "")` rather than `get(key, default)`
            # so an absent env var is distinguishable from one that happens to hold the
            # caller's default — the cache needs to know which of those it saw.
            if not value:
                value = self.get(key, "").strip()

            # Cache what the sources said. _ABSENT records "no source has this key",
            # which is worth caching (it saves the DB read) but must never be confused
            # with a real value.
            with self._lock:
                self._cache[key] = (value if value else _ABSENT, time.time())
                self._evict_locked()
            return value if value else default
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
