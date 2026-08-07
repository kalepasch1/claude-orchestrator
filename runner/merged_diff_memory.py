"""
Merged-diff-memory: thread-safe, fail-soft metadata tracking for merged commits.

Stores recent merge metadata (commit hash, author, date, message, affected files)
in ~/.claude/projects/.../memory/merged_diff_memory.json with max 50 entries.

Fail-soft on all errors; missing state returns empty list/dict.
Module-level singleton pattern: all functions delegate to thread-safe _Pool instance.
"""

import json
import subprocess
import threading
from pathlib import Path
from typing import Optional

MAX_STORED_MERGES = 50


def _get_memory_dir() -> Path:
    """Resolve memory directory dynamically. Falls back to home/.claude/projects/memory on error."""
    try:
        home = Path.home()
        # Derive project ID from repo root path
        cwd = Path.cwd()
        repo_root = cwd
        while repo_root != repo_root.parent:
            if (repo_root / ".git").exists():
                break
            repo_root = repo_root.parent

        # Create project id: convert absolute path to "home-relative-path-format"
        try:
            project_path = str(repo_root.relative_to(home)).replace("/", "-")
            project_id = f"-{home.name}-{project_path}"
        except ValueError:
            # Not under home, use absolute path hash
            project_id = "-" + str(repo_root).replace("/", "-")[1:]

        memory_dir = home / ".claude" / "projects" / project_id / "memory"
        return memory_dir
    except Exception:
        return Path.home() / ".claude" / "projects" / "memory"


class _Pool:
    """Thread-safe singleton for merge metadata storage."""

    def __init__(self):
        self._lock = threading.Lock()
        self._stats = {"reads": 0, "writes": 0, "errors": 0}

    def _safe_run(self, cmd: list[str], cwd: Optional[str] = None) -> str:
        """Run command; return empty string on any error."""
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, timeout=5)
            return result.stdout.strip() if result.returncode == 0 else ""
        except Exception:
            return ""

    def _read_memory(self) -> list[dict]:
        """Load merged diff metadata from memory file. Return [] on any error."""
        with self._lock:
            self._stats["reads"] += 1
            try:
                memory_file = _get_memory_dir() / "merged_diff_memory.json"
                if memory_file.exists():
                    with open(memory_file, encoding="utf-8", errors="replace") as f:
                        data = json.load(f)
                        return data.get("merges", [])
            except Exception:
                self._stats["errors"] += 1
            return []

    def _write_memory(self, merges: list[dict]) -> None:
        """Write merged diff metadata to memory file. Fail-soft on error."""
        with self._lock:
            self._stats["writes"] += 1
            try:
                memory_dir = _get_memory_dir()
                memory_dir.mkdir(parents=True, exist_ok=True)
                memory_file = memory_dir / "merged_diff_memory.json"
                trimmed = merges[-MAX_STORED_MERGES:]
                with open(memory_file, "w", encoding="utf-8") as f:
                    json.dump({"merges": trimmed}, f, indent=2)
            except Exception:
                self._stats["errors"] += 1

    def capture_merge(self, commit_hash: str, branch: str, cwd: str) -> None:
        """Capture metadata for a merged commit."""
        if not commit_hash or not branch or not cwd:
            return

        merges = self._read_memory()

        # Skip if already recorded
        if any(m.get("commit") == commit_hash for m in merges):
            return

        author = self._safe_run(["git", "log", "-1", "--format=%an", commit_hash], cwd=cwd)
        date = self._safe_run(["git", "log", "-1", "--format=%ai", commit_hash], cwd=cwd)
        message = self._safe_run(["git", "log", "-1", "--format=%B", commit_hash], cwd=cwd)
        files = self._safe_run(["git", "diff-tree", "--no-commit-id", "--name-only", "-r", commit_hash], cwd=cwd)

        merge_entry = {
            "commit": commit_hash,
            "branch": branch,
            "author": author or "",
            "date": date or "",
            "message": (message or "")[:500],
            "files": files.split("\n") if files else [],
        }

        merges.append(merge_entry)
        self._write_memory(merges)

    def get_recent_merges(self, limit: int = 10) -> list[dict]:
        """Get recent merged commits. Returns newest first."""
        if limit <= 0:
            return []
        merges = self._read_memory()
        return merges[-limit:][::-1]

    def stats(self) -> dict:
        """Return operation statistics."""
        with self._lock:
            merges = self._read_memory()
            return {
                "reads": self._stats["reads"],
                "writes": self._stats["writes"],
                "errors": self._stats["errors"],
                "max_capacity": MAX_STORED_MERGES,
                "current_count": len(merges),
                "memory_file": str(_get_memory_dir() / "merged_diff_memory.json"),
            }

    def invalidate(self) -> None:
        """Clear all stored merge metadata."""
        with self._lock:
            try:
                memory_dir = _get_memory_dir()
                memory_file = memory_dir / "merged_diff_memory.json"
                if memory_file.exists():
                    memory_file.unlink()
            except Exception:
                self._stats["errors"] += 1


_pool = _Pool()


def capture_merge(commit_hash: str, branch: str, cwd: str) -> None:
    """Capture metadata for a merged commit."""
    _pool.capture_merge(commit_hash, branch, cwd)


def get_recent_merges(limit: int = 10) -> list[dict]:
    """Get recent merged commits. Returns newest first. Empty list on error."""
    return _pool.get_recent_merges(limit)


def stats() -> dict:
    """Return merge tracking statistics (reads, writes, errors, capacity)."""
    return _pool.stats()


def invalidate() -> None:
    """Clear all tracked merges."""
    _pool.invalidate()
