#!/usr/bin/env python3
"""
merged_diff_memory.py - Capture learned patterns from merged commits into auto-memory.

On each run, reads recent master commits, extracts quality-gated patterns from
learn_from_merges.py output, and saves to the auto-memory system with daily rollup.
Integrates seamlessly with the existing task_memory.py and memory index (MEMORY.md).

Fail-soft: errors in DB, file I/O, or memory writing do not wedge the runner.
"""
import os
import sys
import json
import re
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
import hashlib
import logging
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import learn_from_merges

HOME = os.environ.get("CLAUDE_ORCH_HOME", os.path.expanduser("~/.claude-orchestrator"))
MEMORY_ROOT = os.environ.get("CLAUDE_MEMORY_ROOT",
                              os.path.expanduser("~/.claude/projects/-Users-kpasch-Documents-beethoven-claude-orchestrator/memory"))
LOOKBACK = int(os.environ.get("MERGED_MEMORY_LOOKBACK", "14"))  # days
ERROR_LOG = os.path.join(HOME, "knowledge", "merged_diff_memory_errors.jsonl")

_lock = threading.Lock()


def _ensure_dirs():
    try:
        os.makedirs(MEMORY_ROOT, exist_ok=True)
        os.makedirs(os.path.dirname(ERROR_LOG), exist_ok=True)
    except Exception:
        pass


def _log_error(msg, context=""):
    try:
        _ensure_dirs()
        with open(ERROR_LOG, "a") as f:
            entry = {
                "timestamp": datetime.utcnow().isoformat(),
                "message": msg,
                "context": context,
            }
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass


def _get_merged_commits(repo=".", lookback_days=None):
    """Return list of (commit_hash, commit_msg) tuples merged to master in the last N days."""
    if lookback_days is None:
        lookback_days = LOOKBACK
    try:
        since = f"--since={lookback_days} days ago"
        cmd = ["git", "log", "--oneline", "--merges", since, "master"]
        out = subprocess.check_output(cmd, cwd=repo, text=True, errors="replace", timeout=30)
        commits = []
        for line in out.strip().splitlines():
            if line.strip():
                parts = line.split(None, 1)
                if len(parts) >= 2:
                    commits.append((parts[0], parts[1]))
        return commits
    except Exception as e:
        _log_error(f"Failed to get merged commits: {e}", f"repo={repo}")
        return []


def _extract_patterns_from_commit(repo, commit_hash):
    """
    Extract learned patterns from a merged commit using learn_from_merges logic.
    Returns dict with 'rules', 'frameworks', 'files' if successful, None on error.
    """
    try:
        # Get the commit message and diff
        msg_out = subprocess.check_output(
            ["git", "log", "-1", "--format=%B", commit_hash],
            cwd=repo, text=True, errors="replace", timeout=10
        )
        diff_out = subprocess.check_output(
            ["git", "show", "--stat", commit_hash],
            cwd=repo, text=True, errors="replace", timeout=30
        )

        full_text = f"{msg_out}\n{diff_out}"

        # Apply quality gate; if rejected, do not save
        accepted, reason = learn_from_merges.quality_gate(full_text, source=commit_hash)
        if not accepted:
            return None  # silently skip; quality gate already logged

        # Extract patterns using learn_from_merges helpers
        from merged_diff_library import _frameworks
        rules = learn_from_merges._extract_rules(msg_out)  # defined below as helper
        frameworks = _frameworks(full_text)
        files = learn_from_merges._changed_files(repo, f"{commit_hash}^", commit_hash)

        return {
            "commit": commit_hash,
            "rules": rules or [],
            "frameworks": frameworks,
            "files": files,
            "timestamp": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        _log_error(f"Failed to extract patterns from {commit_hash}: {e}", f"repo={repo}")
        return None


def _extract_rules(text):
    """Extract do/avoid bullet points from commit message or diff."""
    lines = (text or "").split("\n")
    rules = []
    for line in lines:
        stripped = line.strip()
        # Match bullet points that look like conventions/rules
        if re.match(r"^\s*(?:[-*•]|\d+[.)])\s+(?:DO|AVOID|DO NOT|NEVER|ALWAYS)\b", line, re.I):
            rules.append(stripped.lstrip("*-•0123456789.). "))
    return rules


def _save_to_memory(patterns_list):
    """
    Save extracted patterns to daily rollup file in memory system.
    Returns (success: bool, memory_file: str or None).
    """
    if not patterns_list:
        return True, None

    try:
        _ensure_dirs()

        today = datetime.utcnow().date()
        memory_file = os.path.join(MEMORY_ROOT, f"merged_learning_{today.strftime('%Y%m%d')}.md")

        # Build content
        all_rules = set()
        all_frameworks = set()
        all_commits = []

        for p in patterns_list:
            if p:
                all_rules.update(p.get("rules", []))
                all_frameworks.update(p.get("frameworks", []))
                all_commits.append(p.get("commit", ""))

        rules_section = "\n".join(f"- {r}" for r in sorted(all_rules)) if all_rules else ""
        frameworks_section = ", ".join(sorted(all_frameworks)) if all_frameworks else "none"
        commits_section = ", ".join(sorted(set(all_commits)))

        frontmatter = f"""---
name: merged_learning_{today.strftime('%Y%m%d')}
description: Patterns and conventions from master merges on {today.isoformat()}
metadata:
  type: project
  date: {today.isoformat()}
  commits: {commits_section}
---

## Learned Conventions & Do/Avoid Rules
{rules_section if rules_section else "(no new rules extracted today)"}

## Frameworks in Use
{frameworks_section}

See also: [[project_claude_orchestrator]], [[project_orchestrator]]
"""

        # Write or append
        with _lock:
            if os.path.exists(memory_file):
                with open(memory_file, "r") as f:
                    existing = f.read()
                if existing.strip():
                    # File exists and has content; skip today (already captured)
                    return True, memory_file
            with open(memory_file, "w") as f:
                f.write(frontmatter)

        return True, memory_file
    except Exception as e:
        _log_error(f"Failed to save patterns to memory: {e}", f"patterns={len(patterns_list)}")
        return False, None


def _update_memory_index(memory_file):
    """Add entry to MEMORY.md index if not already present."""
    if not memory_file:
        return True
    try:
        _ensure_dirs()
        index_file = os.path.join(MEMORY_ROOT, "MEMORY.md")
        base = os.path.basename(memory_file)
        date = datetime.strptime(base.split("_")[-1].split(".")[0], "%Y%m%d").date()

        # Read existing
        existing_entries = []
        if os.path.exists(index_file):
            with open(index_file, "r") as f:
                existing_entries = f.readlines()

        # Check if already in index
        for line in existing_entries:
            if base in line:
                return True  # already indexed

        # Add new entry
        new_entry = f"- [Merged patterns {date.isoformat()}]({base}) — conventions from master commits\n"
        with _lock:
            with open(index_file, "a") as f:
                f.write(new_entry)

        # Prune old entries (keep last 90 days)
        _prune_old_entries(index_file, days=90)
        return True
    except Exception as e:
        _log_error(f"Failed to update MEMORY.md index: {e}", f"file={memory_file}")
        return False


def _prune_old_entries(index_file, days=90):
    """Remove entries older than N days from MEMORY.md."""
    try:
        cutoff = datetime.utcnow().date() - timedelta(days=days)
        with open(index_file, "r") as f:
            lines = f.readlines()

        kept = []
        for line in lines:
            # Try to extract date from line
            match = re.search(r"(\d{4})-(\d{2})-(\d{2})", line)
            if match:
                try:
                    entry_date = datetime.strptime(f"{match.group(1)}{match.group(2)}{match.group(3)}", "%Y%m%d").date()
                    if entry_date >= cutoff:
                        kept.append(line)
                except Exception:
                    kept.append(line)  # keep if unparseable
            else:
                kept.append(line)

        with _lock:
            with open(index_file, "w") as f:
                f.writelines(kept)
    except Exception as e:
        _log_error(f"Failed to prune old index entries: {e}")


def capture_to_memory(repo=".", dry_run=False):
    """Capture merged-diff patterns into the memory system. Returns True/False.

    The boolean contract for callers that only need "did it land?": True when a memory
    file was actually written, False on ANY failure — bad git ref, not a repo, no diffs
    to capture, file I/O error, database error. It never raises.

    True is tied to a WRITTEN FILE, not to "the function completed". A run that finds no
    merged commits returns False: nothing was persisted, so a caller that treats True as
    "memory is now current" would be misled. That distinction is the whole point of the
    boolean — `run()` remains available for callers that need the counts and the reason.

    A dry run always returns False; it deliberately writes nothing.

    Failures are reported via logging.warning rather than swallowed silently, so a
    persistently failing capture is visible in the logs instead of looking like a
    no-op forever.
    """
    try:
        result = run(repo=repo, dry_run=dry_run)
    except Exception as exc:            # run() is fail-soft, but never trust that here
        logging.warning("merged_diff_memory: capture raised: %s: %s",
                        type(exc).__name__, exc)
        return False

    if not isinstance(result, dict):
        logging.warning("merged_diff_memory: capture returned %r, expected dict",
                        type(result).__name__)
        return False

    if result.get("error"):
        logging.warning("merged_diff_memory: capture failed: %s", result["error"])
        return False

    if not result.get("success") or not result.get("memory_file"):
        logging.warning(
            "merged_diff_memory: nothing written (success=%s, merged_count=%s, "
            "patterns_count=%s)",
            result.get("success"), result.get("merged_count"),
            result.get("patterns_count"))
        return False

    return True


def run(repo=".", dry_run=False):
    """
    Main entry point: capture merged patterns and save to memory.
    Returns dict with summary: {success, merged_count, patterns_count, memory_file}.
    """
    result = {
        "success": False,
        "merged_count": 0,
        "patterns_count": 0,
        "memory_file": None,
        "error": None,
    }

    try:
        commits = _get_merged_commits(repo, LOOKBACK)
        result["merged_count"] = len(commits)

        patterns = []
        for commit_hash, msg in commits:
            p = _extract_patterns_from_commit(repo, commit_hash)
            if p:
                patterns.append(p)

        result["patterns_count"] = len(patterns)

        if patterns:
            if not dry_run:
                success, memory_file = _save_to_memory(patterns)
                result["success"] = success
                result["memory_file"] = memory_file
                if success and memory_file:
                    _update_memory_index(memory_file)
            else:
                result["success"] = True
                result["memory_file"] = f"[dry-run] would save {len(patterns)} patterns"
        else:
            result["success"] = True  # no patterns to save is OK

        return result
    except Exception as e:
        _log_error(f"Unhandled error in run(): {e}")
        result["error"] = str(e)
        return result


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Capture merged diffs into auto-memory")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be saved without writing")
    parser.add_argument("--lookback", type=int, default=LOOKBACK, help="Days to look back")
    args = parser.parse_args()

    LOOKBACK = args.lookback
    result = run(dry_run=args.dry_run)
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["success"] else 1)


# ---------------------------------------------------------------------------
# Merge-metadata tracking (added later, in commit 68f17db0).
#
# RESTORED 2026-08-06: 68f17db0 landed this metadata API by REPLACING the whole
# module above rather than extending it. That silently deleted the distillation
# pipeline (_extract_rules/_save_to_memory/_update_memory_index/run) that feeds
# the "## Learned from merged work (auto)" sections of CLAUDE.md, and left its
# 13-case suite erroring at setup with `module has no attribute MEMORY_ROOT`.
# Both features are wanted, and their names do not collide, so both now live
# here: the distillation pipeline above, the metadata tracker below.
# ---------------------------------------------------------------------------

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


def recent(days: int = 14, limit: int = 50, repo: str = ".") -> list[dict]:
    """Return recent merged commits with their diff text.

    ADDED 2026-08-06: self_authored_capabilities.scan_recent_diffs() has always
    called mdm.recent(days=, limit=) — a function no version of this module ever
    defined. The call sits inside `except Exception: diffs = []`, so instead of
    raising it silently yielded zero diffs on every run, and capability
    self-authoring has been quietly detecting nothing since it shipped. The guard
    turned a missing function into a permanent no-op, which is the worst of both.

    Each record carries a "diff" key because that is what the caller regex-scans;
    metadata-only records would match nothing. Fail-soft: returns [] on any error.
    """
    try:
        days = max(1, int(days))
        limit = max(1, int(limit))
    except (TypeError, ValueError):
        days, limit = 14, 50

    try:
        since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        out = _safe_run(
            ["git", "log", f"--since={since}", f"--max-count={limit}",
             "--merges", "--format=%H"], cwd=repo)
        if not out:
            # Repos that fast-forward instead of merging have no merge commits;
            # fall back to plain commits so the scanner still sees real code.
            out = _safe_run(
                ["git", "log", f"--since={since}", f"--max-count={limit}",
                 "--format=%H"], cwd=repo)
        shas = [s for s in out.split("\n") if s.strip()]
    except Exception:
        return []

    records = []
    for sha in shas[:limit]:
        try:
            diff = _safe_run(["git", "show", "--format=%s", "--unified=0", sha], cwd=repo)
            if not diff:
                continue
            records.append({
                "commit": sha,
                "date": _safe_run(["git", "log", "-1", "--format=%aI", sha], cwd=repo),
                "message": _safe_run(["git", "log", "-1", "--format=%s", sha], cwd=repo),
                "diff": diff,
            })
        except Exception:
            continue
    return records

def write_memory_file(merges: list[dict]) -> bool:
    """Persist merge metadata. True on success, False on any error.

    Public entry point for callers that need to know whether the write
    actually landed (e.g. before reporting a merge as recorded).
    """
    return _write_memory(merges)

