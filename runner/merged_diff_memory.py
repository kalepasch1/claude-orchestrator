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

logger = logging.getLogger(__name__)

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
    """(commit_hash, commit_msg) for merges worth learning from in the last N days.

    Filtered, not raw. Every commit returned here goes on to
    `_extract_patterns_from_commit()`, which spends three git subprocesses plus a
    quality-gate pass on it — and a revert, a WIP merge, or a merge of a
    non-agent branch cannot yield a reusable convention, so that work buys a
    guaranteed rejection. The filter runs on the message alone, before any
    subprocess is spawned for the commit.

    Fail-soft: if the predicate module cannot be imported the scan still runs
    unfiltered, because losing the whole window is worse than scanning noise.
    """
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
        try:
            from merge_candidate import filter_merge_candidates
        except ImportError as e:
            _log_error(f"merge_candidate unavailable, scanning unfiltered: {e}", f"repo={repo}")
            return commits
        kept = filter_merge_candidates(commits)
        if len(kept) != len(commits):
            _log_error(
                f"merged-diff scan: {len(commits) - len(kept)} of {len(commits)} merges "
                f"skipped as non-candidates (reverts, WIP, non-agent branches)",
                f"repo={repo}",
            )
        return kept
    except Exception as e:
        _log_error(f"Failed to get merged commits: {e}", f"repo={repo}")
        return []


def _record_worth_keeping(pattern):
    """True when an extracted record has at least one changed file worth learning from.

    Mirrors `merge_candidate.is_merge_candidate_commit`'s path rule against the shape
    `_extract_patterns_from_commit` returns (which carries `files` but no raw diff).
    Fail-soft: an unimportable predicate keeps the record, because dropping real
    signal is worse than keeping noise.
    """
    if not isinstance(pattern, dict):
        return False
    try:
        from merge_candidate import is_ignored_path
    except ImportError:
        return True
    files = pattern.get("files")
    if not isinstance(files, (list, tuple)) or not files:
        return False
    return any(not is_ignored_path(f) for f in files)


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

        # FIXED 2026-08-11 — two stacked defects, the second masked by the first.
        #
        # (1) `quality_gate` grades a *distilled* convention list: it rejects
        #     anything without 2+ do/avoid bullet lines, anything over 4000 chars,
        #     anything that looks like a raw dump. It was being fed a raw commit
        #     message plus `git show --stat`, which is by definition a raw dump.
        #     Every commit was therefore rejected — measured: 447/447 over a
        #     14-day window, "fewer than 2 bullet lines" — so patterns_count was
        #     permanently 0, capture_to_memory permanently False, and the daily
        #     rollup permanently empty. The gate belongs on the extracted rules,
        #     which is what it was written to grade.
        #
        # (2) `learn_from_merges._extract_rules` and `._changed_files` do not
        #     exist on that module; those calls would have raised AttributeError
        #     into the `except` below. The helpers actually available are this
        #     module's own `_extract_rules` (defined just below, as the original
        #     comment already said) and `merged_diff_library._changed_files`.
        #     Unreachable while (1) held, so it never surfaced.
        from merged_diff_library import _changed_files, _frameworks
        rules = _extract_rules(full_text)
        frameworks = _frameworks(full_text)
        files = _changed_files(repo, f"{commit_hash}^", commit_hash)

        if not rules and not frameworks and not files:
            return None  # nothing learnable in this commit

        # Gate the distillation, not the raw commit. Only rules are graded;
        # frameworks and file lists are facts, not prose to be quality-checked.
        if rules:
            accepted, reason = learn_from_merges.quality_gate(
                "\n".join(f"- {r}" for r in rules), source=commit_hash)
            if not accepted:
                _log_error(f"quality gate rejected extracted rules: {reason}", commit_hash)
                rules = []

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
        # Read AND write under the same lock. The read used to sit outside it, so two
        # concurrent prunes could both load the same `lines`, each drop a different set,
        # and the second writer would resurrect the entries the first had just removed
        # (or drop entries the first had kept) — a lost-update on the index file.
        with _lock:
            with open(index_file, "r") as f:
                lines = f.readlines()

            kept = []
            for line in lines:
                # Try to extract date from line
                match = re.search(r"(\d{4})-(\d{2})-(\d{2})", line)
                if match:
                    try:
                        entry_date = datetime.strptime(
                            f"{match.group(1)}{match.group(2)}{match.group(3)}", "%Y%m%d").date()
                        if entry_date >= cutoff:
                            kept.append(line)
                    except Exception:
                        kept.append(line)  # keep if unparseable
                else:
                    kept.append(line)

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
    if dry_run:
        # FIXED 2026-08-11. The docstring above has always promised False for a
        # dry run, but the check below only asks whether `memory_file` is truthy
        # — and run() fills it with the string "[dry-run] would save N patterns",
        # which is truthy. So a dry run returned True: "a file was written" for a
        # mode whose entire purpose is writing nothing. Unreachable until the
        # pattern-extraction fix above, because patterns_count was always 0.
        run(repo=repo, dry_run=True)
        return False

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
        skipped_ignored = 0
        for commit_hash, msg in commits:
            p = _extract_patterns_from_commit(repo, commit_hash)
            if not p:
                continue
            # Record-level gate. The message filter above cannot see the diff, so a
            # merge whose every changed file is a lockfile, a vendored dependency or
            # build output still reaches here — and carries nothing reusable.
            if not _record_worth_keeping(p):
                skipped_ignored += 1
                continue
            patterns.append(p)
        if skipped_ignored:
            _log_error(
                f"merged-diff scan: {skipped_ignored} extracted commit(s) skipped — "
                f"no changed file outside the ignored set",
                f"repo={repo}",
            )

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
    """Get the most recent `limit` merge records. Returns [] on error.

    `merges[-limit:]` alone is wrong at the boundary: -0 == 0, so a limit of 0 sliced
    from the start and returned the WHOLE list — the opposite of "give me none" — and a
    negative limit silently became "all but the first N". `recent()` already clamps its
    limit; this one did not, so the same argument meant different things depending on
    which entry point a caller used. limit <= 0 now means no records.
    """
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 20
    if limit <= 0:
        return []
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

    # Per-diff byte cap (memory fix). Every record here holds the FULL text of a commit's
    # diff, and the whole list is held at once: one merge of a lockfile or a generated bundle
    # is tens of MB, and `limit` defaults to 50 of them. The caller regex-scans the text for
    # convention hints, so a bounded head of each diff answers the same question at a bounded
    # cost. 0 or negative disables the cap.
    try:
        max_diff_bytes = int(os.environ.get("ORCH_DIFF_RECENT_MAX_BYTES", str(256 * 1024)))
    except (TypeError, ValueError):
        max_diff_bytes = 256 * 1024

    records = []
    for sha in shas[:limit]:
        try:
            diff = _safe_run(["git", "show", "--format=%s", "--unified=0", sha], cwd=repo)
            if not diff:
                continue
            if 0 < max_diff_bytes < len(diff):
                diff = diff[:max_diff_bytes]
            records.append({
                "commit": sha,
                "date": _safe_run(["git", "log", "-1", "--format=%aI", sha], cwd=repo),
                "message": _safe_run(["git", "log", "-1", "--format=%s", sha], cwd=repo),
                "diff": diff,
            })
        except Exception:
            continue
    return records

# Matches the subject git writes for a merge: "Merge branch 'agent/foo' into bar",
# "Merge pull request #12 from org/agent/foo", and the plain "Merge agent/foo" form.
_MERGE_BRANCH_RE = re.compile(
    r"""Merge\s+(?:remote-tracking\s+)?branch\s+['"]([^'"]+)['"]"""
    r"""|Merge\s+pull\s+request\s+\#?\d+\s+from\s+(\S+)"""
    r"""|Merge\s+([^\s'"]+)""",
    re.IGNORECASE,
)


def _branch_from_subject(subject: str) -> str:
    """Best-effort source branch out of a merge subject. '' when it is not a merge."""
    m = _MERGE_BRANCH_RE.search(subject or "")
    if not m:
        return ""
    branch = next((g for g in m.groups() if g), "")
    # "org/agent/foo" from a PR subject -> "agent/foo"; keep plain names intact.
    if branch.startswith("origin/"):
        branch = branch[len("origin/"):]
    return branch.strip()


def _summarise(subject: str, branch: str, files: list) -> str:
    """One-line, dependency-free description of what a merge did.

    Heuristic on purpose. The spec allows an LLM call "if available", but this module
    is imported by the scheduler on every pass and has no model client; a per-merge
    network call would make a metadata read cost money and latency. The heuristic reads
    the same signals a summariser would (touched top-level areas, test-vs-source mix,
    breadth) and is deterministic, which also makes it testable.
    """
    paths = [p for p in (files or []) if p]
    if not paths:
        return f"{subject or 'merge'} — no files changed"
    areas = sorted({(p.split("/", 1)[0] if "/" in p else "(root)") for p in paths})
    tests = sum(1 for p in paths
                if "test" in os.path.basename(p).lower() or p.startswith("tests/")
                or "/tests/" in p)
    if tests == len(paths):
        nature = "tests only"
    elif tests:
        nature = f"{len(paths) - tests} source + {tests} test file(s)"
    else:
        nature = f"{len(paths)} source file(s)"
    where = ", ".join(areas[:3]) + ("…" if len(areas) > 3 else "")
    lead = subject or (f"merge of {branch}" if branch else "merge")
    return f"{lead} — {nature} under {where}"


def assemble_merge_summaries(limit: int = 20, repo: str = ".",
                             store: bool = False) -> list[dict]:
    """Recent merges as [{name, branch_name, files_changed, merge_date, summary}, …].

    This is the assembled shape the merged-diff-memory backlog asks for, in that exact
    key order and with no extra keys, newest first. It sits on the existing extractors
    (`_safe_run` git reads) rather than introducing a second git layer.

    `store=True` also persists the records through the existing metadata memory, so a
    caller can assemble and remember in one step; the memory schema is unchanged
    (commit/branch/author/date/message/files_affected) — this shape is a projection for
    consumers, not a new storage format.

    Fail-soft: returns [] rather than raising, because every caller of this module reads
    it inside a broad except and a raise would silently degrade to "no merges" anyway.
    """
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 20
    if limit <= 0:
        return []

    try:
        out = _safe_run(["git", "log", f"--max-count={limit}", "--merges", "--format=%H"],
                        cwd=repo)
        if not out:
            # Fast-forward-only repos have no merge commits; fall back to plain commits
            # so the assembled list is never empty just because of a merge strategy.
            out = _safe_run(["git", "log", f"--max-count={limit}", "--format=%H"], cwd=repo)
        shas = [s for s in out.split("\n") if s.strip()][:limit]
    except Exception:
        return []

    records = []
    for sha in shas:
        try:
            subject = _safe_run(["git", "log", "-1", "--format=%s", sha], cwd=repo)
            date = _safe_run(["git", "log", "-1", "--format=%aI", sha], cwd=repo)
            # `-m --first-parent` is required: for a MERGE commit, a plain diff-tree
            # prints nothing at all (git has no single parent to diff against), so
            # files_changed came back empty for every record — the exact field this
            # shape exists to carry. --first-parent diffs against the branch we merged
            # INTO, i.e. "what this merge brought in".
            raw = _safe_run(["git", "diff-tree", "--no-commit-id", "--name-only",
                             "-r", "-m", "--first-parent", sha], cwd=repo)
            files = [f for f in raw.split("\n") if f.strip()] if raw else []
            branch = _branch_from_subject(subject)
            records.append({
                "name": subject or sha[:12],
                "branch_name": branch,
                "files_changed": files,
                "merge_date": date,
                "summary": _summarise(subject, branch, files),
            })
        except Exception:
            continue

    if store and records:
        try:
            merges = _read_memory()
            known = {m.get("commit") for m in merges}
            for sha, rec in zip(shas, records):
                if sha in known:
                    continue
                merges.append({
                    "commit": sha,
                    "branch": rec["branch_name"],
                    "author": "",
                    "date": rec["merge_date"],
                    "message": rec["name"],
                    "files_affected": rec["files_changed"],
                })
            _write_memory(merges)
        except Exception:
            pass
    return records


def write_memory_file(merges: list[dict]) -> bool:
    """Persist merge metadata. True on success, False on any error.

    Public entry point for callers that need to know whether the write
    actually landed (e.g. before reporting a merge as recorded).
    """
    return _write_memory(merges)


def _invalidate_tracking() -> bool:
    """Clear all tracked merges (metadata file). True if the clear was persisted."""
    return _write_memory([])


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
        self._evictions = 0

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
            if key in self._entries:
                self._bytes -= reclaimed
                del self._entries[key]

            # RECLAIM BEFORE REFUSING (memory fix).
            #
            # The cap used to be enforced by refusing the write: once 50 MB of diffs had
            # accumulated the pool never accepted another entry and never gave a byte back.
            # TTL did not help — expiry was only ever checked in get_diff(), and only for the
            # one key being looked up, so a diff nobody asks for again is held for the life of
            # the process. In a long-running runner that is a permanently full cache holding
            # permanently stale content: worst case for both memory and hit rate.
            #
            # Now the cap evicts. Expired entries go first (they are dead weight by
            # definition), then the oldest live entries, until the new value fits.
            if self._bytes + size > CACHE_SIZE_BYTES:
                self._evict_expired_locked()
            if self._bytes + size > CACHE_SIZE_BYTES:
                self._evict_oldest_locked(size)
            if self._bytes + size > CACHE_SIZE_BYTES:
                return  # single entry larger than the whole cap — nothing to evict for

            self._entries[key] = (content, time.time(), size)
            self._bytes += size

    def _evict_expired_locked(self) -> None:
        """Drop every entry past its TTL. Caller holds the lock."""
        now = time.time()
        for key in [k for k, (_c, stored_at, _s) in self._entries.items()
                    if now - stored_at > CACHE_TTL]:
            self._bytes -= self._entries.pop(key)[2]
            self._evictions += 1

    def _evict_oldest_locked(self, needed: int) -> None:
        """Evict oldest-first until `needed` bytes fit under the cap. Caller holds the lock."""
        for key, _entry in sorted(self._entries.items(), key=lambda kv: kv[1][1]):
            if self._bytes + needed <= CACHE_SIZE_BYTES:
                return
            self._bytes -= self._entries.pop(key)[2]
            self._evictions += 1

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
                "evictions": self._evictions,
            }

    def invalidate(self) -> None:
        with self._lock:
            self._entries.clear()
            self._bytes = 0
            self._hits = 0
            self._misses = 0
            self._evictions = 0


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


def invalidate() -> bool:
    """Clear the diff cache AND tracked-merge metadata. Fail-soft, idempotent.

    Returns whether the metadata clear was persisted, preserving the bool
    contract callers on orchestrator/dev already depend on. Cache clearing is
    in-memory and cannot fail meaningfully, so it does not affect the result.
    """
    try:
        _pool.invalidate()
    except Exception:
        pass
    try:
        return _invalidate_tracking()
    except Exception:
        return False
