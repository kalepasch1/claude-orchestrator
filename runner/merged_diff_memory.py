"""
Merged-diff-memory: metadata tracking for merged commits, supporting fleet recovery and operator queries.

Stores recent merge metadata (not full diffs) in auto-memory for auditability and recovery.
Fail-soft on all errors; missing state returns empty list.
"""

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

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
    except Exception as e:
        logger.warning("merged_diff_memory: could not read %s: %s", MERGED_DIFF_FILE, e)
    return []


def _write_memory(merges: list[dict]) -> bool:
    """Write merged diff metadata to the memory file.

    Returns True if the data was persisted, False on any error. Still
    fail-soft -- callers are never interrupted -- but a failed write is now
    both observable by the caller and logged, rather than swallowed. A
    silently-dropped write left the recovery memory looking populated while
    it was actually stale, which is worse than an empty one.

    The write goes to a temp file in the same directory and is then
    os.replace()d into place, so a crash or a full disk mid-write cannot
    leave behind a truncated file that _read_memory would discard wholesale.
    """
    tmp = MERGED_DIFF_FILE.with_suffix(".json.tmp")
    try:
        MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"merges": merges[-MAX_STORED_MERGES:]}, f, indent=2)
        os.replace(tmp, MERGED_DIFF_FILE)
        return True
    except Exception as e:
        logger.warning("merged_diff_memory: could not write %s: %s", MERGED_DIFF_FILE, e)
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        return False


def write_memory_file(merges: list[dict]) -> bool:
    """Persist merge metadata. True on success, False on any error.

    Public entry point for callers that need to know whether the write
    actually landed (e.g. before reporting a merge as recorded).
    """
    return _write_memory(merges)


def capture_merge(commit_hash: str, branch: str, cwd: str) -> bool:
    """
    Capture metadata for a merged commit.

    Args:
        commit_hash: full commit SHA
        branch: source branch name
        cwd: repo root for git commands

    Returns:
        True if the metadata is on disk (including when the commit was
        already recorded), False if the write failed.
    """
    merges = _read_memory()

    # Skip if already recorded. .get() rather than [] -- a hand-edited or
    # partially-written entry without a "commit" key used to raise KeyError
    # here and abort the capture entirely.
    if any(m.get("commit") == commit_hash for m in merges):
        return True

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

    return _write_memory(merges)


def get_recent_merges(limit: int = 20) -> list[dict]:
    """Get recent merge metadata. Returns empty list on error."""
    merges = _read_memory()
    return merges[-limit:]


def stats() -> dict:
    """Return merge tracking stats."""
    merges = _read_memory()
    return {
        "total_tracked": len(merges),
        "max_capacity": MAX_STORED_MERGES,
        "memory_file": str(MERGED_DIFF_FILE),
        "file_exists": MERGED_DIFF_FILE.exists(),
    }


def invalidate() -> bool:
    """Clear all tracked merges. True if the clear was persisted."""
    return _write_memory([])
