#!/usr/bin/env python3
"""
pattern_compiler.py — mines merge history for repeatable task patterns and
compiles them into zero-token deterministic scripts.

When a queued task matches a compiled pattern, the runner can skip the
expensive model call entirely and replay the proven diff instead.

Usage:
    import pattern_compiler

    # Periodic daemon call to refresh patterns from merge history
    pattern_compiler.compile_patterns()

    # Before claiming a model slot for a task
    m = pattern_compiler.match(task)
    if m and m["confidence"] >= 0.7:
        result = pattern_compiler.execute(m, worktree_path, task["id"])

    # Observability
    pattern_compiler.stats()

Env vars:
    ORCH_PATTERN_COMPILER_ENABLED  – master switch (default "true")
    ORCH_PATTERN_MIN_MERGES        – min merges to form a pattern (default 3)
    ORCH_PATTERN_MAX               – max compiled patterns in memory (default 100)
    ORCH_PATTERN_TTL_S             – cache TTL in seconds (default 600)
    ORCH_PATTERN_MIN_CONFIDENCE    – match threshold (default 0.6)
"""
import sys, os, json, time, threading, re, hashlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import log as _log_mod
import db

_log = _log_mod.get("pattern_compiler")

# ---------------------------------------------------------------------------
# Configuration (env-var gated with sensible defaults)
# ---------------------------------------------------------------------------
ENABLED         = os.environ.get("ORCH_PATTERN_COMPILER_ENABLED", "true").lower() == "true"
MIN_MERGES      = int(os.environ.get("ORCH_PATTERN_MIN_MERGES", "3"))
MAX_PATTERNS    = int(os.environ.get("ORCH_PATTERN_MAX", "100"))
CACHE_TTL       = int(os.environ.get("ORCH_PATTERN_TTL_S", "600"))
MIN_CONFIDENCE  = float(os.environ.get("ORCH_PATTERN_MIN_CONFIDENCE", "0.6"))
MIN_SUCCESS_RATE = 0.5  # auto-disable patterns below this


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _slugify_prefix(slug):
    """Extract the prefix pattern from a slug.

    Everything before the last hyphenated segment if that segment is numeric,
    or the full slug otherwise.  "add-field-42" -> "add-field-",
    "fix-lint-warnings" -> "fix-lint-warnings".
    """
    try:
        slug = str(slug or "")
        parts = slug.rsplit("-", 1)
        if len(parts) == 2 and parts[1].isdigit():
            return parts[0] + "-"
        return slug
    except Exception:
        return str(slug or "")


def _keywords(text):
    """Extract lowercase alpha-numeric keywords (4+ chars) from text."""
    try:
        return set(re.findall(r"[a-z0-9_]{4,}", str(text or "").lower()))
    except Exception:
        return set()


def _pattern_id(prefix, keywords_frozen):
    """Deterministic hash for a pattern."""
    raw = f"{prefix}|{','.join(sorted(keywords_frozen))}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _extract_pattern(outcomes_group):
    """Find common diff structure across 3+ merged outcomes.

    Returns a pattern dict or None if no usable pattern emerges.
    """
    try:
        if len(outcomes_group) < MIN_MERGES:
            return None

        # Collect diffs/summaries from the group
        diffs = []
        all_keywords = []
        files_sets = []
        for o in outcomes_group:
            diff_text = str(o.get("diff") or o.get("summary") or "")
            if diff_text:
                diffs.append(diff_text)
            all_keywords.append(_keywords(o.get("prompt") or o.get("slug") or ""))
            files_raw = o.get("files_changed") or o.get("files") or ""
            if isinstance(files_raw, str):
                files_sets.append(set(files_raw.split(",")) if files_raw else set())
            elif isinstance(files_raw, list):
                files_sets.append(set(files_raw))

        if not diffs:
            return None

        # Find common keywords across all outcomes
        common_kw = set.intersection(*all_keywords) if all_keywords else set()

        # Find common file patterns
        common_files = set.intersection(*files_sets) if files_sets and all(files_sets) else set()

        # Use the most recent diff as the template (best signal)
        template_diff = diffs[-1]

        # Success rate from the group
        successes = sum(1 for o in outcomes_group
                        if o.get("state") == "DONE" or o.get("integrated"))
        success_rate = successes / len(outcomes_group) if outcomes_group else 0

        return {
            "template_diff": template_diff[:30000],  # bound memory
            "common_keywords": common_kw,
            "common_files": sorted(common_files)[:50],
            "example_count": len(outcomes_group),
            "success_rate": round(success_rate, 3),
        }
    except Exception as exc:
        _log.debug("_extract_pattern failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Singleton compiler state
# ---------------------------------------------------------------------------

class _PatternCache:
    """Thread-safe compiled-pattern cache with TTL and bounded size."""

    def __init__(self):
        self._lock = threading.Lock()
        self._patterns = {}        # pattern_id -> {prefix, keywords, pattern, compiled_at}
        self._compiled_at = 0.0
        self._total_matches = 0
        self._total_executions = 0
        self._total_successes = 0

    # -- compile ----------------------------------------------------------

    def compile_patterns(self):
        """Query outcomes, group by slug prefix, compile repeatable patterns.

        Returns count of patterns compiled.
        """
        if not ENABLED:
            return 0

        now = time.time()
        if now - self._compiled_at < CACHE_TTL:
            with self._lock:
                return len(self._patterns)

        try:
            rows = db.select("outcomes", {
                "select": "id,slug,prompt,diff,summary,state,integrated,files_changed,files",
                "or": "(state.eq.DONE,integrated.eq.true)",
                "order": "created_at.desc",
                "limit": "500",
            }) or []
        except Exception as exc:
            _log.debug("compile_patterns: db query failed: %s", exc)
            return 0

        if not rows:
            return 0

        # Group by slug prefix
        groups = {}
        for row in rows:
            prefix = _slugify_prefix(row.get("slug"))
            groups.setdefault(prefix, []).append(row)

        compiled = {}
        for prefix, group in groups.items():
            if len(group) < MIN_MERGES:
                continue

            pattern = _extract_pattern(group)
            if not pattern:
                continue

            # Skip patterns with poor historical success
            if pattern["success_rate"] < MIN_SUCCESS_RATE:
                _log.debug("skipping low-success pattern %s (%.1f%%)",
                           prefix, pattern["success_rate"] * 100)
                continue

            kw = pattern["common_keywords"]
            pid = _pattern_id(prefix, kw)
            compiled[pid] = {
                "pattern_id": pid,
                "prefix": prefix,
                "keywords": kw,
                "pattern": pattern,
                "compiled_at": now,
            }

            if len(compiled) >= MAX_PATTERNS:
                break

        with self._lock:
            self._patterns = compiled
            self._compiled_at = now

        count = len(compiled)
        _log.debug("compiled %d patterns from %d outcome rows", count, len(rows))
        return count

    # -- match ------------------------------------------------------------

    def match(self, task):
        """Check if a task matches any compiled pattern.

        Returns {"pattern_id": str, "confidence": float, "script": str} or None.
        """
        if not ENABLED:
            return None
        if not task:
            return None

        with self._lock:
            patterns = dict(self._patterns)

        if not patterns:
            return None

        task_slug = str(task.get("slug") or "")
        task_prefix = _slugify_prefix(task_slug)
        task_kw = _keywords(task.get("prompt") or task.get("slug") or "")

        best = None
        best_conf = 0.0

        for pid, entry in patterns.items():
            try:
                p_prefix = entry["prefix"]
                p_kw = entry["keywords"]
                p_pattern = entry["pattern"]

                # Slug prefix match (0 or 1)
                slug_match = 1.0 if (task_prefix == p_prefix or
                                     task_slug.startswith(p_prefix)) else 0.0

                # Keyword overlap (Jaccard-ish)
                if p_kw and task_kw:
                    overlap = len(task_kw & p_kw)
                    union = len(task_kw | p_kw)
                    keyword_overlap = overlap / union if union else 0.0
                else:
                    keyword_overlap = 0.0

                # Historical success rate from pattern
                success_rate = p_pattern.get("success_rate", 0.5)

                # Weighted confidence
                confidence = (keyword_overlap * 0.4 +
                              slug_match * 0.3 +
                              success_rate * 0.3)

                if confidence > best_conf and confidence >= MIN_CONFIDENCE:
                    best_conf = confidence
                    best = {
                        "pattern_id": pid,
                        "confidence": round(confidence, 4),
                        "script": p_pattern.get("template_diff", ""),
                        "prefix": p_prefix,
                        "files": p_pattern.get("common_files", []),
                    }
            except Exception as exc:
                _log.debug("match scoring failed for %s: %s", pid, exc)
                continue

        if best:
            with self._lock:
                self._total_matches += 1
            _log.debug("matched pattern %s (conf=%.3f) for slug %s",
                       best["pattern_id"], best["confidence"], task_slug)

        return best

    # -- execute ----------------------------------------------------------

    def execute(self, match_result, worktree_path, task_id):
        """Apply a compiled pattern's diff to a worktree.

        Returns {"success": bool, "files_changed": int, "method": str}.
        Never raises.
        """
        if not ENABLED:
            return {"success": False, "files_changed": 0, "method": "pattern-replay"}
        if not match_result or not worktree_path:
            return {"success": False, "files_changed": 0, "method": "pattern-replay"}

        try:
            import subprocess

            script = match_result.get("script", "")
            if not script.strip():
                return {"success": False, "files_changed": 0, "method": "pattern-replay"}

            pid = match_result.get("pattern_id", "unknown")
            _log.debug("executing pattern %s on task %s at %s", pid, task_id, worktree_path)

            # Write patch to temp file and apply
            patch_path = os.path.join(worktree_path, f".pattern-{pid}.patch")
            try:
                with open(patch_path, "w") as f:
                    f.write(script)

                result = subprocess.run(
                    ["git", "apply", "--check", patch_path],
                    cwd=worktree_path,
                    capture_output=True, text=True, timeout=30,
                )

                if result.returncode != 0:
                    _log.debug("pattern %s patch --check failed: %s", pid, result.stderr[:200])
                    with self._lock:
                        self._total_executions += 1
                    return {"success": False, "files_changed": 0, "method": "pattern-replay"}

                # Apply for real
                result = subprocess.run(
                    ["git", "apply", patch_path],
                    cwd=worktree_path,
                    capture_output=True, text=True, timeout=30,
                )

                if result.returncode != 0:
                    _log.debug("pattern %s apply failed: %s", pid, result.stderr[:200])
                    with self._lock:
                        self._total_executions += 1
                    return {"success": False, "files_changed": 0, "method": "pattern-replay"}

                # Count changed files
                changed = subprocess.run(
                    ["git", "diff", "--name-only"],
                    cwd=worktree_path,
                    capture_output=True, text=True, timeout=10,
                )
                files_changed = len([l for l in changed.stdout.splitlines() if l.strip()])

                with self._lock:
                    self._total_executions += 1
                    self._total_successes += 1

                _log.debug("pattern %s applied successfully (%d files)", pid, files_changed)
                return {
                    "success": True,
                    "files_changed": files_changed,
                    "method": "pattern-replay",
                }

            finally:
                # Clean up temp patch file
                try:
                    os.unlink(patch_path)
                except OSError:
                    pass

        except Exception as exc:
            _log.debug("pattern execute failed: %s", exc)
            with self._lock:
                self._total_executions += 1
            return {"success": False, "files_changed": 0, "method": "pattern-replay"}

    # -- stats ------------------------------------------------------------

    def stats(self):
        """Return observability counters."""
        with self._lock:
            execs = self._total_executions
            successes = self._total_successes
            return {
                "patterns_compiled": len(self._patterns),
                "total_matches": self._total_matches,
                "total_executions": execs,
                "success_rate": round(successes / execs, 3) if execs else 0.0,
            }


# ---------------------------------------------------------------------------
# Module-level singleton + delegating functions
# ---------------------------------------------------------------------------
_cache = _PatternCache()


def compile_patterns():
    """Refresh compiled patterns from merge history. Returns count compiled."""
    try:
        return _cache.compile_patterns()
    except Exception as exc:
        _log.debug("compile_patterns top-level error: %s", exc)
        return 0


def match(task):
    """Check if a task matches a compiled pattern. Returns match dict or None."""
    try:
        return _cache.match(task)
    except Exception as exc:
        _log.debug("match top-level error: %s", exc)
        return None


def execute(match_result, worktree_path, task_id):
    """Apply a compiled pattern to a worktree. Never raises."""
    try:
        return _cache.execute(match_result, worktree_path, task_id)
    except Exception as exc:
        _log.debug("execute top-level error: %s", exc)
        return {"success": False, "files_changed": 0, "method": "pattern-replay"}


def stats():
    """Return {"patterns_compiled", "total_matches", "total_executions", "success_rate"}."""
    try:
        return _cache.stats()
    except Exception:
        return {"patterns_compiled": 0, "total_matches": 0,
                "total_executions": 0, "success_rate": 0.0}
