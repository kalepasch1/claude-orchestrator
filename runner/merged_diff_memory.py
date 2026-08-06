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


# ---------------------------------------------------------------------------
# File-based merged-learning memory (suite: runner/tests/test_merged_diff_memory.py)
#
# Captures do/avoid rules from merged commit messages into dated markdown
# files under MEMORY_ROOT, indexed by MEMORY.md, with age-based pruning and
# a jsonl error log under HOME. Fail-soft throughout.
# ---------------------------------------------------------------------------

import re as _re
from datetime import datetime as _datetime, timedelta as _timedelta

MEMORY_ROOT = str(MEMORY_DIR)
HOME = str(Path.home())


def _error_log_path() -> str:
    """Error log lives under the (test-overridable) HOME."""
    return os.path.join(HOME, "logs", "merged_diff_memory_errors.jsonl")


def __getattr__(name):  # PEP 562: ERROR_LOG tracks reassignment of HOME
    if name == "ERROR_LOG":
        return _error_log_path()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def _log_error(message: str, context: Optional[str] = None) -> None:
    """Append an error entry to the jsonl log. Never raises."""
    try:
        path = _error_log_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "message": message,
                "context": context,
                "timestamp": _datetime.utcnow().isoformat(),
            }) + "\n")
    except Exception:
        pass


def _ensure_dirs() -> None:
    """Create MEMORY_ROOT and the error-log directory (idempotent)."""
    os.makedirs(MEMORY_ROOT, exist_ok=True)
    os.makedirs(os.path.dirname(_error_log_path()), exist_ok=True)


def _extract_rules(text: str) -> list[str]:
    """Find bullet-point DO/AVOID rules in free text."""
    rules: list[str] = []
    for line in (text or "").splitlines():
        stripped = line.strip()
        if not stripped.startswith("-"):
            continue
        body = stripped.lstrip("-").strip()
        if body.upper().startswith(("DO ", "DO:", "AVOID ", "AVOID:")):
            rules.append(body)
    return rules


def _save_to_memory(patterns: list[dict]) -> tuple[bool, Optional[str]]:
    """Write patterns to a dated markdown file under MEMORY_ROOT."""
    if not patterns:
        return True, None
    try:
        os.makedirs(MEMORY_ROOT, exist_ok=True)
        today = _datetime.utcnow()
        path = os.path.join(MEMORY_ROOT, f"merged_learning_{today.strftime('%Y%m%d')}.md")
        lines = [f"# Merged learning — {today.date().isoformat()}", ""]
        for pattern in patterns:
            lines.append(f"## Commit {pattern.get('commit', 'unknown')}")
            frameworks = sorted(pattern.get("frameworks") or [])
            if frameworks:
                lines.append(f"Frameworks: {', '.join(frameworks)}")
            for rule in pattern.get("rules") or []:
                lines.append(f"- {rule}")
            files = [f for f in (pattern.get("files") or []) if f]
            if files:
                lines.append("Files: " + ", ".join(files))
            lines.append("")
        Path(path).write_text("\n".join(lines), encoding="utf-8")
        return True, path
    except Exception as e:
        _log_error(str(e), context="_save_to_memory")
        return False, None


def _update_memory_index(memory_file: str) -> bool:
    """Add (dedup) an entry for memory_file to MEMORY_ROOT/MEMORY.md."""
    try:
        base = os.path.basename(memory_file)
        m = _re.search(r"(\d{4})(\d{2})(\d{2})", base)
        date_str = "-".join(m.groups()) if m else _datetime.utcnow().date().isoformat()
        index_path = os.path.join(MEMORY_ROOT, "MEMORY.md")
        existing = ""
        if os.path.exists(index_path):
            existing = Path(index_path).read_text(encoding="utf-8", errors="replace")
        if base in existing:
            return True
        if existing and not existing.endswith("\n"):
            existing += "\n"
        existing += f"- [Merged learning {date_str}]({base}) — {date_str}\n"
        Path(index_path).write_text(existing, encoding="utf-8")
        return True
    except Exception as e:
        _log_error(str(e), context="_update_memory_index")
        return False


def _prune_old_entries(index_file: str, days: int = 90) -> None:
    """Drop index lines whose ISO date is older than the cutoff. Fail-soft."""
    try:
        cutoff = _datetime.utcnow().date() - _timedelta(days=days)
        content = Path(index_file).read_text(encoding="utf-8", errors="replace")
        kept = []
        for line in content.splitlines():
            dates = _re.findall(r"\d{4}-\d{2}-\d{2}", line)
            parsed = []
            for d in dates:
                try:
                    parsed.append(_datetime.strptime(d, "%Y-%m-%d").date())
                except ValueError:
                    pass
            if parsed and min(parsed) < cutoff:
                continue
            kept.append(line)
        Path(index_file).write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
    except Exception as e:
        _log_error(str(e), context="_prune_old_entries")


def run(repo: Optional[str] = None, dry_run: bool = False) -> dict:
    """Capture DO/AVOID rules from merged commits into the learning memory.

    Returns {"success", "merged_count", "patterns_count", "memory_file"};
    never raises (errors are logged and reflected in "success").
    """
    result: dict = {"success": True, "merged_count": 0, "patterns_count": 0, "memory_file": None}
    try:
        repo = repo or os.getcwd()
        out = _safe_run(["git", "log", "--merges", "--pretty=%H"], cwd=repo)
        merges = [h for h in out.splitlines() if h.strip()]
        result["merged_count"] = len(merges)

        patterns = []
        for commit in merges:
            text = _safe_run(["git", "log", "-1", "--pretty=%B", commit], cwd=repo)
            branch_tip = _safe_run(["git", "log", "-1", "--pretty=%B", f"{commit}^2"], cwd=repo)
            rules = _extract_rules(text + "\n" + branch_tip)
            if not rules:
                continue
            files = _safe_run(
                ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", commit], cwd=repo)
            patterns.append({
                "commit": commit,
                "rules": rules,
                "frameworks": [],
                "files": files.splitlines() if files else [],
                "timestamp": _datetime.utcnow().isoformat(),
            })
        result["patterns_count"] = len(patterns)

        if patterns:
            if dry_run:
                result["memory_file"] = "<dry-run: no files written>"
            else:
                _ensure_dirs()
                ok, memory_file = _save_to_memory(patterns)
                if ok and memory_file:
                    _update_memory_index(memory_file)
                    result["memory_file"] = memory_file
                else:
                    result["success"] = False
        return result
    except Exception as e:
        _log_error(str(e), context="run")
        result["success"] = False
        return result
