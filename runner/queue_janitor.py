#!/usr/bin/env python3
"""
queue_janitor.py - automates the manual cleanup session of 2026-07-02, every cycle:

  1. SCHEDULER HEARTBEAT - writes runner_heartbeats independently of the main loop
     (the 6/30-7/02 outage was invisible because db.heartbeat() only ran in the main
     loop, which wedged while the scheduler thread kept going).
  2. WEDGED MAIN LOOP - tasks stuck RUNNING longer than STUCK_RUNNING_H are reassigned
     to same-task agentic repair (capped) and the owner is notified once: the exact
     "semi-alive runner" failure.
  3. EMPTY/FAILED RUNS - BLOCKED tasks whose notes show the empty-diff/prompt-delivery
     class ("no committable changes", "agent run failed", "diff is empty", ...) are
     converted into agentic repair automatically instead of waiting for a human to notice.
  4. STRANDED APPROVALS - BLOCKED "awaiting your approval" tasks are released into
     automatic batching instead of getting fresh code-merge cards.
  5. STALE GIT LOCKS - leftover .git/*.lock files older than LOCK_STALE_MIN in local
     repos are removed (a crashed run left index.lock and silently blocked all merges).
  6. CRASHED MERGE CLAIMS - optional MERGING tasks older than STUCK_RUNNING_H are
     returned to BLOCKED when the DB enum supports MERGING.

Everything is bounded, idempotent (the approvals_one_pending_per_issue index blocks
duplicate cards), and audited via notes/notifications. No model spend.
"""
import os, sys, glob, time, socket, subprocess
import repo_hygiene
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import agentic_repair

STUCK_RUNNING_H = float(os.environ.get("JANITOR_STUCK_RUNNING_H", "2"))
LOCK_STALE_MIN = float(os.environ.get("JANITOR_LOCK_STALE_MIN", "15"))
REQUEUE_CAP = int(os.environ.get("JANITOR_REQUEUE_CAP", "3"))
# Fast orphan recovery: a runner restart/crash strands its in-flight tasks in RUNNING (the claim is
# never released). Those stale rows hold lanes, so the fleet claims nothing new and goes idle — the
# exact stall a Mac restart caused. This threshold is well beyond the agentic coder timeout (~15 min),
# so a task RUNNING past it has already exceeded its own run and is orphaned, not live.
ORPHAN_RUNNING_MIN = float(os.environ.get("JANITOR_ORPHAN_RUNNING_MIN", "20"))

EMPTY_RUN_MARKERS = ("no committable changes", "empty diff", "diff is empty",
                     "no diff provided", "missing diff", "no code diff",
                     "agent run failed", "incomplete and truncated",
                     "what would you like to work on")


def _note_matches_empty(note):
    n = (note or "").lower()
    return any(m in n for m in EMPTY_RUN_MARKERS)


def _repair_task(task, category, detail, prefer_non_claude=False):
    directive = (
        "Resume this same task through an agentic coder. Inspect the existing branch/worktree/artifacts, "
        "preserve useful prior work, repair the technical issue, run the relevant checks, and commit."
    )
    patch = agentic_repair.repair_patch(
        task, detail, category=category, directive=directive, prefer_non_claude=prefer_non_claude
    )
    if "transient_retries" in task:
        patch["transient_retries"] = int(task.get("transient_retries") or 0)
    db.update("tasks", {"id": task["id"]}, patch)


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
            _repair_task(
                t,
                "orphaned-running",
                (t.get("note") or "") + f"\nTask was stuck RUNNING >{STUCK_RUNNING_H}h and hit the janitor retry cap. Do a final same-task repair and finish it.",
            )
        else:
            _repair_task(
                {**t, "transient_retries": attempts + 1},
                "orphaned-running",
                (t.get("note") or "") + f"\nTask was stuck RUNNING >{STUCK_RUNNING_H}h; resume and complete, do not restart blindly.",
            )
        try:
            db.insert("notifications", {"channel": "digest", "audience": os.environ.get("APPROVAL_PUSH_EMAIL", "kalepasch@gmail.com"),
                                        "kind": "janitor", "title": f"[janitor] unstuck '{t.get('slug')}' (main loop was wedged)",
                                        "body": "Task sat in RUNNING past the wedge threshold; assigned to same-task agentic repair.", "sent": False})
        except Exception:
            pass
        fixed += 1
    return fixed


def release_orphaned_running():
    """Release RUNNING tasks orphaned by a runner restart/crash, far faster than the 2h wedge detector.

    A RUNNING task untouched for ORPHAN_RUNNING_MIN minutes has exceeded the agentic coder timeout, so
    its worker is gone; the claim is dead but still holds a lane. Requeue it (account cleared) so the
    fleet can repair it, capped by transient_retries so a genuinely long task can't ping-pong forever.
    This is what stops a Mac restart from stranding in-flight work and starving the whole fleet."""
    fixed = 0
    cutoff = time.time() - ORPHAN_RUNNING_MIN * 60
    import datetime
    for t in db.select("tasks", {"select": "*", "state": "eq.RUNNING"}) or []:
        try:
            ts = datetime.datetime.fromisoformat(str(t.get("updated_at")).replace("Z", "+00:00")).timestamp()
        except Exception:
            continue
        if ts > cutoff:
            continue
        attempts = int(t.get("transient_retries") or 0)
        if attempts >= REQUEUE_CAP:
            _repair_task(
                t,
                "orphaned-running",
                (t.get("note") or "") + f"\nTask was orphaned RUNNING >{ORPHAN_RUNNING_MIN:.0f}m and hit the janitor cap. Resume/fix/commit rather than asking for manual intervention.",
            )
        else:
            _repair_task(
                {**t, "transient_retries": attempts + 1},
                "orphaned-running",
                (t.get("note") or "") + f"\nTask was orphaned RUNNING >{ORPHAN_RUNNING_MIN:.0f}m; resume existing work and finish.",
            )
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
    """The empty-diff/prompt-delivery class: repair via coder instead of waiting on a human."""
    fixed = 0
    for t in db.select("tasks", {"select": "*", "state": "eq.BLOCKED"}) or []:
        if not _note_matches_empty(t.get("note")):
            continue
        if "[janitor-requeued]" in (t.get("note") or "") and int(t.get("transient_retries") or 0) >= REQUEUE_CAP:
            continue
        _repair_task(
            {**t, "attempt": int(t.get("attempt") or 0) + 1,
             "transient_retries": int(t.get("transient_retries") or 0) + 1},
            "noop",
            (t.get("note") or "") + "\nPrevious run produced no committable changes; make the smallest concrete implementation and commit.",
        )
        fixed += 1
    return fixed


def refile_stranded_approvals():
    """BLOCKED awaiting-approval tasks are released back into automatic code-merge flow."""
    made = 0
    for t in db.select("tasks", {"select": "*", "state": "eq.BLOCKED"}) or []:
        if "awaiting your approval" not in (t.get("note") or ""):
            continue
        _repair_task(
            t,
            "approval",
            "Stale code-merge approval was removed. Continue the same task through automatic QA/merge and commit any missing work.",
        )
        made += 1
    return made


def _lock_has_live_holder(lock_path):
    """True if any live process currently has this lock file open.

    2026-07-10: age alone isn't sufficient proof a lock is abandoned -- a legitimately
    slow git operation (large gc, long rebase) could still be running past LOCK_STALE_MIN,
    and removing the lock out from under it risks a corrupted index. Verified manually via
    `lsof` before clearing a stale Sustainable_Barks lock that day; this makes that check
    automatic. Fail closed: if lsof itself can't be run, assume held and leave it alone --
    a lock that lingers an extra cycle is far cheaper than one yanked from a live writer.
    """
    try:
        out = subprocess.run(["lsof", "-t", lock_path], capture_output=True, text=True, timeout=10)
        return bool(out.stdout.strip())
    except Exception:
        return True


def clear_stale_git_locks():
    """Remove .git/*.lock files older than LOCK_STALE_MIN in repos on this machine, but
    only once no live process still has the file open (see _lock_has_live_holder)."""
    cleared = 0
    cutoff = time.time() - LOCK_STALE_MIN * 60
    for p in db.select("projects", {"select": "repo_path"}) or []:
        repo = p.get("repo_path") or ""
        if not repo or not os.path.isdir(os.path.join(repo, ".git")):
            continue
        for lock in glob.glob(os.path.join(repo, ".git", "*.lock")):
            try:
                if os.path.getmtime(lock) >= cutoff:
                    continue
                if _lock_has_live_holder(lock):
                    print(f"janitor: {lock} is stale by age but still held by a live process -- leaving it")
                    continue
                os.remove(lock)
                cleared += 1
                print(f"janitor: removed stale {lock}")
            except Exception:
                pass
    return cleared


def clean_stray_js_across_projects():
    """Periodic sweep (all registered repos on this machine) for untracked compiled .js
    files shadowing their .ts source in ESM projects -- see repo_hygiene.py. This catches
    the residue BEFORE an agent's own build/test attempt hits it, not just before
    merge_train's test gate (which has its own call to the same helper). 2026-07-10:
    tomorrow's server/ tree accumulated 4106 such files on one machine before this existed."""
    cleaned = 0
    for p in db.select("projects", {"select": "repo_path"}) or []:
        repo = p.get("repo_path") or ""
        if not repo or not os.path.isdir(os.path.join(repo, ".git")):
            continue
        try:
            cleaned += len(repo_hygiene.clean_stray_js_duplicates(repo))
        except Exception:
            continue
    return cleaned


def run():
    hb = scheduler_heartbeat()
    orphans = release_orphaned_running()
    stuck = requeue_stuck_running()
    merging = recover_stuck_merging()
    empty = requeue_empty_runs()
    refiled = refile_stranded_approvals()
    locks = clear_stale_git_locks()
    stray_js = clean_stray_js_across_projects()
    print(f"queue_janitor: heartbeat={'ok' if hb else 'FAIL'} orphans-released={orphans} unstuck={stuck} "
          f"merge-released={merging} empty-agentic-repair={empty} cards-refiled={refiled} locks-cleared={locks} "
          f"stray-js-cleaned={stray_js}")
    return orphans + stuck + merging + empty + refiled + locks + stray_js


if __name__ == "__main__":
    run()
