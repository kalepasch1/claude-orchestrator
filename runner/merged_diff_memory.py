#!/usr/bin/env python3
"""
merged_diff_memory.py - Thread-safe cache for computed diffs from merged branches/PRs.

Stores computed diff results keyed by (branch_a, branch_b, merge_commit).
Returns cached diffs within TTL (default 3600s, configurable via ORCH_DIFF_CACHE_TTL).
Fails soft: returns empty string on cache miss or error, never raises.
Provides stats() and invalidate() methods for operators.
Enforces memory limits via resource_governor.can_claim() before adding new entries.
"""
import os
import sys
import time
import threading
from typing import Optional, Dict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import resource_governor
except ImportError:
    resource_governor = None

# Configuration from environment variables
CACHE_SIZE_MB = int(os.environ.get("ORCH_DIFF_CACHE_SIZE", "100"))
CACHE_SIZE_BYTES = CACHE_SIZE_MB * 1024 * 1024
CACHE_TTL = int(os.environ.get("ORCH_DIFF_CACHE_TTL", "3600"))

_lock = threading.Lock()


class _DiffCache:
    """Thread-safe singleton cache for merged diffs."""

    def __init__(self):
        self.cache = {}  # (branch_a, branch_b, commit) -> (diff_content, timestamp)
        self.bytes_used = 0
        self.hits = 0
        self.misses = 0

    def get_diff(
        self, branch_a: Optional[str], branch_b: Optional[str], commit_hash: Optional[str]
    ) -> str:
        """Retrieve cached diff or return empty string on miss/error."""
        if not branch_a or not branch_b or not commit_hash:
            self.misses += 1
            return ""

        key = (branch_a, branch_b, commit_hash)
        now = time.time()

        try:
            if key not in self.cache:
                self.misses += 1
                return ""

            diff_content, timestamp = self.cache[key]

            # Check TTL
            if now - timestamp > CACHE_TTL:
                del self.cache[key]
                self.bytes_used -= len(diff_content.encode("utf-8", errors="replace"))
                self.misses += 1
                return ""

            self.hits += 1
            return diff_content
        except Exception:
            self.misses += 1
            return ""

    def put_diff(
        self,
        branch_a: Optional[str],
        branch_b: Optional[str],
        commit_hash: Optional[str],
        diff_content: Optional[str],
    ) -> None:
        """Cache a diff, respecting size limits. Fails soft on error."""
        if not branch_a or not branch_b or not commit_hash or not diff_content:
            return

        key = (branch_a, branch_b, commit_hash)
        diff_bytes = len(diff_content.encode("utf-8", errors="replace"))

        try:
            # Truncate oversized diffs at byte limit (max 10% of cache per entry) first
            max_bytes_per_entry = CACHE_SIZE_BYTES // 10
            if diff_bytes > max_bytes_per_entry:
                truncated = diff_content.encode("utf-8", errors="replace")[
                    :max_bytes_per_entry
                ].decode("utf-8", errors="ignore")
                diff_content = truncated
                diff_bytes = len(diff_content.encode("utf-8", errors="replace"))

            # Check if resource_governor allows this
            if resource_governor and not resource_governor.can_claim(diff_bytes):
                return

            # Check total size after truncation
            if self.bytes_used + diff_bytes > CACHE_SIZE_BYTES:
                return

            # Remove old entry if exists to reclaim space
            if key in self.cache:
                old_content, _ = self.cache[key]
                self.bytes_used -= len(old_content.encode("utf-8", errors="replace"))

            self.cache[key] = (diff_content, time.time())
            self.bytes_used += diff_bytes
        except Exception:
            pass

    def invalidate(self) -> None:
        """Clear cache and reset counters. Safe to call during get/put."""
        self.cache.clear()
        self.bytes_used = 0
        self.hits = 0
        self.misses = 0

    def stats(self) -> Dict[str, int]:
        """Return cache statistics."""
        return {
            "entries": len(self.cache),
            "bytes_used": self.bytes_used,
            "hits": self.hits,
            "misses": self.misses,
        }


_pool = _DiffCache()


def get_diff(
    branch_a: Optional[str], branch_b: Optional[str], commit_hash: Optional[str]
) -> str:
    """Get cached diff for (branch_a, branch_b, commit_hash). Returns "" on miss/error."""
    try:
        with _lock:
            return _pool.get_diff(branch_a, branch_b, commit_hash)
    except Exception:
        return ""


def put_diff(
    branch_a: Optional[str],
    branch_b: Optional[str],
    commit_hash: Optional[str],
    diff_content: Optional[str],
) -> None:
    """Cache diff for (branch_a, branch_b, commit_hash). Fails soft on error."""
    try:
        with _lock:
            _pool.put_diff(branch_a, branch_b, commit_hash, diff_content)
    except Exception:
        pass


def invalidate() -> None:
    """Clear all cached diffs and reset counters."""
    with _lock:
        _pool.invalidate()


def stats() -> Dict[str, int]:
    """Get cache statistics: {entries, bytes_used, hits, misses}."""
    try:
        with _lock:
            return _pool.stats()
    except Exception:
        return {"entries": 0, "bytes_used": 0, "hits": 0, "misses": 0}
