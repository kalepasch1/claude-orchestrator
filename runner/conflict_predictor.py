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
