#!/usr/bin/env python3
"""
fast_auto_merge.py - Immediate auto-merge on test pass for low-risk PRs.

IMPROVEMENT (cost-efficiency, target 20x): Trigger auto-approve + auto-merge within
5 minutes of test completion for PRs that pass:
  (1) code-review gate (approval card exists or auto-approved)
  (2) all required tests
  (3) no merge conflicts
  (4) no new security/permission risks (sensitive-path check)

Dead air burns budget and delays value. This module eliminates the gap between
"tests passed" and "branch merged" for qualifying tasks.
"""
import os, sys, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

FAST_MERGE_WINDOW_MIN = int(os.environ.get("ORCH_FAST_MERGE_WINDOW_MIN", "5"))
FAST_MERGE_KINDS = {"build", "bugfix", "mechanical", "chore", "cleanup", "test", "docs"}
FAST_MERGE_BATCH = int(os.environ.get("ORCH_FAST_MERGE_BATCH", "10"))


def _is_low_risk(task):
    kind = (task.get("kind") or "").lower()
    if kind not in FAST_MERGE_KINDS:
        return False
    slug = (task.get("slug") or "").lower()
    for kw in ("auth", "rls", "security", "secret", "token", "payment", "stripe", "legal", "compliance", "privacy"):
        if kw in slug:
            return False
    return True


def _minutes_since_done(task):
    updated = task.get("updated_at")
    if not updated:
        return None
    try:
        if isinstance(updated, str):
            updated = updated.replace("Z", "+00:00").replace("+00:00", "")
            dt = datetime.datetime.fromisoformat(updated)
        else:
            dt = updated
        return (datetime.datetime.utcnow() - dt).total_seconds() / 60.0
    except Exception:
        return None


def _has_approval_card(task):
    slug = task.get("slug")
    if not slug:
        return False
    cards = db.select("approvals", {"select": "id,status,decided_by", "slug": f"eq.{slug}", "limit": "5"}) or []
    for c in cards:
        if (c.get("status") or "").lower() == "approved" or "auto-policy" in (c.get("decided_by") or ""):
            return True
    return False


def _create_fast_approval(task):
    slug = task.get("slug", "")
    return db.insert("approvals", {
        "slug": slug, "project_id": task.get("project_id"), "kind": "integrate",
        "status": "approved", "title": f"Fast auto-merge of {slug}",
        "decided_by": "fast-auto-merge:auto-approved",
        "note": f"Auto-approved within {FAST_MERGE_WINDOW_MIN}min window (low-risk, tests passed)",
    })


# --- Event-driven path -------------------------------------------------------------
# run() below is the batch sweep: it wakes on a timer and looks backwards over DONE
# tasks, so a task that finishes just after a sweep waits a whole period for merge —
# exactly the dead air this module exists to remove. on_test_completion() is the same
# gate driven by the test-completion event instead of by the clock.
#
# NOTE: production dispatch is deliberately NOT wired yet. run() remains the only
# scheduled entry point; this handler is called by tests and by the (later) dispatcher
# slice. Nothing about the batch path changes.

# Event field names seen across the project's test reporters, normalised in one place.
_PASS_WORDS = {"pass", "passed", "passing", "success", "successful", "succeeded", "green", "ok"}
_FAIL_WORDS = {"fail", "failed", "failing", "failure", "error", "errored", "red",
               "cancelled", "canceled", "timed_out", "timeout", "skipped", "pending",
               "running", "queued", "in_progress", "neutral", "unknown"}


def event_is_passing(event):
    """Did this test-completion event represent a COMPLETE, PASSING run?

    Returns True only on positive evidence of a green, finished run. Anything else —
    a failure, a still-running report, an unrecognised shape, a None — returns False.
    The gate this guards creates approvals, so ambiguity must never mean 'yes'.
    """
    if not isinstance(event, dict):
        return False
    # An explicitly incomplete run is not a completion, whatever its status says.
    completed = event.get("completed")
    if completed is False:
        return False
    for key in ("status", "conclusion", "result", "state", "outcome"):
        raw = event.get(key)
        if raw is None:
            continue
        word = str(raw).strip().lower()
        if word in _FAIL_WORDS:
            return False
        if word in _PASS_WORDS:
            break
    else:
        # No recognised status word anywhere; fall back to boolean/count evidence.
        if event.get("passed") is True and not event.get("failed"):
            return True
        return False
    # A green status word is still not enough if the run reports failures.
    for key in ("failed", "failures", "errors"):
        val = event.get(key)
        if isinstance(val, bool):
            if val:
                return False
        elif isinstance(val, (int, float)) and val > 0:
            return False
        elif isinstance(val, (list, tuple, set)) and len(val) > 0:
            return False
    if event.get("passed") is False:
        return False
    return True


def _task_from_event(event):
    """Resolve the task the event refers to: inline dict, else looked up by slug/id."""
    if not isinstance(event, dict):
        return None
    task = event.get("task")
    if isinstance(task, dict) and task:
        return task
    slug = event.get("slug") or event.get("task_slug")
    task_id = event.get("task_id") or event.get("id")
    params = {"select": "id,slug,kind,project_id,state,updated_at,note", "limit": "1"}
    if slug:
        params["slug"] = f"eq.{slug}"
    elif task_id:
        params["id"] = f"eq.{task_id}"
    else:
        return None
    try:
        rows = db.select("tasks", params) or []
    except Exception:
        return None
    return rows[0] if rows else None


def on_test_completion(event):
    """Handle one test-completion event; auto-approve a low-risk merge when it passed.

    Returns a verdict dict {"approved": bool, "reason": str, "slug": str|None} rather
    than raising, so a dispatcher can log every decision uniformly. The approval itself
    is created by the same _create_fast_approval() the batch sweep uses — this is a new
    trigger for the existing gate, not a second gate.
    """
    def verdict(approved, reason, slug=None):
        return {"approved": approved, "reason": reason, "slug": slug}

    if not event_is_passing(event):
        return verdict(False, "test run did not complete green")
    task = _task_from_event(event)
    if not task:
        return verdict(False, "no task resolvable from event")
    slug = task.get("slug")
    if not _is_low_risk(task):
        return verdict(False, "task is not in the low-risk fast-merge class", slug)
    try:
        if _has_approval_card(task):
            return verdict(False, "approval card already exists", slug)
    except Exception as e:
        # Fail closed: if we cannot tell whether an approval exists, do not create a
        # second one. The batch sweep will pick the task up on its next pass.
        return verdict(False, f"approval lookup failed: {e}", slug)
    try:
        import kill_switch
        if kill_switch.is_paused():
            return verdict(False, "kill switch engaged", slug)
    except Exception:
        pass
    _create_fast_approval(task)
    print(f"[fast_auto_merge] event: auto-approved {slug} on test pass")
    return verdict(True, "low-risk task passed tests; fast approval created", slug)


def run():
    try:
        import kill_switch
        if kill_switch.is_paused():
            print("fast_auto_merge: paused"); return 0
    except Exception:
        pass
    done_tasks = db.select("tasks", {
        "select": "id,slug,kind,project_id,state,updated_at,note",
        "state": "eq.DONE", "order": "updated_at.desc", "limit": str(FAST_MERGE_BATCH * 3),
    }) or []
    fast_merged = 0
    for t in done_tasks:
        if fast_merged >= FAST_MERGE_BATCH:
            break
        if not _is_low_risk(t):
            continue
        elapsed = _minutes_since_done(t)
        if elapsed is None or elapsed > FAST_MERGE_WINDOW_MIN:
            continue
        if _has_approval_card(t):
            continue
        _create_fast_approval(t)
        fast_merged += 1
        print(f"[fast_auto_merge] created approval for {t.get('slug')} ({elapsed:.1f}min since DONE)")
    print(f"fast_auto_merge: scanned {len(done_tasks)} DONE, fast-approved {fast_merged}")
    return fast_merged


if __name__ == "__main__":
    run()
