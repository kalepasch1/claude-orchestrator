"""
build_selfheal.py — self-healing loop for production build failures.

Inspects the orchestration queue for BUILDFAIL/TESTFAIL tasks, identifies the failing
files from error notes, and generates minimal fix tasks. Tracks metrics on blocked
states and merge conversion to verify improvement.
"""
import os, sys, re, logging, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

log = logging.getLogger(__name__)

# Common build-error patterns and their likely fix categories
_ERROR_PATTERNS = [
    (re.compile(r"TS\d+:\s+", re.IGNORECASE), "typescript"),
    (re.compile(r"SyntaxError", re.IGNORECASE), "syntax"),
    (re.compile(r"Cannot find module", re.IGNORECASE), "missing-import"),
    (re.compile(r"Type '.*' is not assignable", re.IGNORECASE), "type-mismatch"),
    (re.compile(r"Property '.*' does not exist", re.IGNORECASE), "missing-property"),
    (re.compile(r"Module not found", re.IGNORECASE), "missing-module"),
    (re.compile(r"SIGKILL|OOM|heap", re.IGNORECASE), "oom"),
]


def classify_build_error(note):
    """Classify a build error note into a fix category."""
    text = str(note or "")
    for pattern, category in _ERROR_PATTERNS:
        if pattern.search(text):
            return category
    return "unknown"


def extract_failing_files(note):
    """Extract file paths from a build error note."""
    text = str(note or "")
    # Match common file path patterns in error output
    patterns = [
        re.compile(r"((?:server|app|components|utils|pages)/[\w/.-]+\.(?:ts|tsx|js|jsx|vue))"),
        re.compile(r"([\w/.-]+\.(?:ts|tsx|js|jsx|vue)):\d+:\d+"),
    ]
    files = set()
    for p in patterns:
        files.update(p.findall(text))
    return sorted(files)


def get_build_health_metrics():
    """Compute current build health metrics from the task queue.

    Returns dict with:
    - blocked_count: tasks in BLOCKED/BUILDFAIL/TESTFAIL state
    - queued_count: tasks in QUEUED state
    - merged_count: tasks in MERGED state
    - done_count: tasks in DONE state
    - block_rate: fraction of non-queued tasks that are blocked
    - merge_rate: fraction of done+merged tasks that made it to merged
    """
    states = {}
    for state in ("QUEUED", "RUNNING", "DONE", "MERGED", "BLOCKED", "TESTFAIL", "BUILDFAIL"):
        try:
            count = db.count("tasks", {"state": f"eq.{state}"})
            states[state] = count or 0
        except Exception:
            states[state] = 0

    blocked = states.get("BLOCKED", 0) + states.get("TESTFAIL", 0) + states.get("BUILDFAIL", 0)
    merged = states.get("MERGED", 0)
    done = states.get("DONE", 0)
    total_terminal = blocked + merged + done

    return {
        "blocked_count": blocked,
        "queued_count": states.get("QUEUED", 0),
        "running_count": states.get("RUNNING", 0),
        "merged_count": merged,
        "done_count": done,
        "block_rate": round(blocked / max(1, total_terminal), 3),
        "merge_rate": round(merged / max(1, merged + done), 3),
    }


def find_stuck_build_tasks(limit=20):
    """Find tasks stuck in BLOCKED/TESTFAIL with build-related notes."""
    rows = db.select("tasks", {
        "select": "id,slug,project_id,state,note,updated_at",
        "state": "in.(BLOCKED,TESTFAIL)",
        "order": "updated_at.desc",
        "limit": str(limit),
    }) or []

    results = []
    for r in rows:
        note = str(r.get("note") or "")
        if any(marker in note.lower() for marker in ("buildfail", "build", "type error", "syntax", "ts2")):
            results.append({
                "id": r["id"],
                "slug": r.get("slug"),
                "project_id": r.get("project_id"),
                "error_category": classify_build_error(note),
                "failing_files": extract_failing_files(note),
                "note_preview": note[:200],
            })
    return results


def selfheal_cycle():
    """Run one self-healing cycle: find stuck builds, requeue fixable ones.

    Returns (requeued_count, skipped_count, metrics).
    """
    metrics = get_build_health_metrics()
    stuck = find_stuck_build_tasks()

    requeued = 0
    skipped = 0

    for task in stuck:
        category = task["error_category"]
        # Only auto-requeue categories we can reasonably expect to self-fix
        if category in ("typescript", "syntax", "missing-import", "type-mismatch", "missing-property"):
            try:
                db.update("tasks",
                          {"state": "QUEUED", "note": f"{task['note_preview']} | selfheal: requeued ({category})"},
                          id=task["id"])
                requeued += 1
                log.info("build_selfheal: requeued %s (%s)", task["slug"], category)
            except Exception as e:
                log.warning("build_selfheal: failed to requeue %s: %s", task["slug"], e)
                skipped += 1
        else:
            skipped += 1

    return requeued, skipped, metrics


if __name__ == "__main__":
    import json
    metrics = get_build_health_metrics()
    print("Build health metrics:")
    print(json.dumps(metrics, indent=2))
    stuck = find_stuck_build_tasks()
    print(f"\nStuck build tasks: {len(stuck)}")
    for t in stuck[:5]:
        print(f"  {t['slug']}: {t['error_category']} -> {t['failing_files'][:3]}")
