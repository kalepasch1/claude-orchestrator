"""
conflict_predictor.py - predict and prevent merge conflicts by checking file-scope
overlap between QUEUED tasks and currently IN_PROGRESS tasks.

check_conflicts(task) - returns {"conflicts": [...], "action": "proceed"|"defer"|"serialize", "reason": str}
suggest_priority(task, conflicts) - returns suggested priority adjustment
stats() - dict with conflicts_detected, defers_suggested, false_positives
record_outcome(task_id, had_conflict, was_deferred) - tracks prediction accuracy
"""
import sys, os, re, threading, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import log as _log_mod
_log = _log_mod.get("conflict_predictor")

_FILE_RE = re.compile(r'[\w/.-]+\.(?:py|ts|js|go|rs|java|tsx|jsx|css|html|sql|yaml|yml|json|toml)')

_ENABLED = os.environ.get("ORCH_CONFLICT_PREDICTOR_ENABLED", "true").lower() == "true"
_THRESHOLD = float(os.environ.get("ORCH_CONFLICT_THRESHOLD", "0.3"))

_lock = threading.Lock()
_stats = {
    "conflicts_detected": 0,
    "defers_suggested": 0,
    "false_positives": 0,
}
_outcomes = {}  # task_id -> {"had_conflict": bool, "was_deferred": bool}

_SAFE = {"conflicts": [], "action": "proceed", "reason": "predictor unavailable"}


def _extract_files(text):
    """Extract file paths from text using regex."""
    if not text:
        return set()
    return set(_FILE_RE.findall(text))


def _jaccard(a, b):
    """Compute Jaccard similarity between two sets."""
    if not a or not b:
        return 0.0
    intersection = a & b
    union = a | b
    return len(intersection) / len(union) if union else 0.0


def _get_prompt(task):
    """Extract prompt text from a task dict."""
    if not task:
        return ""
    if isinstance(task, dict):
        return task.get("prompt", "") or task.get("description", "") or ""
    return ""


def check_conflicts(task):
    """Check for file-scope overlap between a candidate task and active tasks.

    Returns {"conflicts": [...], "action": "proceed"|"defer"|"serialize", "reason": str}
    """
    if not _ENABLED:
        return {"conflicts": [], "action": "proceed", "reason": "predictor disabled"}
    try:
        import db
        candidate_files = _extract_files(_get_prompt(task))
        if not candidate_files:
            return {"conflicts": [], "action": "proceed", "reason": "no files detected in task"}

        active = db.select("tasks", {
            "select": "id,prompt",
            "state": "in.(RUNNING,RETRY)",
        }) or []

        all_overlaps = []
        max_overlap = 0.0

        for active_task in active:
            active_files = _extract_files(_get_prompt(active_task))
            if not active_files:
                continue
            overlap = candidate_files & active_files
            if overlap:
                j = _jaccard(candidate_files, active_files)
                max_overlap = max(max_overlap, j)
                all_overlaps.extend(sorted(overlap))

        all_overlaps = sorted(set(all_overlaps))

        with _lock:
            if max_overlap > _THRESHOLD:
                _stats["conflicts_detected"] += 1
                _stats["defers_suggested"] += 1
                return {
                    "conflicts": all_overlaps,
                    "action": "defer",
                    "reason": f"Jaccard overlap {max_overlap:.2f} exceeds threshold {_THRESHOLD}; overlapping files: {', '.join(all_overlaps[:10])}",
                }
            elif max_overlap > 0:
                _stats["conflicts_detected"] += 1
                return {
                    "conflicts": all_overlaps,
                    "action": "proceed",
                    "reason": f"low overlap {max_overlap:.2f} (threshold {_THRESHOLD}); overlapping files: {', '.join(all_overlaps[:10])}",
                }
            else:
                return {"conflicts": [], "action": "proceed", "reason": "no file overlap"}

    except Exception as exc:
        _log.warning("check_conflicts failed: %s", exc)
        return dict(_SAFE)


def suggest_priority(task, conflicts):
    """Return a suggested priority adjustment to serialize conflicting tasks.

    Returns a dict with suggested_priority and reason.
    """
    try:
        if not conflicts or not conflicts.get("conflicts"):
            return {"suggested_priority": 0, "reason": "no conflicts"}

        action = conflicts.get("action", "proceed")
        num_conflicts = len(conflicts.get("conflicts", []))

        if action == "defer":
            return {
                "suggested_priority": -10,
                "reason": f"defer: {num_conflicts} overlapping file(s); lower priority to serialize",
            }
        elif num_conflicts > 0:
            return {
                "suggested_priority": -2,
                "reason": f"minor overlap: {num_conflicts} file(s); slight priority reduction",
            }
        return {"suggested_priority": 0, "reason": "no adjustment needed"}
    except Exception as exc:
        _log.warning("suggest_priority failed: %s", exc)
        return {"suggested_priority": 0, "reason": "predictor unavailable"}


def stats():
    """Return prediction statistics."""
    with _lock:
        return dict(_stats)


def record_outcome(task_id, had_conflict, was_deferred):
    """Track whether a conflict prediction was correct.

    If we deferred but there was no actual conflict, that's a false positive.
    """
    try:
        with _lock:
            _outcomes[task_id] = {
                "had_conflict": had_conflict,
                "was_deferred": was_deferred,
                "ts": time.time(),
            }
            if was_deferred and not had_conflict:
                _stats["false_positives"] += 1
    except Exception as exc:
        _log.warning("record_outcome failed: %s", exc)


# ---------------------------------------------------------------------------
# Real-time conflict detection during merge process
# ---------------------------------------------------------------------------

_REALTIME_ENABLED = os.environ.get("ORCH_REALTIME_CONFLICT_ENABLED", "true").lower() == "true"
_CONTENT_OVERLAP_THRESHOLD = float(os.environ.get("ORCH_CONTENT_OVERLAP_THRESHOLD", "0.5"))


def _extract_function_names(text):
    """Extract function/class definitions from code text for semantic overlap."""
    if not text:
        return set()
    fns = set()
    for m in re.finditer(r'(?:def|class|function|const|let|var)\s+(\w+)', text):
        fns.add(m.group(1))
    return fns


def analyze_merge_conflict(base_content, branch_a_content, branch_b_content, filepath=""):
    """Analyze a real merge conflict to classify severity and suggest resolution.

    Returns {
        "severity": "low"|"medium"|"high",
        "conflict_type": "additive"|"divergent"|"semantic",
        "auto_resolvable": bool,
        "suggestion": str,
        "overlapping_symbols": list,
    }
    """
    if not _REALTIME_ENABLED:
        return {"severity": "low", "conflict_type": "unknown",
                "auto_resolvable": False, "suggestion": "realtime analysis disabled",
                "overlapping_symbols": []}
    try:
        fns_a = _extract_function_names(branch_a_content or "")
        fns_b = _extract_function_names(branch_b_content or "")
        fns_base = _extract_function_names(base_content or "")

        new_in_a = fns_a - fns_base
        new_in_b = fns_b - fns_base
        modified_both = (fns_a & fns_b) - fns_base  # new in both branches

        # Additive: both branches add new, non-overlapping symbols
        if new_in_a and new_in_b and not (new_in_a & new_in_b):
            return {
                "severity": "low",
                "conflict_type": "additive",
                "auto_resolvable": True,
                "suggestion": "Both branches add non-overlapping code; safe to merge both additions.",
                "overlapping_symbols": [],
            }

        # Divergent: same symbols modified differently
        overlap = new_in_a & new_in_b
        if overlap:
            return {
                "severity": "high",
                "conflict_type": "divergent",
                "auto_resolvable": False,
                "suggestion": f"Both branches define: {', '.join(sorted(overlap)[:5])}. Manual review needed.",
                "overlapping_symbols": sorted(overlap),
            }

        # Semantic: same region touched but different symbols
        lines_a = set((branch_a_content or "").splitlines())
        lines_b = set((branch_b_content or "").splitlines())
        lines_base = set((base_content or "").splitlines())
        changed_a = lines_a - lines_base
        changed_b = lines_b - lines_base
        common_changes = changed_a & changed_b

        if common_changes:
            ratio = len(common_changes) / max(len(changed_a | changed_b), 1)
            severity = "high" if ratio > _CONTENT_OVERLAP_THRESHOLD else "medium"
            return {
                "severity": severity,
                "conflict_type": "semantic",
                "auto_resolvable": ratio < 0.2,
                "suggestion": f"Content overlap ratio {ratio:.2f}; {'auto-merge possible' if ratio < 0.2 else 'manual review recommended'}.",
                "overlapping_symbols": sorted(list(fns_a & fns_b))[:10],
            }

        return {
            "severity": "low",
            "conflict_type": "additive",
            "auto_resolvable": True,
            "suggestion": "No semantic overlap detected; safe to auto-merge.",
            "overlapping_symbols": [],
        }

    except Exception as exc:
        _log.warning("analyze_merge_conflict failed: %s", exc)
        return {"severity": "medium", "conflict_type": "unknown",
                "auto_resolvable": False, "suggestion": f"analysis error: {exc}",
                "overlapping_symbols": []}


def auto_resolve_conflict(base_content, branch_a_content, branch_b_content, filepath=""):
    """Attempt automatic conflict resolution for additive/low-overlap conflicts.

    Returns {"resolved": bool, "merged_content": str, "strategy": str}.
    Only resolves when both branches add non-overlapping code (append-both strategy).
    """
    if not _REALTIME_ENABLED:
        return {"resolved": False, "merged_content": "", "strategy": "disabled"}

    analysis = analyze_merge_conflict(base_content, branch_a_content, branch_b_content, filepath)

    if not analysis.get("auto_resolvable"):
        return {"resolved": False, "merged_content": "", "strategy": "manual_required",
                "analysis": analysis}

    try:
        base_lines = (base_content or "").splitlines(keepends=True)
        a_lines = (branch_a_content or "").splitlines(keepends=True)
        b_lines = (branch_b_content or "").splitlines(keepends=True)

        # Find lines added by each branch
        base_set = set(base_lines)
        added_a = [l for l in a_lines if l not in base_set]
        added_b = [l for l in b_lines if l not in base_set]

        # Append-both: keep all of branch_a, then append branch_b additions
        merged = list(a_lines)
        if added_b:
            # Add a separator comment if it's a code file
            ext = os.path.splitext(filepath)[1].lower() if filepath else ""
            if ext in (".py", ".js", ".ts", ".go", ".rs", ".java"):
                merged.append("\n")
            merged.extend(added_b)

        return {
            "resolved": True,
            "merged_content": "".join(merged),
            "strategy": "append_both",
            "analysis": analysis,
        }
    except Exception as exc:
        _log.warning("auto_resolve_conflict failed: %s", exc)
        return {"resolved": False, "merged_content": "", "strategy": f"error: {exc}"}


def realtime_conflict_scan(repo_path, branch_a, branch_b, base="master"):
    """Scan two branches for conflicting files and attempt auto-resolution.

    Returns {"files_scanned": int, "conflicts": int, "auto_resolved": int,
             "results": [{filepath, analysis, resolution}]}.
    """
    import subprocess
    results = []
    auto_resolved = 0

    try:
        # Get list of files changed in both branches relative to base
        r_a = subprocess.run(
            ["git", "diff", "--name-only", f"{base}...{branch_a}"],
            cwd=repo_path, capture_output=True, text=True, timeout=30)
        r_b = subprocess.run(
            ["git", "diff", "--name-only", f"{base}...{branch_b}"],
            cwd=repo_path, capture_output=True, text=True, timeout=30)

        files_a = set(r_a.stdout.strip().splitlines()) if r_a.returncode == 0 else set()
        files_b = set(r_b.stdout.strip().splitlines()) if r_b.returncode == 0 else set()
        overlap = files_a & files_b

        for fp in sorted(overlap):
            # Get content from each branch
            def _show(rev, path):
                r = subprocess.run(["git", "show", f"{rev}:{path}"],
                                   cwd=repo_path, capture_output=True, text=True, timeout=10)
                return r.stdout if r.returncode == 0 else ""

            base_c = _show(base, fp)
            a_c = _show(branch_a, fp)
            b_c = _show(branch_b, fp)

            analysis = analyze_merge_conflict(base_c, a_c, b_c, fp)
            resolution = auto_resolve_conflict(base_c, a_c, b_c, fp)

            if resolution.get("resolved"):
                auto_resolved += 1

            results.append({"filepath": fp, "analysis": analysis, "resolution": resolution})

        return {
            "files_scanned": len(overlap),
            "conflicts": len(results),
            "auto_resolved": auto_resolved,
            "results": results,
        }
    except Exception as exc:
        _log.warning("realtime_conflict_scan failed: %s", exc)
        return {"files_scanned": 0, "conflicts": 0, "auto_resolved": 0, "results": []}
