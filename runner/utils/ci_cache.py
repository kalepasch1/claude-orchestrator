"""
ci_cache.py — Dependency caching for CI pipeline optimization.
Env gate: ORCH_CI_CACHE_ENABLED (default OFF).
"""
import os

ENABLED = os.environ.get("ORCH_CI_CACHE_ENABLED", "").lower() == "true"

def get_cache_key(deps_file: str) -> str:
    """Generate a cache key from a dependency lockfile path."""
    if not ENABLED or not deps_file:
        return ""
    import hashlib
    try:
        with open(deps_file, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()[:16]
    except (FileNotFoundError, PermissionError):
        return ""

def should_use_cache(key: str, cache_dir: str = "/tmp/ci_cache") -> bool:
    """Check if a valid cache exists for the given key."""
    if not ENABLED or not key:
        return False
    return os.path.isdir(os.path.join(cache_dir, key))
