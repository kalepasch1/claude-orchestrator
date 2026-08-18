#!/usr/bin/env python3
"""
config_consumer.py - Centralized fleet-wide configuration consumption.

Reads ORCH_*-prefixed configuration from the fleet_config table (via database),
with fallback to environment variables if the database is unavailable. Implements
the module-level singleton pattern with fail-soft error handling: all reads return
sensible defaults on any error and never raise.

Usage:
    import config_consumer
    timeout = config_consumer.get_int("SESSION_TIMEOUT", default=3600)
    enabled = config_consumer.get_bool("FEATURE_X", default=False)
    value = config_consumer.get_str("CUSTOM_KEY", default="")

Configuration precedence:
    1. fleet_config table (centralized, fleet-wide)
    2. environment variable ORCH_{key} (machine-local)
    3. provided default (fail-soft fallback)
"""
import os, sys, time, threading
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_lock = threading.Lock()
_cache = {}
_last_db_fetch = {"t": 0.0}
CACHE_TTL_S = 30.0  # Reuse cached values for 30 seconds


def _get_db():
    """Lazy import of db module for fail-soft behavior."""
    try:
        import db
        return db
    except Exception:
        return None


def _fetch_from_db(key):
    """Query fleet_config table for a key. Returns value or None on any error."""
    db = _get_db()
    if db is None:
        return None
    try:
        rows = db.select("fleet_config", {"select": "value", "key": f"eq.{key}", "limit": "1"}) or []
        if rows:
            return str(rows[0].get("value") or "").strip() or None
    except Exception:
        pass
    return None


def _get_raw(key):
    """Get raw string value for a config key from cache or DB.

    Checks cache first (if fresh), then DB, then environment variable ORCH_{key},
    finally returns empty string. Never raises.
    """
    if not key or not isinstance(key, str):
        return ""

    try:
        now = time.time()
        with _lock:
            if key in _cache:
                cached_val, cached_at = _cache[key]
                if now - cached_at < CACHE_TTL_S:
                    return cached_val or ""

        # Try DB fetch
        value = _fetch_from_db(key)
        if value is not None:
            with _lock:
                _last_db_fetch["t"] = now
                _cache[key] = (value, now)
            return value

        # Fall back to environment
        value = os.environ.get(f"ORCH_{key.upper()}", "").strip()
        if value:
            with _lock:
                _last_db_fetch["t"] = now
                _cache[key] = (value, now)
            return value

        # Mark as tried but empty
        with _lock:
            _cache[key] = ("", now)
        return ""
    except Exception:
        return os.environ.get(f"ORCH_{key.upper()}", "").strip() or ""


def get_str(key, default=""):
    """Get a string config value. Returns default on missing/invalid keys."""
    if not key:
        return default
    try:
        value = _get_raw(key)
        return value if value else default
    except Exception:
        return default


def get_int(key, default=0):
    """Get an integer config value. Returns default on missing/non-numeric keys."""
    if not key:
        return default
    try:
        value = _get_raw(key)
        if not value:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def get_float(key, default=0.0):
    """Get a float config value. Returns default on missing/non-numeric keys."""
    if not key:
        return default
    try:
        value = _get_raw(key)
        if not value:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def get_bool(key, default=False):
    """Get a boolean config value. True iff value is '1', 'true', 'yes', or 'on' (case-insensitive)."""
    if not key:
        return default
    try:
        value = _get_raw(key)
        if not value:
            return default
        return value.lower() in ("1", "true", "yes", "on")
    except Exception:
        return default


def invalidate(key=None):
    """Clear the config cache. If key is None, clears all entries."""
    with _lock:
        if key is None:
            _cache.clear()
        elif key in _cache:
            del _cache[key]


def stats():
    """Return cache statistics: {cached_keys, oldest_entry_age_s}."""
    with _lock:
        if not _cache:
            return {"cached_keys": 0, "oldest_entry_age_s": 0}
        now = time.time()
        oldest_age = max(now - cached_at for _, (_, cached_at) in _cache.items())
        return {"cached_keys": len(_cache), "oldest_entry_age_s": oldest_age}


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        key = sys.argv[1]
        default = sys.argv[2] if len(sys.argv) > 2 else ""
        print(get_str(key, default))
