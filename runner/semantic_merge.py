"""
semantic_merge.py - AST-level 3-way merging for conflicting tasks.

Instead of serializing tasks that conflict_predictor flags as overlapping,
this module runs both concurrently and uses structural analysis to combine
their diffs.  For Python files it parses with the ast module to identify
function/class boundaries; for everything else it falls back to line-range
analysis.

Strategies (in descending confidence):
  disjoint          - diffs touch completely different files        (1.0)
  function_disjoint - same file, different functions/classes        (0.8)
  line_disjoint     - same function, non-overlapping line ranges   (0.6)
  overlapping       - overlapping lines in the same function       (unmergeable)

Thread-safe.  Fail-soft: any error -> mergeable=False / success=False
so the caller falls back to serialization.

Env vars:
  ORCH_SEMANTIC_MERGE_ENABLED              (default "true")
  ORCH_SEMANTIC_MERGE_CONFIDENCE_THRESHOLD (default "0.6")
"""

import sys, os, re, ast, json, time, threading, subprocess, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import log as _log_mod

_log = _log_mod.get("semantic_merge")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_ENABLED = os.environ.get("ORCH_SEMANTIC_MERGE_ENABLED", "true").lower() in (
    "true", "1", "yes",
)
_CONFIDENCE_THRESHOLD = float(
    os.environ.get("ORCH_SEMANTIC_MERGE_CONFIDENCE_THRESHOLD", "0.6")
)

# ---------------------------------------------------------------------------
# Stats (thread-safe)
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_stats = {
    "merges_attempted": 0,
    "merges_succeeded": 0,
    "conflicts_avoided": 0,
    "time_saved_s": 0.0,
}


def stats() -> dict:
    """Return a snapshot of merge statistics."""
    with _lock:
        return dict(_stats)


def _inc(key, value=1):
    with _lock:
        _stats[key] = _stats.get(key, 0) + value


# ---------------------------------------------------------------------------
# Diff parsing
# ---------------------------------------------------------------------------

_DIFF_FILE_RE = re.compile(r"^diff --git a/(.+?) b/(.+?)$", re.MULTILINE)
_HUNK_HEADER_RE = re.compile(
    r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$", re.MULTILINE,
)


def _parse_diff_hunks(diff_text: str) -> list:
    """Parse unified diff into structured hunks.

    Returns list of dicts:
      {"file", "old_start", "old_count", "new_start", "new_count", "content"}
    """
    if not diff_text:
        return []

    hunks = []
    current_file = None

    for line in diff_text.splitlines(keepends=True):
        stripped = line.rstrip("\n")

        file_match = _DIFF_FILE_RE.match(stripped)
        if file_match:
            current_file = file_match.group(2)
            continue

        hunk_match = _HUNK_HEADER_RE.match(stripped)
        if hunk_match:
            hunks.append({
                "file": current_file or "",
                "old_start": int(hunk_match.group(1)),
                "old_count": int(hunk_match.group(2) or 1),
                "new_start": int(hunk_match.group(3)),
                "new_count": int(hunk_match.group(4) or 1),
                "content": "",
            })
            continue

        if hunks:
            hunks[-1]["content"] += line

    return hunks


# ---------------------------------------------------------------------------
# Python AST helpers
# ---------------------------------------------------------------------------


def _python_function_boundaries(file_path: str) -> list:
    """Use ast module to map function/class line ranges in a Python file.

    Returns list of dicts:
      {"name", "start_line", "end_line", "type": "function"|"class"}
    """
    try:
        with open(file_path, "r", errors="replace") as fh:
            source = fh.read()
    except (FileNotFoundError, PermissionError, OSError):
        return []

    try:
        tree = ast.parse(source, filename=file_path)
    except SyntaxError:
        return []

    boundaries = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            boundaries.append({
                "name": node.name,
                "start_line": node.lineno,
                "end_line": node.end_lineno or node.lineno,
                "type": "function",
            })
        elif isinstance(node, ast.ClassDef):
            boundaries.append({
                "name": node.name,
                "start_line": node.lineno,
                "end_line": node.end_lineno or node.lineno,
                "type": "class",
            })

    boundaries.sort(key=lambda b: b["start_line"])
    return boundaries


def _find_containing_boundary(boundaries, line):
    """Return the boundary dict that contains *line*, or None."""
    for b in boundaries:
        if b["start_line"] <= line <= b["end_line"]:
            return b
    return None


# ---------------------------------------------------------------------------
# Overlap analysis helpers
# ---------------------------------------------------------------------------


def _ranges_overlap(s1, c1, s2, c2):
    """Return True if line ranges [s1, s1+c1) and [s2, s2+c2) overlap."""
    return s1 < s2 + c2 and s2 < s1 + c1


def _files_touched(hunks):
    """Return set of files modified by a list of hunks."""
    return {h["file"] for h in hunks}


# ---------------------------------------------------------------------------
# can_semantic_merge
# ---------------------------------------------------------------------------


def can_semantic_merge(diff_a: str, diff_b: str, repo_path: str) -> dict:
    """Analyse two diffs and determine whether they can be semantically merged.

    Parameters
    ----------
    diff_a : str      Unified diff text from task A.
    diff_b : str      Unified diff text from task B.
    repo_path : str   Absolute path to the repository root (used to read
                      Python files for AST analysis).

    Returns
    -------
    dict  {"mergeable": bool, "confidence": float,
           "conflicts": list, "strategy": str}
    """
    fail = {"mergeable": False, "confidence": 0.0, "conflicts": [], "strategy": "error"}

    if not _ENABLED:
        return {**fail, "strategy": "disabled"}

    try:
        hunks_a = _parse_diff_hunks(diff_a)
        hunks_b = _parse_diff_hunks(diff_b)

        if not hunks_a or not hunks_b:
            return {**fail, "strategy": "empty_diff"}

        files_a = _files_touched(hunks_a)
        files_b = _files_touched(hunks_b)
        common_files = files_a & files_b

        # ------ completely different files ------
        if not common_files:
            return {
                "mergeable": True,
                "confidence": 1.0,
                "conflicts": [],
                "strategy": "disjoint",
            }

        # ------ same file(s): deeper analysis ------
        conflicts = []
        min_confidence = 1.0

        for fname in common_files:
            fhunks_a = [h for h in hunks_a if h["file"] == fname]
            fhunks_b = [h for h in hunks_b if h["file"] == fname]

            # Try Python AST analysis
            full_path = os.path.join(repo_path, fname) if repo_path else fname
            boundaries = []
            if fname.endswith(".py") and os.path.isfile(full_path):
                boundaries = _python_function_boundaries(full_path)

            if boundaries:
                # Function-level analysis
                funcs_a = set()
                funcs_b = set()
                for h in fhunks_a:
                    for line in range(h["old_start"],
                                     h["old_start"] + h["old_count"]):
                        b = _find_containing_boundary(boundaries, line)
                        if b:
                            funcs_a.add(b["name"])
                for h in fhunks_b:
                    for line in range(h["old_start"],
                                     h["old_start"] + h["old_count"]):
                        b = _find_containing_boundary(boundaries, line)
                        if b:
                            funcs_b.add(b["name"])

                common_funcs = funcs_a & funcs_b
                if not common_funcs:
                    # Same file, different functions
                    min_confidence = min(min_confidence, 0.8)
                    continue

                # Same function — check line ranges
                for func_name in common_funcs:
                    func_hunks_a = [
                        h for h in fhunks_a
                        if (_find_containing_boundary(boundaries, h["old_start"])
                            or {}).get("name") == func_name
                    ]
                    func_hunks_b = [
                        h for h in fhunks_b
                        if (_find_containing_boundary(boundaries, h["old_start"])
                            or {}).get("name") == func_name
                    ]

                    overlap = False
                    for ha in func_hunks_a:
                        for hb in func_hunks_b:
                            if _ranges_overlap(
                                ha["old_start"], ha["old_count"],
                                hb["old_start"], hb["old_count"],
                            ):
                                overlap = True
                                conflicts.append({
                                    "file": fname,
                                    "function": func_name,
                                    "a_range": (
                                        f"{ha['old_start']}-"
                                        f"{ha['old_start'] + ha['old_count']}"
                                    ),
                                    "b_range": (
                                        f"{hb['old_start']}-"
                                        f"{hb['old_start'] + hb['old_count']}"
                                    ),
                                })

                    if overlap:
                        return {
                            "mergeable": False,
                            "confidence": 0.0,
                            "conflicts": conflicts,
                            "strategy": "overlapping",
                        }

                    min_confidence = min(min_confidence, 0.6)
            else:
                # Non-Python or no AST: line-range analysis only
                overlap = False
                for ha in fhunks_a:
                    for hb in fhunks_b:
                        if _ranges_overlap(
                            ha["old_start"], ha["old_count"],
                            hb["old_start"], hb["old_count"],
                        ):
                            overlap = True
                            conflicts.append({
                                "file": fname,
                                "a_range": (
                                    f"{ha['old_start']}-"
                                    f"{ha['old_start'] + ha['old_count']}"
                                ),
                                "b_range": (
                                    f"{hb['old_start']}-"
                                    f"{hb['old_start'] + hb['old_count']}"
                                ),
                            })

                if overlap:
                    return {
                        "mergeable": False,
                        "confidence": 0.0,
                        "conflicts": conflicts,
                        "strategy": "overlapping",
                    }

                # Same file, non-overlapping lines (no AST info)
                min_confidence = min(min_confidence, 0.6)

        # Determine strategy name from confidence level
        if min_confidence >= 1.0:
            strategy = "disjoint"
        elif min_confidence >= 0.8:
            strategy = "function_disjoint"
        else:
            strategy = "line_disjoint"

        mergeable = min_confidence >= _CONFIDENCE_THRESHOLD
        return {
            "mergeable": mergeable,
            "confidence": min_confidence,
            "conflicts": conflicts,
            "strategy": strategy,
        }

    except Exception as exc:
        _log.warning("can_semantic_merge failed: %s", exc)
        return fail


# ---------------------------------------------------------------------------
# Diff reconstruction
# ---------------------------------------------------------------------------


def _reconstruct_diff(hunks):
    """Reconstruct a unified diff string from a list of parsed hunks."""
    if not hunks:
        return ""

    lines = []
    current_file = None
    for h in hunks:
        if h["file"] != current_file:
            current_file = h["file"]
            lines.append(f"diff --git a/{current_file} b/{current_file}")
            lines.append(f"--- a/{current_file}")
            lines.append(f"+++ b/{current_file}")
        lines.append(
            f"@@ -{h['old_start']},{h['old_count']} "
            f"+{h['new_start']},{h['new_count']} @@"
        )
        content = h["content"].rstrip("\n")
        if content:
            lines.append(content)

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Function-level merge fallback
# ---------------------------------------------------------------------------


def _try_function_merge(diff_a, diff_b, wt_path, base_branch, repo_path, t0):
    """Fallback: split diffs into per-function hunks, apply non-overlapping."""
    fail = {"success": False, "merged_diff": "", "strategy_used": "none",
            "files_merged": 0}

    try:
        hunks_a = _parse_diff_hunks(diff_a)
        hunks_b = _parse_diff_hunks(diff_b)

        # Identify non-overlapping hunks from diff_b
        non_overlapping_b = []
        for hb in hunks_b:
            overlap = False
            for ha in hunks_a:
                if ha["file"] == hb["file"] and _ranges_overlap(
                    ha["old_start"], ha["old_count"],
                    hb["old_start"], hb["old_count"],
                ):
                    overlap = True
                    break
            if not overlap:
                non_overlapping_b.append(hb)

        if not non_overlapping_b:
            return fail

        # Reset worktree and apply diff_a fully
        subprocess.run(
            ["git", "checkout", base_branch, "--", "."],
            cwd=wt_path, capture_output=True, timeout=30,
        )
        ra = subprocess.run(
            ["git", "apply"],
            input=diff_a, cwd=wt_path, capture_output=True, text=True,
            timeout=60,
        )
        if ra.returncode != 0:
            return fail

        # Build partial diff from non-overlapping hunks of diff_b
        partial_diff = _reconstruct_diff(non_overlapping_b)
        if not partial_diff:
            return fail

        rb = subprocess.run(
            ["git", "apply"],
            input=partial_diff, cwd=wt_path, capture_output=True, text=True,
            timeout=60,
        )
        if rb.returncode != 0:
            return fail

        # Generate combined diff
        combined = subprocess.run(
            ["git", "diff", base_branch],
            cwd=wt_path, capture_output=True, text=True, timeout=30,
        )

        files_merged = len(
            _files_touched(hunks_a)
            | {h["file"] for h in non_overlapping_b}
        )

        elapsed = time.monotonic() - t0
        _inc("merges_succeeded")
        _inc("conflicts_avoided")
        _inc("time_saved_s", elapsed)

        return {
            "success": True,
            "merged_diff": combined.stdout,
            "strategy_used": "function_level",
            "files_merged": files_merged,
        }

    except Exception as exc:
        _log.warning("function-level merge failed: %s", exc)
        return fail


# ---------------------------------------------------------------------------
# merge_diffs
# ---------------------------------------------------------------------------


def merge_diffs(diff_a: str, diff_b: str, repo_path: str,
                base_branch: str) -> dict:
    """Apply two diffs onto *base_branch* and return a combined diff.

    Tries ``git apply --3way`` first; on failure attempts function-level
    merge for non-overlapping hunks.

    Parameters
    ----------
    diff_a : str         Unified diff from task A.
    diff_b : str         Unified diff from task B.
    repo_path : str      Repository root.
    base_branch : str    Branch both diffs are relative to.

    Returns
    -------
    dict  {"success": bool, "merged_diff": str,
           "strategy_used": str, "files_merged": int}
    """
    fail = {"success": False, "merged_diff": "", "strategy_used": "none",
            "files_merged": 0}

    if not _ENABLED:
        return fail

    _inc("merges_attempted")
    t0 = time.monotonic()

    try:
        with tempfile.TemporaryDirectory(prefix="sem_merge_") as tmpdir:
            wt_path = os.path.join(tmpdir, "worktree")

            r = subprocess.run(
                ["git", "worktree", "add", "--detach", wt_path, base_branch],
                cwd=repo_path, capture_output=True, text=True, timeout=60,
            )
            if r.returncode != 0:
                _log.warning("git worktree add failed: %s", r.stderr.strip())
                return fail

            try:
                # Apply diff_a
                ra = subprocess.run(
                    ["git", "apply", "--3way"],
                    input=diff_a, cwd=wt_path, capture_output=True, text=True,
                    timeout=60,
                )
                if ra.returncode != 0:
                    _log.debug("diff_a apply failed: %s", ra.stderr.strip())
                    return _try_function_merge(
                        diff_a, diff_b, wt_path, base_branch, repo_path, t0,
                    )

                # Apply diff_b
                rb = subprocess.run(
                    ["git", "apply", "--3way"],
                    input=diff_b, cwd=wt_path, capture_output=True, text=True,
                    timeout=60,
                )
                if rb.returncode != 0:
                    _log.debug("diff_b apply failed: %s", rb.stderr.strip())
                    return _try_function_merge(
                        diff_a, diff_b, wt_path, base_branch, repo_path, t0,
                    )

                # Both applied cleanly — generate combined diff
                combined = subprocess.run(
                    ["git", "diff", base_branch],
                    cwd=wt_path, capture_output=True, text=True, timeout=30,
                )

                files_merged = len(
                    _files_touched(_parse_diff_hunks(diff_a))
                    | _files_touched(_parse_diff_hunks(diff_b))
                )

                elapsed = time.monotonic() - t0
                _inc("merges_succeeded")
                _inc("conflicts_avoided")
                _inc("time_saved_s", elapsed)

                return {
                    "success": True,
                    "merged_diff": combined.stdout,
                    "strategy_used": "git_apply_3way",
                    "files_merged": files_merged,
                }
            finally:
                subprocess.run(
                    ["git", "worktree", "remove", "--force", wt_path],
                    cwd=repo_path, capture_output=True, timeout=30,
                )

    except Exception as exc:
        _log.warning("merge_diffs failed: %s", exc)
        return fail


# ---------------------------------------------------------------------------
# Concurrent orchestration
# ---------------------------------------------------------------------------


def orchestrate_concurrent(task_a, task_b, repo_path: str,
                           base_branch: str, test_cmd: str) -> dict:
    """Run two conflicting tasks concurrently and attempt semantic merge.

    *task_a* and *task_b* are callables that return a dict with at least
    ``{"diff": str, "branch": str, "task_id": str}``.

    After both finish, attempts semantic merge.  If the merge succeeds and
    ``test_cmd`` passes on the merged result, returns success with the
    merged branch.  Otherwise falls back to serialization (task_a kept,
    task_b re-queued).

    Parameters
    ----------
    task_a : callable    Returns {"diff", "branch", "task_id"}.
    task_b : callable    Returns {"diff", "branch", "task_id"}.
    repo_path : str      Repository root.
    base_branch : str    Common ancestor branch.
    test_cmd : str       Shell command to validate the merged result.

    Returns
    -------
    dict  {"success": bool, "merged_branch": str, "tasks_merged": list}
    """
    fail = {"success": False, "merged_branch": "", "tasks_merged": []}

    if not _ENABLED:
        return fail

    try:
        results = {}

        def _run(key, task):
            try:
                results[key] = task()
            except Exception as exc:
                _log.warning("task %s failed: %s", key, exc)
                results[key] = None

        thread_a = threading.Thread(target=_run, args=("a", task_a), daemon=True)
        thread_b = threading.Thread(target=_run, args=("b", task_b), daemon=True)
        thread_a.start()
        thread_b.start()
        thread_a.join()
        thread_b.join()

        res_a = results.get("a")
        res_b = results.get("b")

        if not res_a or not res_b:
            _log.info("one or both tasks returned no result; falling back")
            return fail

        diff_a = res_a.get("diff", "")
        diff_b = res_b.get("diff", "")

        if not diff_a or not diff_b:
            return fail

        # Check mergeability
        analysis = can_semantic_merge(diff_a, diff_b, repo_path)
        if not analysis["mergeable"]:
            _log.info(
                "diffs not mergeable (strategy=%s); falling back",
                analysis["strategy"],
            )
            return fail

        # Attempt merge
        merge_result = merge_diffs(diff_a, diff_b, repo_path, base_branch)
        if not merge_result["success"]:
            return fail

        # Apply merged diff to a new branch and run tests
        merged_branch = f"agent/merged-{int(time.time())}"
        try:
            subprocess.run(
                ["git", "checkout", "-b", merged_branch, base_branch],
                cwd=repo_path, capture_output=True, text=True, timeout=30,
                check=True,
            )
            subprocess.run(
                ["git", "apply"],
                input=merge_result["merged_diff"],
                cwd=repo_path, capture_output=True, text=True, timeout=60,
                check=True,
            )
            subprocess.run(
                ["git", "add", "-A"],
                cwd=repo_path, capture_output=True, timeout=15,
            )
            subprocess.run(
                ["git", "commit", "-m",
                 f"semantic merge: "
                 f"{res_a.get('task_id', '?')} + {res_b.get('task_id', '?')}"],
                cwd=repo_path, capture_output=True, text=True, timeout=30,
            )
        except subprocess.CalledProcessError as exc:
            _log.warning("branch creation / apply failed: %s", exc)
            return fail

        # Run tests
        test_result = subprocess.run(
            test_cmd, cwd=repo_path, shell=True,
            capture_output=True, text=True, timeout=300,
        )

        if test_result.returncode != 0:
            _log.info("tests failed on merged branch; falling back")
            subprocess.run(
                ["git", "checkout", base_branch],
                cwd=repo_path, capture_output=True, timeout=15,
            )
            subprocess.run(
                ["git", "branch", "-D", merged_branch],
                cwd=repo_path, capture_output=True, timeout=15,
            )
            return fail

        return {
            "success": True,
            "merged_branch": merged_branch,
            "tasks_merged": [
                res_a.get("task_id", "a"),
                res_b.get("task_id", "b"),
            ],
        }

    except Exception as exc:
        _log.warning("orchestrate_concurrent failed: %s", exc)
        return fail
