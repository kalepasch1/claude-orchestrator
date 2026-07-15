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
import json
import re
import subprocess
from datetime import datetime, timedelta
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
HOME = os.environ.get("CLAUDE_ORCH_HOME", os.path.expanduser("~/.claude-orchestrator"))
MEMORY_ROOT = os.environ.get("CLAUDE_MEMORY_ROOT", os.path.expanduser("~/.claude-orchestrator/memory"))
LOOKBACK = int(os.environ.get("MERGED_MEMORY_LOOKBACK", "14"))
ERROR_LOG = os.path.join(HOME, "knowledge", "merged_diff_memory_errors.jsonl")


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


def _ensure_dirs():
    os.makedirs(MEMORY_ROOT, exist_ok=True)
    os.makedirs(os.path.dirname(ERROR_LOG), exist_ok=True)


def _log_error(message, context=""):
    try:
        _ensure_dirs()
        with open(ERROR_LOG, "a") as handle:
            handle.write(json.dumps({"timestamp": datetime.utcnow().isoformat(),
                                     "message": message, "context": context}) + "\n")
    except Exception:
        pass


def _extract_rules(text):
    return [line.strip().lstrip("*-•0123456789.). ") for line in (text or "").splitlines()
            if re.match(r"^\s*(?:[-*•]|\d+[.)])\s+(?:DO|AVOID|DO NOT|NEVER|ALWAYS)\b", line, re.I)]


def _merged_commits(repo, days=LOOKBACK):
    try:
        output = subprocess.check_output(["git", "log", "--oneline", "--merges",
                                          f"--since={days} days ago", "master"],
                                         cwd=repo, text=True, timeout=30)
        return [tuple(line.split(None, 1)) for line in output.splitlines() if " " in line]
    except Exception:
        return []


def _save_to_memory(patterns):
    if not patterns:
        return True, None
    try:
        _ensure_dirs(); today = datetime.utcnow().date(); path = os.path.join(MEMORY_ROOT, f"merged_learning_{today:%Y%m%d}.md")
        rules = sorted({rule for pattern in patterns for rule in pattern.get("rules", [])})
        frameworks = sorted({item for pattern in patterns for item in pattern.get("frameworks", [])})
        content = f"# Merged learning {today.isoformat()}\n\n" + "\n".join(f"- {rule}" for rule in rules)
        content += "\n\nFrameworks: " + (", ".join(frameworks) or "none") + "\n"
        with open(path, "w") as handle: handle.write(content)
        return True, path
    except Exception as exc:
        _log_error(str(exc), "save"); return False, None


def _update_memory_index(memory_file):
    if not memory_file: return True
    try:
        _ensure_dirs(); index = os.path.join(MEMORY_ROOT, "MEMORY.md"); base = os.path.basename(memory_file)
        existing = open(index).read() if os.path.exists(index) else ""
        if base not in existing:
            stamp = re.search(r"(\d{4})(\d{2})(\d{2})", base)
            date = f"{stamp.group(1)}-{stamp.group(2)}-{stamp.group(3)}" if stamp else datetime.utcnow().date().isoformat()
            with open(index, "a") as handle: handle.write(f"- [Merged patterns {date}]({base})\n")
        return True
    except Exception as exc:
        _log_error(str(exc), "index"); return False


def _prune_old_entries(index_file, days=90):
    cutoff = datetime.utcnow().date() - timedelta(days=days)
    try:
        lines = open(index_file).readlines(); kept = []
        for line in lines:
            match = re.search(r"(\d{4})-(\d{2})-(\d{2})", line)
            if not match or datetime.strptime("".join(match.groups()), "%Y%m%d").date() >= cutoff: kept.append(line)
        with open(index_file, "w") as handle: handle.writelines(kept)
    except Exception as exc: _log_error(str(exc), "prune")


def run(repo=".", dry_run=False):
    commits = _merged_commits(repo); patterns = []
    for commit, message in commits:
        rules = _extract_rules(message)
        if rules: patterns.append({"commit": commit, "rules": rules, "frameworks": [], "files": []})
    if dry_run: return {"success": True, "merged_count": len(commits), "patterns_count": len(patterns), "memory_file": "[dry-run]" if patterns else None}
    success, path = _save_to_memory(patterns)
    if success and path: _update_memory_index(path)
    return {"success": success, "merged_count": len(commits), "patterns_count": len(patterns), "memory_file": path}
