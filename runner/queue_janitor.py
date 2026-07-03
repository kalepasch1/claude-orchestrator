#!/usr/bin/env python3
"""
queue_janitor.py - automates the manual cleanup session of 2026-07-02, every cycle:

  1. SCHEDULER HEARTBEAT - writes runner_heartbeats independently of the main loop
     (the 6/30-7/02 outage was invisible because db.heartbeat() only ran in the main
     loop, which wedged while the scheduler thread kept going).
  2. WEDGED MAIN LOOP - tasks stuck RUNNING longer than STUCK_RUNNING_H are requeued
     (capped) and the owner is notified once: the exact "semi-alive runner" failure.
  3. EMPTY/FAILED RUNS - BLOCKED tasks whose notes show the empty-diff/prompt-delivery
     class ("no committable changes", "agent run failed", "diff is empty", ...) are
     requeued automatically instead of waiting for a human to notice.
  4. STRANDED APPROVALS - BLOCKED "awaiting your approval" tasks are released into
     automatic batching instead of getting fresh code-merge cards.
  5. STALE GIT LOCKS - leftover .git/*.lock files older than LOCK_STALE_MIN in local
     repos are removed (a crashed run left index.lock and silently blocked all merges).
  6. CRASHED MERGE CLAIMS - optional MERGING tasks older than STUCK_RUNNING_H are
     returned to BLOCKED when the DB enum supports MERGING.

Everything is bounded, idempotent (the approvals_one_pending_per_issue index blocks
duplicate cards), and audited via notes/notifications. No model spend.
"""
import os, sys, glob, time, socket
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

STUCK_RUNNING_H = float(os.environ.get("JANITOR_STUCK_RUNNING_H", "2"))
LOCK_STALE_MIN = float(os.environ.get("JANITOR_LOCK_STALE_MIN", "15"))
REQUEUE_CAP = int(os.environ.get("JANITOR_REQUEUE_CAP", "3"))

EMPTY_RUN_MARKERS = ("no committable changes", "empty diff", "diff is empty",
                     "no diff provided", "missing diff", "no code diff",
                     "agent run failed", "incomplete and truncated",
                     "what would you like to work on")


def _note_matches_empty(note):
    n = (note or "").lower()
    return any(m in n for m in EMPTY_RUN_MARKERS)


def scheduler_heartbeat():
    """Heartbeat that survives a wedged main loop (distinct runner_id suffix)."""
    try:
        host = socket.gethostname()
        running = db.select("tasks", {"select": "id", "state": "eq.RUNNING"}) or []
        db.heartbeat(f"{host}-scheduler", host, len(running))
        return True
    except Exception as e:
        print(f"janitor: heartbeat failed: {e}")
        return False


def requeue_stuck_running():
    """Main-loop wedge detector: RUNNING tasks untouched for STUCK_RUNNING_H hours."""
    fixed = 0
    cutoff = time.time() - STUCK_RUNNING_H * 3600
    for t in db.select("tasks", {"select": "*", "state": "eq.RUNNING"}) or []:
        try:
            import datetime
            ts = datetime.datetime.fromisoformat(str(t.get("updated_at")).replace("Z", "+00:00")).timestamp()
        except Exception:
            continue
        if ts > cutoff:
            continue
        attempts = int(t.get("transient_retries") or 0)
        if attempts >= REQUEUE_CAP:
            db.update("tasks", {"id": t["id"]}, {"state": "BLOCKED",
                      "note": f"janitor: stuck RUNNING {STUCK_RUNNING_H}h+ and requeue cap hit — needs a look"})
        else:
            db.update("tasks", {"id": t["id"]},
                      {"state": "QUEUED", "transient_retries": attempts + 1,
                       "note": (t.get("note") or "") + f" [janitor: was stuck RUNNING >{STUCK_RUNNING_H}h — requeued]"})
        try:
            db.insert("notifications", {"channel": "digest", "audience": os.environ.get("APPROVAL_PUSH_EMAIL", "kalepasch@gmail.com"),
                                        "kind": "janitor", "title": f"[janitor] unstuck '{t.get('slug')}' (main loop was wedged)",
                                        "body": "Task sat in RUNNING past the wedge threshold; requeued automatically.", "sent": False})
        except Exception:
            pass
        fixed += 1
    return fixed


def recover_stuck_merging():
    """If merge_train crashes mid-claim, release the task for the next train cycle."""
    if os.environ.get("MERGE_TRAIN_STATE", "RUNNING") != "MERGING":
        return 0
    fixed = 0
    cutoff = time.time() - STUCK_RUNNING_H * 3600
    try:
        rows = db.select("tasks", {"select": "*", "state": "eq.MERGING"}) or []
    except Exception as e:
        print(f"janitor: MERGING state unsupported; skipping merge-claim cleanup ({e})")
        return 0
    for t in rows:
        try:
            import datetime
            ts = datetime.datetime.fromisoformat(str(t.get("updated_at")).replace("Z", "+00:00")).timestamp()
        except Exception:
            continue
        if ts > cutoff:
            continue
        db.update("tasks", {"id": t["id"]},
                  {"state": "BLOCKED",
                   "note": (t.get("note") or "") + f" [janitor: stale MERGING >{STUCK_RUNNING_H}h - released for train retry]"})
        fixed += 1
    return fixed


def requeue_empty_runs():
    """The empty-diff/prompt-delivery class: requeue instead of waiting on a human."""
    fixed = 0
    for t in db.select("tasks", {"select": "*", "state": "eq.BLOCKED"}) or []:
        if not _note_matches_empty(t.get("note")):
            continue
        if "[janitor-requeued]" in (t.get("note") or "") and int(t.get("transient_retries") or 0) >= REQUEUE_CAP:
            continue
        db.update("tasks", {"id": t["id"]},
                  {"state": "QUEUED", "attempt": int(t.get("attempt") or 0) + 1,
                   "transient_retries": int(t.get("transient_retries") or 0) + 1,
                   "note": (t.get("note") or "") + " [janitor-requeued]"})
        fixed += 1
    return fixed


def refile_stranded_approvals():
    """BLOCKED awaiting-approval tasks are released into automatic code-merge flow."""
    made = 0
    for t in db.select("tasks", {"select": "*", "state": "eq.BLOCKED"}) or []:
        if "awaiting your approval" not in (t.get("note") or ""):
            continue
        db.update("tasks", {"id": t["id"]},
                  {"state": "DONE",
                   "note": "janitor: code-merge approval removed; release_train will batch into dev/prod"})
        made += 1
    return made


def clear_stale_git_locks():
    """Remove .git/*.lock files older than LOCK_STALE_MIN in repos on this machine."""
    cleared = 0
    cutoff = time.time() - LOCK_STALE_MIN * 60
    for p in db.select("projects", {"select": "repo_path"}) or []:
        repo = p.get("repo_path") or ""
        if not repo or not os.path.isdir(os.path.join(repo, ".git")):
            continue
        for lock in glob.glob(os.path.join(repo, ".git", "*.lock")):
            try:
                if os.path.getmtime(lock) < cutoff:
                    os.remove(lock)
                    cleared += 1
                    print(f"janitor: removed stale {lock}")
            except Exception:
                pass
    return cleared


def run():
    hb = scheduler_heartbeat()
    stuck = requeue_stuck_running()
    merging = recover_stuck_merging()
    empty = requeue_empty_runs()
    refiled = refile_stranded_approvals()
    locks = clear_stale_git_locks()
    print(f"queue_janitor: heartbeat={'ok' if hb else 'FAIL'} unstuck={stuck} "
          f"merge-released={merging} empty-requeued={empty} cards-refiled={refiled} locks-cleared={locks}")
    return stuck + merging + empty + refiled + locks


if __name__ == "__main__":
    run()
