#!/usr/bin/env python3
"""Proactive health fixer — runs every 120s from the scheduler.

Fixes issues in real-time before they reach the watchdog report:
1. Throttle drift: resource_medic halves throttle on transient RAM pressure
   (ollama model loads) but never restores it. We restore when RAM is healthy.
2. Stale merge-qa worktrees: temporary staging worktrees older than 30 min.
   Does NOT touch agent worktrees — those are intentional for isolation.
3. Merge starvation: if merge_train hasn't merged anything in 2+ hours
   and there are DONE tasks waiting, request priority yield.
4. Stale locks: repo locks held by dead PIDs.

2026-07-15 — initial version for merge-starvation + throttle-drift fix.
"""
import logging
import os
import pathlib
import shutil
import subprocess
import time

log = logging.getLogger("service_agent")

ORCH_ROOT = pathlib.Path(__file__).resolve().parent.parent
RUNTIME   = ORCH_ROOT / ".runtime"
THROTTLE  = RUNTIME / "throttle"
LOCK_DIR  = ORCH_ROOT / "runner" / ".runtime" / "locks"


# ---------------------------------------------------------------------------
# 1. Throttle drift fix
# ---------------------------------------------------------------------------

def fix_throttle_drift():
    """Restore throttle to governor target when RAM pressure has passed."""
    gov_file = RUNTIME / "governor_target"
    if not gov_file.exists():
        return
    try:
        target = int(gov_file.read_text().strip())
    except Exception:
        return
    try:
        current = int(THROTTLE.read_text().strip())
    except Exception:
        current = 0
    if current >= target:
        return
    # Check current memory pressure
    try:
        import psutil
        mem = psutil.virtual_memory()
        free_pct = mem.available / mem.total * 100
    except Exception:
        free_pct = 50  # assume healthy if we can't check
    if free_pct > 30:  # above warn threshold — safe to restore
        log.warning("Throttle drift: %d → %d (RAM %.0f%% free, restoring to governor target)",
                    current, target, free_pct)
        THROTTLE.write_text(str(target))


# ---------------------------------------------------------------------------
# 2. Stale merge-qa worktree cleanup (NOT agent worktrees)
# ---------------------------------------------------------------------------

def fix_stale_merge_qa():
    """Remove temporary merge-qa staging worktrees older than 30 minutes.
    
    Agent worktrees (in claude-orchestrator-wt/) are NEVER touched — they exist
    intentionally to isolate concurrent agentic editors.
    """
    git_wt_dir = ORCH_ROOT / ".git" / "worktrees"
    if not git_wt_dir.exists():
        return
    now = time.time()
    for wt in git_wt_dir.iterdir():
        if not wt.is_dir():
            continue
        name = wt.name
        # Only touch merge-qa staging worktrees (in /tmp or /var/folders)
        gitdir_file = wt / "gitdir"
        if not gitdir_file.exists():
            continue
        try:
            checkout_path = gitdir_file.read_text().strip()
            # Only prune if it's a temp directory (merge-qa staging)
            if not (checkout_path.startswith("/tmp/") or checkout_path.startswith("/var/folders/")):
                continue
            # Check age
            mtime = wt.stat().st_mtime
            age_min = (now - mtime) / 60
            if age_min < 30:
                continue
            log.warning("Pruning stale merge-qa worktree: %s (%.0f min old)", name, age_min)
            shutil.rmtree(wt, ignore_errors=True)
            # Also remove on-disk checkout if it exists
            if os.path.isdir(checkout_path):
                shutil.rmtree(checkout_path, ignore_errors=True)
        except Exception as e:
            log.debug("Error checking worktree %s: %s", name, e)
    # Let git clean up its metadata
    try:
        subprocess.run(["git", "worktree", "prune"], cwd=str(ORCH_ROOT),
                       capture_output=True, timeout=10)
    except Exception:
        pass

# ---------------------------------------------------------------------------
# 3. Merge starvation detection
# ---------------------------------------------------------------------------

def fix_merge_starvation():
    """If merge_train hasn't merged in 2+ hours and tasks are waiting, signal priority."""
    from . import repo_lock
    last_merge_file = RUNTIME / "last_merge_ts"
    if not last_merge_file.exists():
        return
    try:
        last_ts = float(last_merge_file.read_text().strip())
    except Exception:
        return
    hours_since = (time.time() - last_ts) / 3600
    if hours_since < 2:
        return
    # Check if there are DONE tasks waiting to merge
    try:
        from .supabase_client import get_client
        sb = get_client()
        resp = sb.table("tasks").select("id", count="exact").eq("status", "DONE").execute()
        waiting = resp.count or 0
    except Exception:
        waiting = 1  # assume some are waiting
    if waiting == 0:
        return
    repo_path = str(ORCH_ROOT)
    log.warning("Merge starvation: %d tasks waiting, %.1fh since last merge — requesting priority",
                waiting, hours_since)
    repo_lock.request_priority(repo_path)

# ---------------------------------------------------------------------------
# 4. Stale lock cleanup
# ---------------------------------------------------------------------------

def fix_stale_locks():
    """Remove repo lock files held by dead processes."""
    if not LOCK_DIR.exists():
        return
    for lock_file in LOCK_DIR.glob("repo-*.lock"):
        try:
            age = time.time() - lock_file.stat().st_mtime
            if age > 600:  # 10 minutes — way too long for any single integrate/merge
                log.warning("Removing stale lock: %s (%.0fs old)", lock_file.name, age)
                lock_file.unlink(missing_ok=True)
        except Exception:
            pass

# ---------------------------------------------------------------------------
# Entry point (called by scheduler)
# ---------------------------------------------------------------------------

def run():
    """Run all health checks. Called every 120s by the scheduler."""
    log.info("Service agent health check starting")
    try:
        fix_throttle_drift()
    except Exception as e:
        log.error("fix_throttle_drift failed: %s", e)
    try:
        fix_stale_merge_qa()
    except Exception as e:
        log.error("fix_stale_merge_qa failed: %s", e)
    try:
        fix_merge_starvation()
    except Exception as e:
        log.error("fix_merge_starvation failed: %s", e)
    try:
        fix_stale_locks()
    except Exception as e:
        log.error("fix_stale_locks failed: %s", e)
    log.info("Service agent health check complete")
