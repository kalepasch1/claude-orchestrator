#!/usr/bin/env python3
"""Thread-safe singleton cache for merged diff metadata with disk persistence and LRU eviction.

Caches merged diff metadata (hash, timestamp, affected files, diff stats) to enable incremental
task recovery and avoid redundant diff processing. Integrates with resource_governor for memory
gating and provides fail-soft error handling on all I/O operations.

Module-level API: acquire() -> DiffMemory singleton instance.
Public functions delegate to singleton: store_diff(), get_diff(), invalidate(), stats().
"""
from __future__ import annotations

import os
import sys
import json
import time
import hashlib
import threading
from pathlib import Path
from typing import Optional, Any
from collections import OrderedDict

try:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "runner"))
    import resource_governor
except ImportError:
    resource_governor = None


class DiffMemory:
    """Thread-safe LRU cache for merged diff metadata with disk persistence."""

    def __init__(self, cache_dir: Optional[str] = None, max_memory_mb: int = 256,
                 ttl_seconds: int = 86400):
        """Initialize the diff cache.

        Args:
            cache_dir: Directory to persist cache. Defaults to ~/.cache/claude-orchestrator/diff-memory
            max_memory_mb: Maximum memory for cache (default 256MB). Set via ORCH_DIFF_MEMORY_LIMIT env var.
            ttl_seconds: Time-to-live for cached entries (default 1 day). Set via ORCH_DIFF_MEMORY_TTL env var.
        """
        self._lock = threading.Lock()

        # Environment overrides
        max_memory_mb = int(os.environ.get("ORCH_DIFF_MEMORY_LIMIT", max_memory_mb))
        ttl_seconds = int(os.environ.get("ORCH_DIFF_MEMORY_TTL", ttl_seconds))

        if cache_dir is None:
            home = Path.home()
            cache_dir = home / ".cache" / "claude-orchestrator" / "diff-memory"
        self._cache_dir = Path(cache_dir)

        self._max_memory_bytes = max_memory_mb * 1024 * 1024
        self._ttl_seconds = ttl_seconds

        # LRU cache: hash -> {metadata, timestamp, size_bytes}
        self._memory_cache: OrderedDict[str, dict] = OrderedDict()
        self._memory_used_bytes = 0

        # Stats
        self._hits = 0
        self._misses = 0
        self._evictions = 0

    def store_diff(self, diff_hash: str, metadata: dict) -> bool:
        """Cache a merged diff metadata entry.

        Args:
            diff_hash: SHA-256 or other unique hash of the diff
            metadata: Dict with keys: files (list), stats (dict), timestamp (float), etc.

        Returns:
            True if stored successfully, False on error or resource exhaustion.
            Fails soft: returns False rather than raising on I/O errors.
        """
        if not diff_hash or not metadata:
            return False

        try:
            with self._lock:
                # Gate on resource availability
                if resource_governor:
                    ok, _ = resource_governor.can_claim()
                    if not ok:
                        return False

                # Estimate size (rough: JSON serialization + overhead)
                entry_bytes = len(json.dumps(metadata)) + 256
                if entry_bytes > self._max_memory_bytes:
                    return False

                # Evict LRU entries if needed
                while (self._memory_used_bytes + entry_bytes > self._max_memory_bytes and
                       self._memory_cache):
                    _, evicted = self._memory_cache.popitem(last=False)
                    self._memory_used_bytes -= evicted.get("_size_bytes", 0)
                    self._evictions += 1

                # Store in memory cache
                entry = {
                    **metadata,
                    "_hash": diff_hash,
                    "_timestamp": time.time(),
                    "_size_bytes": entry_bytes,
                }
                self._memory_cache[diff_hash] = entry
                self._memory_used_bytes += entry_bytes

                # Move to end (most recently used)
                self._memory_cache.move_to_end(diff_hash)

            # Persist to disk (outside lock to avoid blocking)
            self._persist_to_disk(diff_hash, entry)
            return True

        except Exception:
            return False

    def get_diff(self, diff_hash: str) -> dict | None:
        """Retrieve cached diff metadata by hash.

        Returns dict on hit, None on miss or error. Fails soft: never raises.
        """
        if not diff_hash:
            return None

        try:
            with self._lock:
                entry = self._memory_cache.get(diff_hash)

                if entry:
                    # Check staleness
                    age = time.time() - entry.get("_timestamp", 0)
                    if age > self._ttl_seconds:
                        # Evict stale entry
                        del self._memory_cache[diff_hash]
                        self._memory_used_bytes -= entry.get("_size_bytes", 0)
                        self._misses += 1
                        return None

                    # Mark as recently used
                    self._memory_cache.move_to_end(diff_hash)
                    self._hits += 1

                    # Remove internal metadata before returning
                    return {k: v for k, v in entry.items() if not k.startswith("_")}

                self._misses += 1

            # Try disk cache if not in memory
            return self._load_from_disk(diff_hash)

        except Exception:
            return None

    def invalidate(self) -> None:
        """Clear all cached diffs."""
        try:
            with self._lock:
                self._memory_cache.clear()
                self._memory_used_bytes = 0

            # Clear disk cache
            if self._cache_dir.exists():
                try:
                    for f in self._cache_dir.glob("*.json"):
                        f.unlink()
                except Exception:
                    pass
        except Exception:
            pass

    def stats(self) -> dict:
        """Return cache statistics."""
        try:
            with self._lock:
                total = self._hits + self._misses
                hit_rate = self._hits / total if total > 0 else 0.0

                return {
                    "cache_entries": len(self._memory_cache),
                    "memory_used_mb": round(self._memory_used_bytes / (1024 * 1024), 2),
                    "memory_limit_mb": self._max_memory_bytes / (1024 * 1024),
                    "hits": self._hits,
                    "misses": self._misses,
                    "hit_rate": round(hit_rate, 3),
                    "evictions": self._evictions,
                }
        except Exception:
            return {}

    def _persist_to_disk(self, diff_hash: str, entry: dict) -> bool:
        """Write cache entry to disk. Fails soft."""
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            cache_file = self._cache_dir / f"{diff_hash}.json"

            # Write to temp file first, then rename (atomic)
            temp_file = cache_file.with_suffix(".tmp")
            with open(temp_file, "w", encoding="utf-8", errors="replace") as f:
                json.dump(entry, f)
            temp_file.replace(cache_file)
            return True
        except Exception:
            return False

    def _load_from_disk(self, diff_hash: str) -> dict | None:
        """Load cache entry from disk. Fails soft."""
        try:
            cache_file = self._cache_dir / f"{diff_hash}.json"
            if not cache_file.exists():
                return None

            with open(cache_file, "r", encoding="utf-8", errors="replace") as f:
                entry = json.load(f)

            # Check staleness
            age = time.time() - entry.get("_timestamp", 0)
            if age > self._ttl_seconds:
                cache_file.unlink()
                return None

            # Load back into memory for future access
            with self._lock:
                self._memory_cache[diff_hash] = entry
                self._memory_used_bytes += entry.get("_size_bytes", 0)
                self._memory_cache.move_to_end(diff_hash)
                self._hits += 1

            # Return without internal metadata
            return {k: v for k, v in entry.items() if not k.startswith("_")}

        except Exception:
            return None


# Module-level singleton
_diff_memory: Optional[DiffMemory] = None
_init_lock = threading.Lock()


def acquire() -> DiffMemory:
    """Acquire the singleton DiffMemory instance. Thread-safe."""
    global _diff_memory
    if _diff_memory is not None:
        return _diff_memory

    with _init_lock:
        if _diff_memory is None:
            _diff_memory = DiffMemory()
        return _diff_memory


def store_diff(diff_hash: str, metadata: dict) -> bool:
    """Cache a merged diff metadata entry. Delegates to singleton."""
    return acquire().store_diff(diff_hash, metadata)


def get_diff(diff_hash: str) -> dict | None:
    """Retrieve cached diff metadata by hash. Delegates to singleton."""
    return acquire().get_diff(diff_hash)


def invalidate() -> None:
    """Clear all cached diffs. Delegates to singleton."""
    acquire().invalidate()


def stats() -> dict:
    """Return cache statistics. Delegates to singleton."""
    return acquire().stats()
