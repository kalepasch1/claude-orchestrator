#!/usr/bin/env python3
"""
continuous_merger.py — event-driven merge pipeline that replaces batch merge-train scheduling.

Instead of waiting for a scheduled merge_train.train_run() call, this module
merges branches as soon as tasks complete. The runner calls
`on_task_done(task)` from set_state() whenever a task reaches DONE state.
The merger then:

  1. Looks up the task's branch and project
  2. Attempts a fast-forward merge onto the base branch
  3. If merge conflicts, runs auto_conflict_resolver on the branch
  4. If auto-resolution succeeds, commits the merge
  5. If auto-resolution fails, marks the branch for manual review
  6. Deletes the merged branch ref

This runs in a background thread so it doesn't block the runner's main loop.
Multiple merge requests are serialized per-project via a lock to avoid
concurrent git operations on the same repo.

Environment:
    ORCH_CONTINUOUS_MERGER_ENABLED  Kill switch (default: true)
    ORCH_CONTINUOUS_MERGER_WORKERS  Thread pool size (default: 2)
    ORCH_CONTINUOUS_MERGER_RETRY    Max retries on transient failure (default: 2)

Usage from runner.py:
    import continuous_merger
    # In set_state, when state == "DONE":
    continuous_merger.on_task_done(task_dict)
"""
from __future__ import annotations  # PY3.9 fleet: PEP-604 'str | None' annotations
# would raise TypeError at import time, making this whole module silently unimportable.
import os
import sys
import subprocess
import threading
import time
import traceback
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import db
except Exception:
    db = None

try:
    import auto_conflict_resolver
except Exception:
    auto_conflict_resolver = None

try:
    import log as _log_mod
    _log = _log_mod.get("continuous_merger")
except Exception:
    import logging
    _log = logging.getLogger("continuous_merger")

ENABLED = os.environ.get("ORCH_CONTINUOUS_MERGER_ENABLED", "true").lower() in (
    "true", "1", "yes", "on"
)
WORKERS = int(os.environ.get("ORCH_CONTINUOUS_MERGER_WORKERS", "2"))
MAX_RETRY = int(os.environ.get("ORCH_CONTINUOUS_MERGER_RETRY", "2"))
GIT_TIMEOUT = int(os.environ.get("ORCH_GIT_TIMEOUT", "90"))

# Per-project locks to serialize git operations
_project_locks: dict[str, threading.Lock] = defaultdict(threading.Lock)
_pool: ThreadPoolExecutor | None = None
_stats_lock = threading.Lock()
_stats = {
    "submitted": 0,
    "merged": 0,
    "auto_resolved": 0,
    "conflict": 0,
    "errors": 0,
    "skipped": 0,
}


def _ensure_pool():
    global _pool
    if _pool is None:
        _pool = ThreadPoolExecutor(max_workers=WORKERS, thread_name_prefix="cont-merger")
    return _pool


def _git(args, repo, timeout=GIT_TIMEOUT):
    """Run a git command, returning CompletedProcess. Never raises."""
    try:
        return subprocess.run(
            args, cwd=repo, capture_output=True, text=True,
            timeout=timeout, errors="replace"
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(args, 124, "", "timeout")
    except Exception as e:
        return subprocess.CompletedProcess(args, 1, "", str(e))


def _lookup_project(project_id: str) -> dict | None:
    """Fetch project details (repo_path, base_branch) from DB."""
    if not db:
        return None
    try:
        rows = db.select("projects", {"id": f"eq.{project_id}"})
        return rows[0] if rows else None
    except Exception:
        return None


def _merge_branch(repo: str, branch: str, base: str, task: dict) -> dict:
    """Attempt to merge a single branch into base.

    Returns:
        {"merged": bool, "strategy": str, "error": str|None, "sha": str|None}
        "sha" is the integrated commit (evidence for artifact_commit) when merged.
    """
    result = {"merged": False, "strategy": "none", "error": None, "sha": None}

    # NEVER destroy uncommitted work in the main checkout (added 2026-08-04).
    #
    # The `reset --hard` below used to run unconditionally. Combined with the missing
    # cross-process lock (see _process_task), this module silently reverted uncommitted
    # edits in the main checkout whenever any task completed — observed three times in one
    # day against in-flight operator/agent edits, including the very commit that was fixing
    # this class of bug. A merge job has no business discarding work it did not create.
    dirty = _git(["git", "status", "--porcelain", "--untracked-files=no"], repo).stdout.strip()
    if dirty:
        result["error"] = ("main checkout has uncommitted changes — refusing to reset; "
                           "branch left for the merge train")
        result["strategy"] = "skipped-dirty"
        return result

    # Ensure we're on base and clean
    _git(["git", "checkout", base], repo)
    _git(["git", "reset", "--hard", "HEAD"], repo)

    # Set git identity
    _git(["git", "config", "user.name", "kalepasch1"], repo)
    _git(["git", "config", "user.email", "kalepasch@gmail.com"], repo)

    # Check if branch exists
    check = _git(["git", "rev-parse", "--verify", branch], repo)
    if check.returncode != 0:
        result["error"] = f"branch {branch} does not exist"
        return result

    # Check if already an ancestor (already merged)
    ancestor = _git(["git", "merge-base", "--is-ancestor", branch, base], repo)
    if ancestor.returncode == 0:
        # Already merged — capture the integrated tip as evidence, then delete the branch ref
        tip = _git(["git", "rev-parse", branch], repo).stdout.strip()
        _git(["git", "branch", "-D", branch], repo)
        result["merged"] = True
        result["strategy"] = "already_ancestor"
        result["sha"] = tip or None
        return result

    # ALL merges — clean or conflicted — go through auto_conflict_resolver.resolve_branch,
    # which runs the fail-closed anti-loss gates (regression, divergent-authorship,
    # shadowed-stub) on EVERY committed merge and rolls back + preserves the branch on any
    # finding.
    #
    # HISTORY (fixed 2026-08-04, operator directive "improvements must never be lost to a
    # merge"): this function used to run its own bare `git merge` for the clean case and
    # only delegated to the resolver on conflict. A branch forked before an improvement
    # landed merges CLEANLY while reverting that improvement; this path then deleted the
    # branch — the only surviving copy. That unguarded clean path authored a large share of
    # the losses behind the 2026-08-04 phantom-merge reclassification (10,598 merges,
    # NO_EVIDENCE). FAIL-CLOSED: if the resolver (and with it the gate stack) cannot be
    # imported, no merge happens here at all.
    if auto_conflict_resolver is None:
        result["error"] = ("auto_conflict_resolver unavailable — unverified merges are "
                           "disabled (fail-closed); branch left for merge_train")
        result["strategy"] = "blocked"
        return result

    acr_result = auto_conflict_resolver.resolve_branch(repo, branch, base, dry_run=False)
    if acr_result.get("merged"):
        result["merged"] = True
        # Evidence: the merge commit sha — HEAD of the repo right after resolve_branch
        # committed the merge on base. Persisted as tasks.artifact_commit by the caller.
        head = _git(["git", "rev-parse", "HEAD"], repo).stdout.strip()
        result["sha"] = head or None
        strategy = acr_result.get("strategy", "clean")
        resolved = acr_result.get("resolved_files") or []
        result["strategy"] = (f"auto_resolved ({len(resolved)} files)"
                              if strategy == "auto" else strategy)
        return result

    err = acr_result.get("error")
    if not err:
        err = "manual files: " + str(acr_result.get("manual_files", []))
    result["error"] = f"auto-resolve failed: {err}"
    result["strategy"] = ("regression-blocked"
                          if acr_result.get("strategy") == "regression-blocked"
                          else "conflict")
    return result


def _process_task(task: dict):
    """Background worker: merge a completed task's branch."""
    project_id = task.get("project_id", "")
    task_id = task.get("id", "")
    slug = task.get("slug", "")
    branch = task.get("branch") or f"agent/{slug}"

    project = _lookup_project(project_id)
    if not project:
        _log.debug("continuous_merger: no project found for %s", project_id)
        with _stats_lock:
            _stats["skipped"] += 1
        return

    repo = project.get("repo_path", "")
    base = project.get("base_branch") or project.get("default_base") or "main"

    if not repo or not os.path.isdir(repo):
        _log.debug("continuous_merger: repo not found: %s", repo)
        with _stats_lock:
            _stats["skipped"] += 1
        return

    # Serialize git ops per project.
    #
    # CROSS-PROCESS LOCK (added 2026-08-04). _project_locks is a threading.Lock, so it only
    # serialized threads INSIDE this process. merge_train, release_train, branch_lease,
    # runner and worktree_isolation all coordinate through repo_lock.hold(), an fcntl.flock
    # on the repo — this module was the one merger that never took it. Two mergers could
    # therefore drive `git checkout` / `reset --hard` / `git merge` on the SAME repo at the
    # same instant. That is the "overlapping mergers" failure mode directly: interleaved
    # index writes, a train's in-progress state reset out from under it, and branches
    # deleted by one path while another was still reading them.
    #
    # Fail-safe by design: if another merger holds the repo we SKIP this cycle rather than
    # block a worker thread. The task stays DONE and the periodic merge_backlog() sweep (or
    # merge_train) picks it up on the next pass — nothing is lost by deferring.
    lock = _project_locks[project_id]
    try:
        import repo_lock
    except Exception:
        repo_lock = None
    with lock:
        _repo_guard = (repo_lock.hold(repo, timeout=120) if repo_lock
                       else _nullcontext_true())
        with _repo_guard as _got_repo:
            if repo_lock is not None and not _got_repo:
                _log.info("continuous_merger: %s busy (another merger holds the repo lock) "
                          "— deferring %s to the backlog sweep", repo, slug)
                with _stats_lock:
                    _stats["skipped"] += 1
                return
            return _merge_with_retries(repo, branch, base, task, slug, task_id,
                                       project_id)


class _nullcontext_true:
    """Stand-in when repo_lock is unavailable: proceed, but say so loudly."""

    def __enter__(self):
        _log.warning("continuous_merger: repo_lock unavailable — merging WITHOUT the "
                     "cross-process lock; concurrent mergers are possible")
        return True

    def __exit__(self, *exc):
        return False


def _merge_with_retries(repo, branch, base, task, slug, task_id, project_id):
    """The merge attempt loop, run while holding both the thread and repo locks."""
    if True:
        for attempt in range(MAX_RETRY + 1):
            try:
                merge_result = _merge_branch(repo, branch, base, task)

                if merge_result["merged"]:
                    strategy = merge_result["strategy"]
                    _log.info("continuous_merger: merged %s (%s)", slug, strategy)
                    with _stats_lock:
                        _stats["merged"] += 1
                        if "auto_resolved" in strategy:
                            _stats["auto_resolved"] += 1

                    # Update task state to MERGED — with commit evidence. Without a sha we
                    # cannot honestly certify MERGED (and the DB evidence gate would reject
                    # it), so fall back to DONE for merge_train to finish the job.
                    if db:
                        merge_sha = merge_result.get("sha") or ""
                        try:
                            if merge_sha:
                                db.update("tasks", {"id": task_id},
                                          {"state": "MERGED",
                                           "artifact_commit": merge_sha,
                                           "note": f"continuous-merger: {strategy} @ {merge_sha[:12]}",
                                           "updated_at": "now()"})
                            else:
                                db.update("tasks", {"id": task_id},
                                          {"state": "DONE",
                                           "note": f"continuous-merger: {strategy} but no merge sha "
                                                   "captured — left DONE for merge_train",
                                           "updated_at": "now()"})
                        except Exception:
                            pass

                    # Release file reservations
                    try:
                        import file_reservation
                        file_reservation.release(task)
                    except Exception:
                        pass
                    return

                else:
                    error = merge_result.get("error", "unknown")
                    if attempt < MAX_RETRY and "timeout" in str(error).lower():
                        _log.debug("continuous_merger: retrying %s (attempt %d): %s",
                                   slug, attempt + 1, error)
                        time.sleep(2)
                        continue

                    # SELF-HEALING MERGE: decompose the conflicting branch into
                    # mergeable sub-branches and focused repair tasks
                    try:
                        import self_healing_merge
                        heal_result = self_healing_merge.heal(
                            repo, branch, base, project_id=project_id
                        )
                        if heal_result.get("healed"):
                            _log.info("continuous_merger: self-healed %s: %s",
                                      slug, heal_result["reason"])
                            with _stats_lock:
                                _stats["merged"] += heal_result.get("merged", 0)
                            if db:
                                try:
                                    db.update("tasks", {"id": task_id},
                                              {"note": f"self-healed: {heal_result['reason'][:400]}",
                                               "updated_at": "now()"})
                                except Exception:
                                    pass
                            return
                    except Exception as _heal_err:
                        _log.debug("continuous_merger: self-healing failed: %s", _heal_err)

                    _log.info("continuous_merger: conflict on %s: %s", slug, error)
                    with _stats_lock:
                        _stats["conflict"] += 1

                    # Update task with conflict note
                    if db:
                        try:
                            db.update("tasks", {"id": task_id},
                                      {"note": f"continuous-merger-conflict: {error[:500]}",
                                       "updated_at": "now()"})
                        except Exception:
                            pass
                    return

            except Exception as e:
                _log.error("continuous_merger: error merging %s: %s", slug, e)
                if attempt < MAX_RETRY:
                    time.sleep(2)
                    continue
                with _stats_lock:
                    _stats["errors"] += 1
                return


def on_task_done(task: dict):
    """Called by runner.py when a task reaches DONE state.

    Submits the merge job to the background thread pool.
    Non-blocking — returns immediately.
    """
    if not ENABLED:
        return

    slug = task.get("slug", "")
    if not slug:
        return

    with _stats_lock:
        _stats["submitted"] += 1

    pool = _ensure_pool()
    try:
        pool.submit(_process_task, task)
    except Exception as e:
        _log.error("continuous_merger: failed to submit %s: %s", slug, e)
        with _stats_lock:
            _stats["errors"] += 1


def merge_backlog(project_id: str = ""):
    """Periodic sweep: attempt to merge any DONE tasks that haven't been merged yet.

    This catches tasks that completed while the merger was down, or that
    failed on first attempt but may now be mergeable (because other branches
    merged, advancing the base).
    """
    if not ENABLED or not db:
        return {"swept": 0, "merged": 0}

    filters = {"state": "eq.DONE"}
    if project_id:
        filters["project_id"] = f"eq.{project_id}"

    try:
        tasks = db.select("tasks", filters) or []
    except Exception:
        return {"swept": 0, "merged": 0, "error": "db query failed"}

    swept = 0
    merged = 0
    for t in tasks:
        swept += 1
        on_task_done(t)

    return {"swept": swept, "submitted": swept}


def stats() -> dict:
    """Return current merger statistics."""
    with _stats_lock:
        return dict(_stats)


def shutdown():
    """Gracefully shut down the thread pool."""
    global _pool
    if _pool:
        _pool.shutdown(wait=True, cancel_futures=False)
        _pool = None


# ── Standalone mode ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    """Run a backlog sweep across all projects."""
    print("continuous_merger: running backlog sweep...")
    result = merge_backlog()
    print(f"continuous_merger: swept {result.get('swept', 0)} tasks")
    # Wait for pool to finish
    if _pool:
        _pool.shutdown(wait=True)
    final = stats()
    print(f"continuous_merger: {final}")
