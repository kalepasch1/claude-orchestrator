"""
Merged-diff-memory: metadata tracking for merged commits, supporting fleet recovery and operator queries.

Stores recent merge metadata (not full diffs) in auto-memory for auditability and recovery.
Fail-soft on all errors; missing state returns empty list.
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from bot_commit_verifier import is_merge_commit
except ImportError:                                   # fail-soft, like the rest of this module
    def is_merge_commit(message):                     # type: ignore[misc]
        return False

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


def _classify_merge(commit_hash: str, message: str, cwd: str) -> tuple[bool, str]:
    """Decide whether a commit is a merge, and say HOW it was decided.

    Two sources, deliberately ranked:

      "parents" — `git rev-list --parents -n 1 <sha>` yields the sha plus its parents.
                  More than one parent IS a merge, definitionally. When the repository
                  is reachable this is proof, not a guess, and it is right about the
                  cases message text cannot be ("Merge remote-tracking branch ...",
                  squash merges, a commit whose body merely quotes a merge subject).

      "message"  — is_merge_commit() on the subject. The fallback for records captured
                  where the repo is gone (a pruned worktree, another machine, a replay
                  from stored metadata), which is most of this module's job.

    Recording the source alongside the verdict keeps the distinction auditable instead of
    collapsing proof and heuristic into one indistinguishable boolean.

    Returns (is_merge, source) where source is "parents", "message", or "unknown".
    """
    parents = _safe_run(["git", "rev-list", "--parents", "-n", "1", commit_hash], cwd=cwd)
    if parents:
        # "<sha> <parent1> [<parent2> ...]" — 3+ fields means 2+ parents, so a merge.
        # ONE field is a root commit: zero parents, definitively not a merge. Requiring
        # two fields here sent root commits down the message path, which is both slower
        # and less certain than the answer git already gave.
        return len(parents.split()) > 2, "parents"
    if message:
        return is_merge_commit(message), "message"
    return False, "unknown"


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

    is_merge, source = _classify_merge(commit_hash, message, cwd)

    merges.append({
        "commit": commit_hash,
        "branch": branch,
        "author": author,
        "date": date,
        "message": message,
        "files_affected": files.split("\n") if files else [],
        "is_merge": is_merge,
        "merge_detection": source,
    })

    _write_memory(merges)


def classify(record: dict) -> bool:
    """Is this stored record a merge commit?

    Reads the tag written at capture time; for records stored before tagging existed
    (no "is_merge" key), falls back to the message heuristic so old rows classify the
    same way rather than silently reading as non-merges.
    """
    if not isinstance(record, dict):
        return False
    if "is_merge" in record:
        return bool(record["is_merge"])
    return is_merge_commit(record.get("message"))


def get_recent_merges(limit: int = 20, merges_only: Optional[bool] = None) -> list[dict]:
    """Get recent merge metadata. Returns empty list on error.

    merges_only=True  -> only records classified as merge commits
    merges_only=False -> only records classified as direct (non-merge) commits
    merges_only=None  -> everything (unchanged default; existing callers are unaffected)

    Filtering happens BEFORE the limit is applied, so `merges_only=True, limit=20` means
    twenty merges rather than however many merges happen to fall in the last twenty rows.
    """
    merges = _read_memory()
    if merges_only is not None:
        merges = [m for m in merges if classify(m) is bool(merges_only)]
    return merges[-limit:]


def stats() -> dict:
    """Return merge tracking stats."""
    merges = _read_memory()
    merge_commits = sum(1 for m in merges if classify(m))
    return {
        "total_tracked": len(merges),
        "merge_commits": merge_commits,
        "direct_commits": len(merges) - merge_commits,
        # How each verdict was reached, so proof and heuristic stay distinguishable.
        "detected_by": {
            source: sum(1 for m in merges if m.get("merge_detection") == source)
            for source in ("parents", "message", "unknown")
        },
        "max_capacity": MAX_STORED_MERGES,
        "memory_file": str(MERGED_DIFF_FILE),
        "file_exists": MERGED_DIFF_FILE.exists(),
    }


def invalidate() -> None:
    """Clear all tracked merges."""
    _write_memory([])
