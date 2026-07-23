#!/usr/bin/env python3
"""
vercel_checks_cache.py — Cache Vercel deployment status checks to avoid repeated API calls.

Instead of 100 tasks individually polling Vercel API for the same deployment status,
this module runs a single Vercel check per project/branch (e.g., deployment ready,
build succeeded) and caches the result. The cache is checked before expensive API calls,
avoiding redundant verification.

This is similar to toolchain_gate.py but focused on Vercel deployment/build status.

Environment variables:
  ORCH_VERCEL_CHECKS_CACHE_FILE: path to cache JSON (default: ~/.claude-orchestrator/vercel_checks_cache.json)
  ORCH_VERCEL_CHECK_INTERVAL: seconds between re-checks per project/branch (default: 300, 5 min)
  ORCH_DISABLE_VERCEL_CHECKS_CACHE: set to 1 to bypass cache entirely (always re-check)
  VERCEL_TOKEN: API token for Vercel API calls
"""
import json
import os
import sys
import time
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

HOME = os.environ.get("CLAUDE_ORCH_HOME", os.path.expanduser("~/.claude-orchestrator"))
CACHE_FILE = os.environ.get("ORCH_VERCEL_CHECKS_CACHE_FILE", os.path.join(HOME, "vercel_checks_cache.json"))
CHECK_INTERVAL = int(os.environ.get("ORCH_VERCEL_CHECK_INTERVAL", "300"))

_lock = threading.Lock()
_cache = None


def _load_cache():
    """Load cache from disk. Returns {} on error (fail-soft)."""
    try:
        if os.path.isfile(CACHE_FILE):
            with open(CACHE_FILE, encoding="utf-8", errors="replace") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
    except Exception:
        pass
    return {}


def _save_cache(cache):
    """Save cache to disk. Swallows errors (fail-soft)."""
    try:
        os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2)
    except Exception:
        pass


def _get_cache_key(project_id, branch):
    """Generate a cache key for a project/branch combo."""
    return f"{project_id}:{branch or 'main'}"


def is_cached_fresh(project_id, branch):
    """Check if a cached result exists and is fresh (within CHECK_INTERVAL).

    Returns (is_fresh: bool, cached_value: dict|None)
    Fails OPEN: if any error, returns (False, None) so caller falls back to real check.
    """
    if os.environ.get("ORCH_DISABLE_VERCEL_CHECKS_CACHE", "").lower() in ("1", "true", "yes"):
        return False, None

    try:
        with _lock:
            cache = _load_cache()
        key = _get_cache_key(project_id, branch)
        entry = cache.get(key)
        if not entry:
            return False, None

        age = time.time() - entry.get("checked_at", 0)
        if age < CHECK_INTERVAL:
            return True, entry.get("data")
        return False, entry.get("data")
    except Exception:
        return False, None


def cache_result(project_id, branch, check_name, result, ttl_seconds=None):
    """Store a check result in the cache.

    Args:
      project_id: Vercel project ID or name
      branch: git branch name
      check_name: human-readable check name (e.g., "deployment_ready", "build_succeeded")
      result: dict with check result (e.g., {"ok": true, "status": "READY", "url": "..."})
      ttl_seconds: custom TTL (default: CHECK_INTERVAL)
    """
    if os.environ.get("ORCH_DISABLE_VERCEL_CHECKS_CACHE", "").lower() in ("1", "true", "yes"):
        return

    ttl = ttl_seconds if ttl_seconds is not None else CHECK_INTERVAL
    try:
        with _lock:
            cache = _load_cache()
            key = _get_cache_key(project_id, branch)
            cache[key] = {
                "checked_at": time.time(),
                "data": result,
                "check": check_name,
                "ttl": ttl
            }
            _save_cache(cache)
    except Exception:
        pass


def invalidate(project_id, branch=None):
    """Invalidate cache entry for a project (all branches if branch is None)."""
    if os.environ.get("ORCH_DISABLE_VERCEL_CHECKS_CACHE", "").lower() in ("1", "true", "yes"):
        return

    try:
        with _lock:
            cache = _load_cache()
            if branch:
                key = _get_cache_key(project_id, branch)
                if key in cache:
                    del cache[key]
            else:
                # Remove all entries for this project
                prefix = f"{project_id}:"
                cache = {k: v for k, v in cache.items() if not k.startswith(prefix)}
            _save_cache(cache)
    except Exception:
        pass


def invalidate_all():
    """Clear the entire cache."""
    try:
        with _lock:
            _save_cache({})
    except Exception:
        pass


def stats():
    """Return cache statistics for monitoring/debugging."""
    try:
        with _lock:
            cache = _load_cache()
        file_size = os.path.getsize(CACHE_FILE) if os.path.isfile(CACHE_FILE) else 0
        if not cache:
            return {"entries": 0, "stale": 0, "fresh": 0, "file_size": file_size, "cache_file": CACHE_FILE, "check_interval_s": CHECK_INTERVAL}

        now = time.time()
        stale = sum(1 for e in cache.values() if now - e.get("checked_at", 0) >= CHECK_INTERVAL)
        return {
            "entries": len(cache),
            "stale": stale,
            "fresh": len(cache) - stale,
            "file_size": file_size,
            "cache_file": CACHE_FILE,
            "check_interval_s": CHECK_INTERVAL
        }
    except Exception:
        return {"error": "could not read cache", "cache_file": CACHE_FILE}


if __name__ == "__main__":
    # CLI for testing/diagnostics
    import sys
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "stats":
            import json
            print(json.dumps(stats(), indent=2))
        elif cmd == "invalidate-all":
            invalidate_all()
            print("Cache invalidated")
        elif cmd == "show":
            cache = _load_cache()
            print(json.dumps(cache, indent=2, default=str))
    else:
        print("Usage: vercel_checks_cache.py [stats|invalidate-all|show]")
