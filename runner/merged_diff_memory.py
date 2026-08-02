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


def stats() -> dict:
    """Return merge tracking stats."""
    merges = _read_memory()
    return {
        "total_tracked": len(merges),
        "max_capacity": MAX_STORED_MERGES,
        "memory_file": str(MERGED_DIFF_FILE),
        "file_exists": MERGED_DIFF_FILE.exists(),
    }


def invalidate() -> None:
    """Clear all tracked merges."""
    _write_memory([])
