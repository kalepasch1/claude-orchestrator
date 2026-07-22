#!/usr/bin/env python3
"""realtime_config.py - Cached config accessor for fleet parameters.

Provides thread-safe, TTL-cached access to fleet_config with:
  - Single key get() and batch get_many()
  - Type coercion helpers (get_int, get_float, get_bool)
  - Config validation via config_validator before cache population
  - Staleness detection and stats() for observability
  - Manual invalidate() for tests and operator control
  - Fail-soft: returns defaults on any error, never raises

Env vars:
    CONFIG_CACHE_TTL   seconds between DB refreshes (default 10)
"""
import os, sys, threading, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

_cache = {}
_cache_ts = 0.0
_TTL = float(os.environ.get("CONFIG_CACHE_TTL", "10"))
_lock = threading.Lock()
_refresh_count = 0
_refresh_errors = 0
_last_error = ""


def get(key, default=None):
    """Get a config value by key. Returns default if missing or on error."""
    global _cache, _cache_ts
    if time.time() - _cache_ts > _TTL:
        _refresh()
    return _cache.get(key, default)


def get_int(key, default=0):
    """Get a config value coerced to int. Returns default on missing/bad value."""
    val = get(key)
    if val is None:
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def get_float(key, default=0.0):
    """Get a config value coerced to float. Returns default on missing/bad value."""
    val = get(key)
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def get_bool(key, default=False):
    """Get a config value coerced to bool. Returns default on missing/bad value."""
    val = get(key)
    if val is None:
        return default
    if isinstance(val, str):
        return val.lower() in ("1", "true", "yes", "on")
    return bool(val)


def get_many(keys, defaults=None):
    """Get multiple config values at once. Returns dict keyed by requested keys.
    defaults is an optional dict of fallback values."""
    global _cache, _cache_ts
    if time.time() - _cache_ts > _TTL:
        _refresh()
    defaults = defaults or {}
    return {k: _cache.get(k, defaults.get(k)) for k in keys}


def invalidate():
    """Force cache invalidation. Next get() will refresh from DB.
    Useful for tests and operator control."""
    global _cache_ts
    with _lock:
        _cache_ts = 0.0


def stats():
    """Return cache observability stats."""
    with _lock:
        age = time.time() - _cache_ts if _cache_ts > 0 else -1
        return {
            "cached_keys": len(_cache),
            "cache_age_s": round(age, 1),
            "ttl_s": _TTL,
            "refresh_count": _refresh_count,
            "refresh_errors": _refresh_errors,
            "last_error": _last_error,
            "stale": age > _TTL if age >= 0 else True,
        }


def _refresh():
    """Reload config from fleet_config table. Validates entries via config_validator
    if available. Fail-soft: errors are counted but never raised."""
    global _cache, _cache_ts, _refresh_count, _refresh_errors, _last_error
    with _lock:
        # Double-check under lock (another thread may have refreshed)
        if time.time() - _cache_ts <= _TTL:
            return
        try:
            rows = db.select("fleet_config", {"select": "key,value"}) or []
        except Exception as exc:
            _refresh_errors += 1
            _last_error = str(exc)[:200]
            # Keep stale cache rather than clearing — better stale than empty
            _cache_ts = time.time()
            return

        # Validate entries if config_validator is available
        new_cache = {}
        validator = None
        try:
            import config_validator
            validator = config_validator
        except ImportError:
            pass

        for r in rows:
            k, v = r.get("key", ""), r.get("value", "")
            if not k:
                continue
            if validator:
                ok, reason = validator.validate_key_value(k, str(v))
                if not ok:
                    # Skip invalid entries silently — they stay out of cache
                    continue
            new_cache[k] = v

        _cache = new_cache
        _cache_ts = time.time()
        _refresh_count += 1
