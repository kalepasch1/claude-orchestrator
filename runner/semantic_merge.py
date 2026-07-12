"""
semantic_merge -- AST-level semantic merging for Python files.

When two concurrent tasks edit the same file, instead of serializing (deferring
one), this module attempts a 3-way semantic merge using AST analysis.  It splits
Python files into "semantic regions" (imports, top-level function/class defs,
module-level statements between defs) and determines whether two diffs touch
different regions.  Non-overlapping diffs merge automatically; overlapping diffs
fall back to serial merge.

For non-Python files, a simpler line-based heuristic is used: diffs are
non-overlapping if they touch entirely different line ranges.

Env vars
--------
ORCH_SEMANTIC_MERGE          "true" (default) / "false"
ORCH_MERGE_CONFIDENCE_MIN    0.0-1.0 (default "0.8")
"""

import sys, os, ast, re, threading, time, difflib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import log as _log_mod

_log = _log_mod.get("semantic_merge")

# ---------------------------------------------------------------------------
# env config
# ---------------------------------------------------------------------------

_ENABLED = os.environ.get("ORCH_SEMANTIC_MERGE", "true").lower() == "true"
_CONFIDENCE_MIN = float(os.environ.get("ORCH_MERGE_CONFIDENCE_MIN", "0.8"))

# ---------------------------------------------------------------------------
# stats tracking (thread-safe)
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_stats = {
    "auto_merges": 0,
    "deferrals": 0,
    "errors": 0,
    "by_strategy": {},        # strategy -> count
    "by_filepath": {},        # filepath -> {"auto": N, "deferred": N}
}


# ---------------------------------------------------------------------------
# semantic region extraction
# ---------------------------------------------------------------------------

class _Region:
    """A contiguous semantic region within a Python file."""
    __slots__ = ("kind", "name", "start", "end")

    def __init__(self, kind, name, start, end):
        self.kind = kind      # "import", "class", "function", "module_stmt"
        self.name = name      # e.g. "MyClass", "my_func", "imports", "stmt_L42"
        self.start = start    # 1-based first line
        self.end = end        # 1-based last line

    def __repr__(self):
        return f"Region({self.kind}:{self.name} L{self.start}-{self.end})"


def _extract_regions(source):
    """Parse Python source into semantic regions.

    Returns a list of _Region covering every line in the file. On parse
    failure returns an empty list (caller should fall back to line heuristic).
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    lines = source.splitlines()
    total_lines = len(lines)
    if total_lines == 0:
        return []

    # Collect top-level nodes with line spans
    nodes = []
    for node in ast.iter_child_nodes(tree):
        if not hasattr(node, "lineno"):
            continue
        end_line = getattr(node, "end_lineno", node.lineno)
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            nodes.append(("import", "imports", node.lineno, end_line))
        elif isinstance(node, ast.ClassDef):
            nodes.append(("class", node.name, node.lineno, end_line))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            nodes.append(("function", node.name, node.lineno, end_line))
        else:
            nodes.append(("module_stmt", f"stmt_L{node.lineno}", node.lineno, end_line))

    if not nodes:
        return [_Region("module_stmt", "entire_file", 1, total_lines)]

    # Sort by start line
    nodes.sort(key=lambda n: n[2])

    # Merge consecutive imports into one region
    merged = []
    for kind, name, start, end in nodes:
        if kind == "import" and merged and merged[-1][0] == "import":
            # Extend previous import region
            merged[-1] = ("import", "imports", merged[-1][2], end)
        else:
            merged.append((kind, name, start, end))

    # Build regions, filling gaps with module_stmt regions
    regions = []
    cursor = 1
    for kind, name, start, end in merged:
        if start > cursor:
            # Gap lines before this node
            regions.append(_Region("module_stmt", f"gap_L{cursor}", cursor, start - 1))
        regions.append(_Region(kind, name, start, end))
        cursor = end + 1

    if cursor <= total_lines:
        regions.append(_Region("module_stmt", f"tail_L{cursor}", cursor, total_lines))

    return regions


# ---------------------------------------------------------------------------
# diff analysis
# ---------------------------------------------------------------------------

def _changed_lines(base_lines, modified_lines):
    """Return set of 1-based line numbers in base that were changed or deleted,
    plus the 1-based line numbers that were inserted-adjacent-to."""
    sm = difflib.SequenceMatcher(None, base_lines, modified_lines, autojunk=False)
    changed = set()
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        # Lines in the base that were replaced or deleted
        for ln in range(i1 + 1, i2 + 1):   # +1 for 1-based
            changed.add(ln)
        # For inserts, mark the adjacent base line so region overlap detects it
        if tag == "insert" and i1 > 0:
            changed.add(i1)  # line before insert point (1-based = i1 since i1==i2 for pure insert)
        if tag == "insert" and i1 == 0:
            changed.add(1)
    return changed


def _touched_regions(regions, changed_lines):
    """Return set of region names touched by the given changed lines."""
    touched = set()
    for region in regions:
        for ln in changed_lines:
            if region.start <= ln <= region.end:
                touched.add(region.name)
                break
    return touched


def _apply_diff_lines(base_lines, modified_lines, base_original):
    """Given base_lines and modified_lines, produce a unified diff as a list of
    (action, line_no, text) tuples for later replay."""
    ops = difflib.SequenceMatcher(None, base_lines, modified_lines, autojunk=False).get_opcodes()
    return ops


# ---------------------------------------------------------------------------
# line-based heuristic for non-Python
# ---------------------------------------------------------------------------

def _line_ranges(base_content, modified_content):
    """Return (min_line, max_line) 1-based of changed region, or None if identical."""
    base = base_content.splitlines()
    mod = modified_content.splitlines()
    changed = _changed_lines(base, mod)
    if not changed:
        return None
    return (min(changed), max(changed))


# ---------------------------------------------------------------------------
# core merge logic
# ---------------------------------------------------------------------------

def can_auto_merge(base_content, diff_a, diff_b, filepath="unknown.py"):
    """Analyze whether two modifications to the same base can be auto-merged.

    Parameters
    ----------
    base_content : str   The original file content both diffs started from.
    diff_a : str         Full file content after applying change A.
    diff_b : str         Full file content after applying change B.
    filepath : str       Path for logging / language detection.

    Returns
    -------
    dict  {"mergeable": bool, "confidence": float, "strategy": str}
    """
    if not _ENABLED:
        return {"mergeable": False, "confidence": 0.0, "strategy": "disabled"}

    try:
        if base_content is None or diff_a is None or diff_b is None:
            return {"mergeable": False, "confidence": 0.0, "strategy": "null_input"}

        base_lines = base_content.splitlines()
        a_lines = diff_a.splitlines()
        b_lines = diff_b.splitlines()

        is_python = filepath.endswith(".py")

        if is_python:
            regions = _extract_regions(base_content)
            if not regions:
                # AST parse failed, fall back to line heuristic
                return _can_merge_line_heuristic(base_lines, a_lines, b_lines)

            changed_a = _changed_lines(base_lines, a_lines)
            changed_b = _changed_lines(base_lines, b_lines)

            if not changed_a and not changed_b:
                return {"mergeable": True, "confidence": 1.0, "strategy": "both_identical"}
            if not changed_a:
                return {"mergeable": True, "confidence": 1.0, "strategy": "only_b_changed"}
            if not changed_b:
                return {"mergeable": True, "confidence": 1.0, "strategy": "only_a_changed"}

            touched_a = _touched_regions(regions, changed_a)
            touched_b = _touched_regions(regions, changed_b)

            overlap = touched_a & touched_b
            if not overlap:
                confidence = 0.95
                return {"mergeable": confidence >= _CONFIDENCE_MIN,
                        "confidence": confidence,
                        "strategy": "ast_disjoint_regions"}

            # Overlapping regions -- cannot auto-merge safely
            return {"mergeable": False, "confidence": 0.0,
                    "strategy": "ast_overlapping_regions",
                    "overlapping": sorted(overlap)}
        else:
            return _can_merge_line_heuristic(base_lines, a_lines, b_lines)

    except Exception as exc:
        _log.warning("can_auto_merge error: %s", exc)
        with _lock:
            _stats["errors"] += 1
        return {"mergeable": False, "confidence": 0.0, "strategy": "error"}


def _can_merge_line_heuristic(base_lines, a_lines, b_lines):
    """Line-range heuristic for non-Python or AST-unparseable files."""
    changed_a = _changed_lines(base_lines, a_lines)
    changed_b = _changed_lines(base_lines, b_lines)

    if not changed_a and not changed_b:
        return {"mergeable": True, "confidence": 1.0, "strategy": "both_identical"}
    if not changed_a:
        return {"mergeable": True, "confidence": 1.0, "strategy": "only_b_changed"}
    if not changed_b:
        return {"mergeable": True, "confidence": 1.0, "strategy": "only_a_changed"}

    # Check if changed line ranges are disjoint with a buffer
    overlap = changed_a & changed_b
    if not overlap:
        min_a, max_a = min(changed_a), max(changed_a)
        min_b, max_b = min(changed_b), max(changed_b)
        gap = min(abs(min_a - max_b), abs(min_b - max_a))
        # Confidence scales with gap size
        confidence = min(0.9, 0.7 + gap * 0.02)
        return {"mergeable": confidence >= _CONFIDENCE_MIN,
                "confidence": confidence,
                "strategy": "line_disjoint"}

    return {"mergeable": False, "confidence": 0.0, "strategy": "line_overlapping"}


# ---------------------------------------------------------------------------
# 3-way merge execution
# ---------------------------------------------------------------------------

def semantic_merge(base_content, diff_a, diff_b, filepath="unknown.py"):
    """Attempt a 3-way semantic merge.

    Parameters
    ----------
    base_content : str   Original file.
    diff_a : str         File after change A.
    diff_b : str         File after change B.
    filepath : str       For logging / language detection.

    Returns
    -------
    dict  {"merged": str|None, "conflicts": list, "auto_resolved": int}
          On failure, merged is None.
    """
    if not _ENABLED:
        return {"merged": None, "conflicts": ["disabled"], "auto_resolved": 0}

    try:
        check = can_auto_merge(base_content, diff_a, diff_b, filepath)
        if not check["mergeable"]:
            return {"merged": None,
                    "conflicts": [check.get("strategy", "unknown")],
                    "auto_resolved": 0}

        strategy = check["strategy"]

        # Trivial cases
        if strategy in ("both_identical",):
            return {"merged": diff_a, "conflicts": [], "auto_resolved": 0}
        if strategy == "only_a_changed":
            return {"merged": diff_a, "conflicts": [], "auto_resolved": 1}
        if strategy == "only_b_changed":
            return {"merged": diff_b, "conflicts": [], "auto_resolved": 1}

        # Non-overlapping merge: apply both sets of changes to the base
        base_lines = base_content.splitlines(keepends=True)
        a_lines = diff_a.splitlines(keepends=True)
        b_lines = diff_b.splitlines(keepends=True)

        merged = _three_way_merge(base_lines, a_lines, b_lines)
        if merged is None:
            return {"merged": None, "conflicts": ["merge_failed"], "auto_resolved": 0}

        return {"merged": "".join(merged), "conflicts": [], "auto_resolved": 2}

    except Exception as exc:
        _log.warning("semantic_merge error: %s", exc)
        with _lock:
            _stats["errors"] += 1
        return {"merged": None, "conflicts": [str(exc)], "auto_resolved": 0}


def _three_way_merge(base, a, b):
    """Line-level 3-way merge.  Returns merged lines or None on conflict.

    For each hunk in A's diff against base and B's diff against base, if they
    touch different line ranges, both are applied.  If they touch the same
    range, we return None (conflict).
    """
    try:
        sm_a = difflib.SequenceMatcher(None, base, a, autojunk=False)
        sm_b = difflib.SequenceMatcher(None, base, b, autojunk=False)

        ops_a = [(tag, i1, i2, j1, j2) for tag, i1, i2, j1, j2 in sm_a.get_opcodes() if tag != "equal"]
        ops_b = [(tag, i1, i2, j1, j2) for tag, i1, i2, j1, j2 in sm_b.get_opcodes() if tag != "equal"]

        # Check for base-range overlap between any A op and any B op
        for ta, ai1, ai2, aj1, aj2 in ops_a:
            for tb, bi1, bi2, bj1, bj2 in ops_b:
                if ai1 < bi2 and bi1 < ai2:
                    return None  # overlapping base ranges

        # No overlapping -- build merged result
        # Collect all edits keyed by base position
        edits = {}  # base_start -> (base_end, replacement_lines)
        for tag, i1, i2, j1, j2 in ops_a:
            edits[i1] = (i2, a[j1:j2])
        for tag, i1, i2, j1, j2 in ops_b:
            edits[i1] = (i2, b[j1:j2])

        # Replay base, substituting edits
        result = []
        i = 0
        while i < len(base):
            if i in edits:
                end, replacement = edits[i]
                result.extend(replacement)
                i = end
            else:
                result.append(base[i])
                i += 1

        return result

    except Exception:
        return None


# ---------------------------------------------------------------------------
# outcome tracking
# ---------------------------------------------------------------------------

def record_outcome(filepath, strategy, success):
    """Record whether an auto-merge attempt succeeded or failed.

    Parameters
    ----------
    filepath : str   The file that was merged.
    strategy : str   The strategy used (from can_auto_merge).
    success : bool   Whether the merge produced a correct result.
    """
    try:
        with _lock:
            if success:
                _stats["auto_merges"] += 1
            else:
                _stats["deferrals"] += 1

            _stats["by_strategy"].setdefault(strategy, {"success": 0, "fail": 0})
            key = "success" if success else "fail"
            _stats["by_strategy"][strategy][key] += 1

            _stats["by_filepath"].setdefault(filepath, {"auto": 0, "deferred": 0})
            fkey = "auto" if success else "deferred"
            _stats["by_filepath"][filepath][fkey] += 1
    except Exception:
        pass


# ---------------------------------------------------------------------------
# stats
# ---------------------------------------------------------------------------

def stats():
    """Return a snapshot of merge statistics."""
    with _lock:
        total = _stats["auto_merges"] + _stats["deferrals"]
        return {
            "auto_merges": _stats["auto_merges"],
            "deferrals": _stats["deferrals"],
            "errors": _stats["errors"],
            "success_rate": (_stats["auto_merges"] / total) if total > 0 else 0.0,
            "total_attempts": total,
            "by_strategy": dict(_stats["by_strategy"]),
            "by_filepath": dict(_stats["by_filepath"]),
        }


# ---------------------------------------------------------------------------
# module-level convenience (singleton pattern)
# ---------------------------------------------------------------------------

def reset_stats():
    """Reset all stats counters.  Useful for testing."""
    with _lock:
        _stats["auto_merges"] = 0
        _stats["deferrals"] = 0
        _stats["errors"] = 0
        _stats["by_strategy"].clear()
        _stats["by_filepath"].clear()


def enabled():
    """Return whether semantic merge is enabled."""
    return _ENABLED


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Quick self-test
    base = "import os\n\ndef foo():\n    return 1\n\ndef bar():\n    return 2\n"
    a = "import os\n\ndef foo():\n    return 42\n\ndef bar():\n    return 2\n"
    b = "import os\n\ndef foo():\n    return 1\n\ndef bar():\n    return 99\n"

    check = can_auto_merge(base, a, b, "test.py")
    print("can_auto_merge:", check)

    result = semantic_merge(base, a, b, "test.py")
    print("merged:", repr(result["merged"]))
    print("conflicts:", result["conflicts"])
    print("auto_resolved:", result["auto_resolved"])
