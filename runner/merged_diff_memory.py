"""
Merged-diff-memory: metadata tracking for merged commits, supporting fleet recovery and operator queries.

Stores recent merge metadata (not full diffs) in auto-memory for auditability and recovery.
Fail-soft on all errors; missing state returns empty list.
"""

import json
import os
import subprocess
from pathlib import Path
from typing import Optional

MEMORY_DIR = Path.home() / ".claude" / "projects" / "-Users-kpasch-Documents-beethoven-claude-orchestrator" / "memory"
MERGED_DIFF_FILE = MEMORY_DIR / "merged_diff_memory.json"
MAX_STORED_MERGES = 50


def _safe_run(cmd: list[str], cwd: Optional[str] = None) -> str:
    """Run command; return empty string on any error."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, timeout=5)
        return result.stdout.strip() if result.returncode == 0 else ""
    except Exception:
        return ""


def _read_memory() -> list[dict]:
    """Load merged diff metadata from memory file. Return [] on any error."""
    try:
        if MERGED_DIFF_FILE.exists():
            with open(MERGED_DIFF_FILE, encoding="utf-8", errors="replace") as f:
                data = json.load(f)
                return data.get("merges", [])
    except Exception:
        pass
    return []


def _write_memory(merges: list[dict]) -> None:
    """Write merged diff metadata to memory file. Fail-soft on error."""
    try:
        MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        with open(MERGED_DIFF_FILE, "w", encoding="utf-8") as f:
            json.dump({"merges": merges[-MAX_STORED_MERGES:]}, f, indent=2)
    except Exception:
        pass


def capture_merge(commit_hash: str, branch: str, cwd: str) -> None:
    """
    Capture metadata for a merged commit.

    Args:
        commit_hash: full commit SHA
        branch: source branch name
        cwd: repo root for git commands
    """
    merges = _read_memory()

    # Skip if already recorded
    if any(m["commit"] == commit_hash for m in merges):
        return

    author = _safe_run(["git", "log", "-1", "--format=%an", commit_hash], cwd=cwd)
    date = _safe_run(["git", "log", "-1", "--format=%aI", commit_hash], cwd=cwd)
    message = _safe_run(["git", "log", "-1", "--format=%s", commit_hash], cwd=cwd)
    files = _safe_run(["git", "diff-tree", "--no-commit-id", "--name-only", "-r", commit_hash], cwd=cwd)

    merges.append({
        "commit": commit_hash,
        "branch": branch,
        "author": author,
        "date": date,
        "message": message,
        "files_affected": files.split("\n") if files else [],
    })

    _write_memory(merges)


def get_recent_merges(limit: int = 20) -> list[dict]:
    """Get recent merge metadata. Returns empty list on error."""
    merges = _read_memory()
    return merges[-limit:]


def _tracking_stats() -> dict:
    """Return merge tracking stats (metadata file)."""
    merges = _read_memory()
    return {
        "total_tracked": len(merges),
        "max_capacity": MAX_STORED_MERGES,
        "memory_file": str(MERGED_DIFF_FILE),
        "file_exists": MERGED_DIFF_FILE.exists(),
    }


def _invalidate_tracking() -> None:
    """Clear all tracked merges (metadata file)."""
    _write_memory([])


# ---------------------------------------------------------------------------
# Merged-diff cache (spec: test_merged_diff_memory_spec.py)
#
# Minimal thread-safe in-memory cache for computed diffs of merged branches.
# Chosen per the merged-diff-memory investigation strategy: the earlier
# file-based learning mechanism was replaced with this simple cache.
# Fail-soft everywhere; invalid input is ignored, errors return "".
# ---------------------------------------------------------------------------

import threading
import time

try:  # pragma: no cover - import shape differs between entry points
    import resource_governor  # type: ignore
except Exception:  # pragma: no cover
    try:
        from runner import resource_governor  # type: ignore
    except Exception:
        resource_governor = None  # type: ignore

CACHE_TTL = float(os.environ.get("ORCH_DIFF_CACHE_TTL", "3600") or 3600)
CACHE_SIZE_BYTES = int(os.environ.get("ORCH_DIFF_CACHE_SIZE", str(50 * 1024 * 1024)) or 50 * 1024 * 1024)


def _valid_str(value) -> bool:
    return isinstance(value, str) and value != ""


class _DiffPool:
    """Thread-safe (base, branch, commit) -> diff cache with TTL + size cap."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._entries: dict[tuple[str, str, str], tuple[str, float, int]] = {}
        self._bytes = 0
        self._hits = 0
        self._misses = 0

    def put_diff(self, branch_a: str, branch_b: str, commit: str, content: str) -> None:
        size = len(content.encode("utf-8", errors="replace"))
        max_entry = max(1, CACHE_SIZE_BYTES // 10)
        if size > max_entry:
            content = content.encode("utf-8", errors="replace")[:max_entry].decode(
                "utf-8", errors="ignore")
            size = len(content.encode("utf-8", errors="replace"))
        key = (branch_a, branch_b, commit)
        with self._lock:
            reclaimed = self._entries.get(key, (None, 0.0, 0))[2]
            if self._bytes - reclaimed + size > CACHE_SIZE_BYTES:
                return  # cache full — silently refuse
            if key in self._entries:
                self._bytes -= reclaimed
            self._entries[key] = (content, time.time(), size)
            self._bytes += size

    def get_diff(self, branch_a: str, branch_b: str, commit: str) -> str:
        key = (branch_a, branch_b, commit)
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                self._misses += 1
                return ""
            content, stored_at, size = entry
            if time.time() - stored_at > CACHE_TTL:
                del self._entries[key]
                self._bytes -= size
                self._misses += 1
                return ""
            self._hits += 1
            return content

    def stats(self) -> dict:
        with self._lock:
            return {
                "entries": len(self._entries),
                "bytes_used": self._bytes,
                "hits": self._hits,
                "misses": self._misses,
            }

    def invalidate(self) -> None:
        with self._lock:
            self._entries.clear()
            self._bytes = 0
            self._hits = 0
            self._misses = 0


_pool = _DiffPool()


def put_diff(branch_a, branch_b, commit_hash, diff_content) -> None:
    """Cache a computed diff. Silently ignores invalid input and errors."""
    try:
        if not (_valid_str(branch_a) and _valid_str(branch_b)
                and _valid_str(commit_hash) and _valid_str(diff_content)):
            return
        if resource_governor is not None:
            size = len(diff_content.encode("utf-8", errors="replace"))
            ok = resource_governor.can_claim(size)
            if isinstance(ok, tuple):
                ok = ok[0]
            if not ok:
                return
        _pool.put_diff(branch_a, branch_b, commit_hash, diff_content)
    except Exception:
        pass


def get_diff(branch_a, branch_b, commit_hash) -> str:
    """Fetch a cached diff; '' on miss, expiry, invalid input, or error."""
    try:
        if not (_valid_str(branch_a) and _valid_str(branch_b) and _valid_str(commit_hash)):
            return ""
        return _pool.get_diff(branch_a, branch_b, commit_hash)
    except Exception:
        return ""


def stats() -> dict:
    """Cache + merge-tracking introspection. Fail-soft.

    Union of the cache counters (entries, bytes_used, hits, misses) and the
    legacy metadata-tracking stats (total_tracked, max_capacity, file_exists).
    """
    out = {"entries": 0, "bytes_used": 0, "hits": 0, "misses": 0}
    try:
        out.update(_pool.stats())
    except Exception:
        pass
    try:
        out.update(_tracking_stats())
    except Exception:
        pass
    return out


def invalidate() -> None:
    """Clear the diff cache AND tracked-merge metadata. Fail-soft, idempotent."""
    try:
        _pool.invalidate()
    except Exception:
        pass
    try:
        _invalidate_tracking()
    except Exception:
        pass
