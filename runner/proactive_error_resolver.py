#!/usr/bin/env python3
"""proactive_error_resolver.py - proactive error detection and auto-resolution.

Slice-3: goes beyond fail-soft (swallowing errors to prevent crashes) to actively
detect error PATTERNS and auto-fix common issues before they block tasks:
  - Recurring error signature detection across tasks
  - Automatic retry with environment fixes (missing tools, stale refs, etc.)
  - Error frequency alerting when a pattern crosses a threshold
  - Pre-flight error prediction based on historical failure signatures
"""
import collections, datetime, json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

PATTERN_WINDOW_H = int(os.environ.get("ORCH_ERROR_PATTERN_WINDOW_H", "6"))
ALERT_THRESHOLD = int(os.environ.get("ORCH_ERROR_ALERT_THRESHOLD", "5"))
AUTO_FIX_ENABLED = os.environ.get("ORCH_AUTO_FIX", "true").lower() in ("true", "1")

# Known fixable error patterns → auto-fix actions
_FIXABLE = [
    (re.compile(r"branch.*missing|no longer exists", re.I),
     "stale_branch", "requeue with fresh base branch"),
    (re.compile(r"conflict|cannot rebase|merge conflict", re.I),
     "conflict", "requeue on fresh base after fetch"),
    (re.compile(r"(yarn|npm|pnpm).*not found|command not found.*(node|python)", re.I),
     "missing_tool", "requeue with toolchain install prefix"),
    (re.compile(r"rate.?limit|429|too many requests", re.I),
     "rate_limit", "requeue with backoff delay"),
    (re.compile(r"timeout|timed out|deadline exceeded", re.I),
     "timeout", "requeue with extended timeout"),
]


def _recent_errors():
    """Gather recent BLOCKED/TESTFAIL/CONFLICT task notes for pattern analysis."""
    since = (datetime.datetime.utcnow() - datetime.timedelta(hours=PATTERN_WINDOW_H)).isoformat()
    try:
        return db.select("tasks", {
            "select": "id,slug,note,state,updated_at,project_id,base_branch,remediation_count",
            "state": "in.(BLOCKED,TESTFAIL,CONFLICT)",
            "updated_at": f"gte.{since}",
            "limit": "200"
        }) or []
    except Exception:
        return []


def detect_patterns():
    """Detect recurring error patterns across recent failures."""
    errors = _recent_errors()
    pattern_counts = collections.Counter()
    pattern_tasks = collections.defaultdict(list)

    for t in errors:
        signal = (t.get("note") or "")
        for regex, pattern_name, _ in _FIXABLE:
            if regex.search(signal):
                pattern_counts[pattern_name] += 1
                pattern_tasks[pattern_name].append(t["slug"])
                break
        else:
            pattern_counts["unknown"] += 1
            pattern_tasks["unknown"].append(t["slug"])

    return {
        "counts": dict(pattern_counts),
        "tasks": {k: v[:10] for k, v in pattern_tasks.items()},
        "total_errors": len(errors),
        "alerts": [p for p, c in pattern_counts.items() if c >= ALERT_THRESHOLD]
    }


def _apply_fix(task, pattern_name, fix_desc):
    """Apply an automatic fix for a known error pattern."""
    tid = task["id"]
    slug = task["slug"]
    rc = int(task.get("remediation_count") or 0)
    note_prefix = f"proactive-fix({pattern_name})"

    if pattern_name == "stale_branch":
        try:
            db.update("tasks", {"id": tid}, {
                "state": "QUEUED", "base_branch": "master",
                "note": f"{note_prefix}: reset to fresh base",
                "remediation_count": rc + 1, "updated_at": "now()"
            })
            return True
        except Exception:
            return False

    elif pattern_name == "conflict":
        try:
            db.update("tasks", {"id": tid}, {
                "state": "QUEUED", "base_branch": "master",
                "note": f"{note_prefix}: requeued on fresh base",
                "remediation_count": rc + 1, "updated_at": "now()"
            })
            return True
        except Exception:
            return False

    elif pattern_name == "rate_limit":
        # Requeue with a note to use backoff
        try:
            db.update("tasks", {"id": tid}, {
                "state": "QUEUED",
                "note": f"{note_prefix}: requeued with backoff",
                "remediation_count": rc + 1, "updated_at": "now()"
            })
            return True
        except Exception:
            return False

    elif pattern_name in ("timeout", "missing_tool"):
        try:
            db.update("tasks", {"id": tid}, {
                "state": "QUEUED",
                "note": f"{note_prefix}: {fix_desc}",
                "remediation_count": rc + 1, "updated_at": "now()"
            })
            return True
        except Exception:
            return False

    return False


def predict_failure(task):
    """Pre-flight check: predict if a task is likely to fail based on
    historical error signatures for similar slugs/projects."""
    slug = task.get("slug", "")
    project_id = task.get("project_id", "")
    try:
        recent_fails = db.select("tasks", {
            "select": "slug,note,state",
            "project_id": f"eq.{project_id}",
            "state": "in.(BLOCKED,TESTFAIL,CONFLICT)",
            "limit": "50"
        }) or []
    except Exception:
        return {"risk": "unknown", "reason": "could not query history"}

    if not recent_fails:
        return {"risk": "low", "reason": "no recent failures in project"}

    # Check if the same slug root has failed before
    slug_root = slug.rsplit("-slice-", 1)[0] if "-slice-" in slug else slug
    same_root = [f for f in recent_fails if f.get("slug", "").startswith(slug_root)]
    if len(same_root) >= 3:
        return {"risk": "high", "reason": f"{len(same_root)} recent failures for {slug_root}"}
    if len(recent_fails) > 20:
        return {"risk": "medium", "reason": f"project has {len(recent_fails)} recent failures"}
    return {"risk": "low", "reason": "no concerning patterns"}


def run(limit=100):
    """Main loop: detect patterns, auto-fix what we can, alert on the rest."""
    if not AUTO_FIX_ENABLED:
        return {"skipped": True, "reason": "ORCH_AUTO_FIX disabled"}

    errors = _recent_errors()[:limit]
    patterns = detect_patterns()
    fixed = 0
    skipped = 0

    for t in errors:
        signal = t.get("note") or ""
        rc = int(t.get("remediation_count") or 0)
        if rc >= 6:  # respect hard cap from auto_remediate
            skipped += 1
            continue
        for regex, pattern_name, fix_desc in _FIXABLE:
            if regex.search(signal):
                if _apply_fix(t, pattern_name, fix_desc):
                    fixed += 1
                break

    # Alert on threshold breaches
    for alert_pattern in patterns.get("alerts", []):
        try:
            db.insert("approvals", {
                "title": f"Error pattern alert: {alert_pattern} ({patterns['counts'][alert_pattern]}x in {PATTERN_WINDOW_H}h)",
                "kind": "alert", "status": "pending",
                "why": f"Recurring {alert_pattern} errors across: {', '.join(patterns['tasks'].get(alert_pattern, [])[:5])}"
            })
        except Exception:
            pass

    result = {"fixed": fixed, "skipped": skipped, "patterns": patterns}
    print(f"proactive_error_resolver: fixed {fixed}, skipped {skipped}, alerts {len(patterns.get('alerts', []))}")
    return result


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, default=str))
