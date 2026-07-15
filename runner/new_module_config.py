#!/usr/bin/env python3
"""
new_module_config.py - Portable module configuration management.

Provides centralized, thread-safe access to module-level configuration via environment variables.
Supports fleet-wide config updates (ORCH_* prefixed keys), defensive defaults on errors,
and TTL-based caching with manual invalidation.

All tunable parameters are environment variables with sensible defaults, never hardcoded.
Fail-soft: returns empty string or defaults on any error; never raises on missing env/file.
"""
import os, sys, time, threading, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Thread-safe singleton pattern
_lock = threading.Lock()
_cache = {}
_cache_ts = 0.0

HOME = os.environ.get("CLAUDE_ORCH_HOME", os.path.expanduser("~/.claude-orchestrator"))
os.makedirs(HOME, exist_ok=True)

# Configuration TTL and limits (all from environment with sensible defaults)
CONFIG_CACHE_TTL = float(os.environ.get("CONFIG_CACHE_TTL", "10"))  # seconds
CONFIG_MAX_KEYS = int(os.environ.get("CONFIG_MAX_KEYS", "1000"))
CONFIG_FILE_MAX_BYTES = int(os.environ.get("CONFIG_FILE_MAX_BYTES", "1048576"))  # 1MB


def _config_file_path():
    """Return the persistent config file path."""
    return os.path.join(HOME, "module_config.json")


def _load_from_file():
    """Load config from persistent file. Returns {} on any error (fail-soft)."""
    try:
        path = _config_file_path()
        if not os.path.exists(path):
            return {}
        size = os.path.getsize(path)
        if size > CONFIG_FILE_MAX_BYTES:
            return {}  # file too large, ignore
        with open(path, encoding="utf-8", errors="replace") as f:
            data = json.load(f) or {}
        return {k: v for k, v in data.items() if isinstance(k, str)}
    except (FileNotFoundError, json.JSONDecodeError, OSError, PermissionError):
        return {}
    except Exception:
        return ""


def _save_to_file(config):
    """Save config to persistent file. Silent fail-soft on any error."""
    try:
        if not isinstance(config, dict):
            return
        path = _config_file_path()
        tmp = path + ".tmp"
        data = json.dumps(config)
        if len(data) > CONFIG_FILE_MAX_BYTES:
            return  # don't write if too large
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(data)
        os.replace(tmp, path)
    except Exception:
        pass


def _refresh():
    """Refresh cache from file and environment. Called with lock held."""
    global _cache, _cache_ts
    cached_data = _load_from_file() or {}
    if not isinstance(cached_data, dict):
        cached_data = {}
    _cache = cached_data
    _cache_ts = time.time()


def get(key, default=""):
    """Get config value. Returns default (or empty string) if not found. Never raises."""
    if not isinstance(key, str):
        return default if default != "" else ""

    with _lock:
        # Refresh cache if stale
        if time.time() - _cache_ts > CONFIG_CACHE_TTL:
            _refresh()

        value = _cache.get(key)
        if value is None:
            # Fall back to environment variable (ORCH_ prefixed)
            env_key = f"ORCH_{key}" if not key.startswith("ORCH_") else key
            value = os.environ.get(env_key)

        return value if value is not None else default


def set(key, value):
    """Set config value. Returns True on success, False on failure (fail-soft)."""
    if not isinstance(key, str) or not isinstance(value, str):
        return False

    try:
        with _lock:
            if len(_cache) >= CONFIG_MAX_KEYS and key not in _cache:
                return False  # at capacity
            _cache[key] = value
            _save_to_file(_cache)
        return True
    except Exception:
        return False


def delete(key):
    """Delete config value. Returns True on success, False otherwise (fail-soft)."""
    if not isinstance(key, str):
        return False

    try:
        with _lock:
            if key in _cache:
                del _cache[key]
                _save_to_file(_cache)
            return True
    except Exception:
        return False


def get_env_var(env_key, default=""):
    """Get environment variable with fallback. Returns empty string on error (fail-soft)."""
    if not isinstance(env_key, str):
        return default if default != "" else ""
    try:
        return os.environ.get(env_key, default)
    except Exception:
        return default if default != "" else ""


def stats():
    """Return cache statistics (diagnostic info)."""
    try:
        with _lock:
            age = time.time() - _cache_ts
            return {
                "cache_size": len(_cache),
                "cache_age_seconds": round(age, 2),
                "is_stale": age > CONFIG_CACHE_TTL,
                "file_path": _config_file_path(),
                "file_exists": os.path.exists(_config_file_path()),
            }
    except Exception:
        return {"error": "stats_unavailable"}


def invalidate():
    """Manually invalidate cache (force refresh on next access)."""
    global _cache_ts
    try:
        with _lock:
            _cache_ts = 0.0
        return True
    except Exception:
        return False


def clear():
    """Clear all in-memory cache and persistent file (debugging). Returns True on success."""
    try:
        with _lock:
            global _cache
            _cache = {}
            _cache_ts = 0.0
            path = _config_file_path()
            if os.path.exists(path):
                os.remove(path)
        return True
    except Exception:
        return False


# Module initialization: load config on import
_refresh()
