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
import datetime, json, os, stat, sys, glob, time, socket, subprocess
import repo_hygiene
import host_resume_watch
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
# A Git writer first creates tmp_obj_* files before atomically installing the
# object.  A crash can leave them behind indefinitely.  Never delete them: move
# only cold files to Git's recovery area, and pin any dangling commits first.
GIT_TMP_OBJECT_STALE_MIN = float(os.environ.get("JANITOR_GIT_TMP_OBJECT_STALE_MIN", "30"))
SECONDS_PER_MINUTE = 60
# Ceiling on unlinks per repo per cycle. On 2026-09-08 one repo held 2,642 abandoned
# lockfiles; sweeping them is fine, but an unbounded loop inside a 300s janitor cycle is
# not. Anything past the cap is left for the next cycle and reported as `remaining`, which
# is what makes a sweeper that is falling behind visible instead of silent.
LOCK_SWEEP_CAP = int(os.environ.get("JANITOR_LOCK_SWEEP_CAP", "5000"))
# How many lock paths go into one `lsof` invocation. One lsof per lockfile is what the
# obvious implementation does, and at 2,642 locks that is 2,642 subprocess spawns inside a
# 300s janitor cycle -- the sweep would time out before it cleared the backlog it exists
# to clear. Batched, the same repo costs a single-digit number of spawns. The bound is
# argv length, not lsof.
LOCK_HOLDER_BATCH = int(os.environ.get("JANITOR_LOCK_HOLDER_BATCH", "500"))
LOCK_HOLDER_TIMEOUT_S = int(os.environ.get("JANITOR_LOCK_HOLDER_TIMEOUT_S", "30"))
# Subtrees of the Git directory that hold lockfiles. Deliberately enumerated rather than
# walking the whole Git directory: objects/ contains tmp_obj_* files that belong to
# archive_stale_git_objects (it pins dangling commits into recovery refs before touching
# them), and nothing in this sweep may race that.
LOCK_SEARCH_SUBDIRS = ("refs", os.path.join("logs", "refs"), "worktrees")
# `locked` is a user-written "do not prune this worktree" MARKER, not a lockfile, and
# `gc.pid` is git's own liveness record. Neither is ours to remove.
NEVER_SWEEP_BASENAMES = frozenset({"locked", "gc.pid"})

EMPTY_RUN_MARKERS = ("no committable changes", "empty diff", "diff is empty",
                     "no diff provided", "missing diff", "no code diff",
                     "agent run failed", "incomplete and truncated",
                     "what would you like to work on")


def _note_matches_empty(note):
    n = (note or "").lower()
    if not any(m in n for m in EMPTY_RUN_MARKERS):
        return False
    # An empty diff because the agent produced nothing is a failed run and this
    # module should repair it. An empty diff because the executor INSPECTED the
    # repo and reported there is nothing to build is an answer, and requeueing
    # it deletes the answer. The two look identical from the diff alone, which
    # is why the marker exists and why the check has to live here rather than in
    # EMPTY_RUN_MARKERS -- a NO-ARTIFACT-JUSTIFIED note routinely explains
    # itself using the words "no committable changes".
    #
    # Imported from auto_remediate rather than re-stated so both requeue doors
    # answer with one rule. A second copy would drift, and when it drifts these
    # tasks quietly start looping again.
    try:
        import auto_remediate
        if auto_remediate.is_terminal_closure(note):
            return False
    except Exception:
        pass
    return True


def _repair_task(task, category, detail, prefer_non_claude=False):
    directive = (
        "Resume this same task through an agentic coder. Inspect the existing branch/worktree/artifacts, "
        "preserve useful prior work, repair the technical issue, run the relevant checks, and commit."
    )
    patch = agentic_repair.repair_patch(
        task, detail, category=category, directive=directive, prefer_non_claude=prefer_non_claude
    )
    if "transient_retries" in task and not agentic_repair.is_terminal(patch):
        # THE INCREMENT LIVES HERE, AND ONLY HERE.
        #
        # Was `= int(...or 0)` — it PRESERVED the counter instead of advancing it, so every
        # transient_retries-based cap elsewhere in the fleet stayed frozen at the same value no
        # matter how many times the janitor re-queued the row. Advancing it is the whole point of
        # writing the field back.
        #
        # But the three below-cap call sites were ALREADY passing
        # `{**t, "transient_retries": attempts + 1}`, so adding the increment
        # here made every janitor pass count as two: a row at 1 went to 3, and
        # REQUEUE_CAP (3) was reached in two sweeps instead of three. Those
        # pre-increments are gone; the callers hand over the row as they read it.
        #
        # At or above the cap the counter HOLDS. The at-cap branch is the final
        # same-task repair, not another retry, and letting it climb would make
        # "how many times did the janitor retry this" unreadable after the fact.
        attempts = int(task.get("transient_retries") or 0)
        patch["transient_retries"] = attempts + 1 if attempts < REQUEUE_CAP else attempts
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
                prefer_non_claude=True,
            )
        else:
            _repair_task(
                t,
                "orphaned-running",
                (t.get("note") or "") + f"\nTask was stuck RUNNING >{STUCK_RUNNING_H}h; resume and complete, do not restart blindly.",
                prefer_non_claude=True,
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
        # COWORK DISPATCH: tasks claimed by Cowork sessions are NOT orphans — they run
        # in a separate Cowork execution context, not as a local subprocess. The janitor
        # can't see Cowork processes, so it must trust the account prefix and leave them alone.
        acct = (t.get("account") or "")
        if acct.startswith("cowork-"):
            continue
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
                prefer_non_claude=True,
            )
        else:
            _repair_task(
                t,
                "orphaned-running",
                (t.get("note") or "") + f"\nTask was orphaned RUNNING >{ORPHAN_RUNNING_MIN:.0f}m; resume existing work and finish.",
                prefer_non_claude=True,
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
            {**t, "attempt": int(t.get("attempt") or 0) + 1},
            "noop",
            (t.get("note") or "") + "\nPrevious run produced no committable changes; make the smallest concrete implementation and commit.",
        )
        fixed += 1
    return fixed


def refile_stranded_approvals():
    """BLOCKED awaiting-approval tasks are released into automatic code-merge flow."""
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


def _candidate_lock_paths(git_dir):
    """Every lockfile path under one Git directory, top level and nested.

    THE BUG THIS FUNCTION EXISTS TO FIX. Until 2026-09-08 clear_stale_git_locks globbed
    `.git/*.lock` and nothing else -- top level only. On 2026-09-02 a `git fetch --prune`
    was SIGKILLed by its caller's 30s subprocess timeout mid-transaction, and a prune
    holds a lock on EVERY ref it intends to delete simultaneously, so it left 2,642
    abandoned lockfiles: 888 under refs/heads, 1,746 under refs/remotes/origin, 8 under
    refs/orch-rescue. Not one of them was at the top level. The janitor ran on schedule
    for five days, cleared its usual index.lock / packed-refs.lock, and stepped over all
    2,642 every single cycle.

    What that cost, measured: `git fetch --prune` aborts the WHOLE deletion batch on the
    first lock it cannot take ("could not delete references: cannot lock ref ...: File
    exists"), so it printed 65 deletions and performed none. The local branch view sat 95
    branches out of date for five days, and 27 `fleet_control: auto-pull failed` lines in
    runner.log are the same root cause going unread. A sibling repo still held 555.

    objects/ is excluded on purpose -- see LOCK_SEARCH_SUBDIRS.
    """
    found = [path for path in glob.glob(os.path.join(git_dir, "*.lock"))]
    for subdir in LOCK_SEARCH_SUBDIRS:
        for parent, _dirnames, filenames in os.walk(os.path.join(git_dir, subdir)):
            for filename in filenames:
                if filename.endswith(".lock"):
                    found.append(os.path.join(parent, filename))
    return found


def _held_in_one_batch(batch):
    """Which paths in this one batch some live process has open.

    Returns the WHOLE batch when lsof cannot answer -- see _held_lock_paths for why that
    is the safe default rather than the empty set.
    """
    try:
        out = subprocess.run(["lsof", "-F", "n", "--", *batch],
                             capture_output=True, text=True,
                             timeout=LOCK_HOLDER_TIMEOUT_S)
    except Exception as error:
        print(f"janitor: lsof failed for {len(batch)} lock paths ({error}) -- treating "
              f"them all as held")
        return set(batch)
    # lsof exits nonzero when it simply found nothing open, which is the normal and
    # expected answer here, so the exit code is not a failure signal. Only an exception
    # (missing binary, timeout) means we did not get an answer.
    return {line[1:] for line in out.stdout.splitlines() if line.startswith("n")}


def _held_lock_paths(lock_paths):
    """Which of these lockfiles some live process currently has open.

    Batched on purpose -- see LOCK_HOLDER_BATCH. `lsof -F n` prints one `n<name>` line per
    open file, so a single invocation answers for hundreds of paths at once.

    FAILS CLOSED, per batch. If lsof cannot be run, or times out, every path in that batch
    is reported as held and survives this cycle. A lock that lingers an extra 300 seconds
    is far cheaper than one yanked out from under a live writer: git keeps the descriptor
    from hold_lock_file_for_update() open until it commits or rolls back, so a live writer
    is visible here for the whole life of its lock, and losing that signal must never be
    read as "nobody has it".
    """
    held = set()
    for start in range(0, len(lock_paths), LOCK_HOLDER_BATCH):
        batch = lock_paths[start:start + LOCK_HOLDER_BATCH]
        held.update(_held_in_one_batch(batch))
    return held


def _lock_is_abandoned(lock_path, cutoff, held_paths=None):
    """Whether one lockfile may be removed. Returns (verdict, reason). Never raises.

    NOTE WHAT IS DELIBERATELY ABSENT: file size.

    A ref DELETION -- exactly what `git fetch --prune` does, and what produced all 2,642
    of the 2026-09-02 locks -- takes the lock and never writes a value into it. Zero bytes
    is the normal shape of a LIVE prune's lock. Conversely a writer killed after it had
    written the new object id leaves a NONZERO abandoned lock, and that is the index.lock
    class that silently blocks every merge. Size tells you which git operation it was,
    never whether its writer is alive; gating on it would keep live locks and miss dead
    ones, in both directions. It is reported in the journal and never tested.
    """
    try:
        lock_stat = os.lstat(lock_path)
    except OSError:
        return False, "vanished"
    if not stat.S_ISREG(lock_stat.st_mode):
        return False, "not-a-regular-file"
    if os.path.basename(lock_path) in NEVER_SWEEP_BASENAMES:
        return False, "not-a-lockfile"
    if lock_stat.st_mtime >= cutoff:
        return False, "too-young"
    if held_paths is None:
        if _lock_has_live_holder(lock_path):
            return False, "live-holder"
    elif lock_path in held_paths:
        return False, "live-holder"
    return True, "abandoned"


def _remove_if_unchanged(lock_path, expected_identity):
    """Unlink only if the file is still the exact one that was cleared.

    Closes the window between the decision and the syscall: a git that grabbed this path
    in between has a different inode, so the comparison fails and nothing happens. Hitting
    the residual window needs a fresh lock that reuses both the same inode number and the
    same nanosecond mtime.
    """
    try:
        current = os.lstat(lock_path)
        if (current.st_ino, current.st_mtime_ns) != expected_identity:
            return False
        os.remove(lock_path)
        return True
    except OSError:
        return False


def clear_stale_git_locks():
    """Remove abandoned Git lockfiles anywhere under each repo's Git directory.

    Two guards decide, and both must pass: the lock has been untouched for
    LOCK_STALE_MIN (15 min, three times the longest git invocation the fleet permits --
    every git call in runner/ is bounded at <=300s and is killed by its caller past that,
    so no legitimate writer can still hold a lock), and no live process has it open
    (_lock_has_live_holder, which fails CLOSED). A lock that lingers an extra cycle is far
    cheaper than one yanked from a live writer.

    _git_dir is used rather than repo/".git" so a linked worktree, whose .git is a FILE,
    is swept instead of skipped.
    """
    cleared = 0
    cutoff = time.time() - LOCK_STALE_MIN * SECONDS_PER_MINUTE
    for project in db.select("projects", {"select": "repo_path"}) or []:
        repo = project.get("repo_path") or ""
        if not repo or not os.path.exists(os.path.join(repo, ".git")):
            continue
        git_dir = _git_dir(repo)
        if not git_dir:
            continue
        removed = held = 0
        oldest_age_min = 0.0
        candidates = _candidate_lock_paths(git_dir)
        held_paths = _held_lock_paths(candidates) if candidates else set()
        for lock in candidates:
            if removed >= LOCK_SWEEP_CAP:
                break
            try:
                identity = (os.lstat(lock).st_ino, os.lstat(lock).st_mtime_ns)
                age_min = (time.time() - os.path.getmtime(lock)) / SECONDS_PER_MINUTE
                verdict, reason = _lock_is_abandoned(lock, cutoff, held_paths)
                if not verdict:
                    if reason == "live-holder":
                        held += 1
                        print(f"janitor: {lock} is stale by age but still held by a live "
                              f"process -- leaving it")
                    continue
                if _remove_if_unchanged(lock, identity):
                    removed += 1
                    cleared += 1
                    oldest_age_min = max(oldest_age_min, age_min)
            except Exception:
                pass
        # Counts only locks that are PAST the cutoff and still there -- never a lock a
        # live git took thirty seconds ago. Counting young locks would make
        # `stale-git-locks-not-cleared` fire on every healthy repo on every cycle, and an
        # alert that is always on is the same as no alert. This backlog is exactly what
        # went unnoticed for five days, so it has to stay meaningful.
        remaining = sum(1 for path in _candidate_lock_paths(git_dir)
                        if _lock_is_abandoned(path, cutoff, set())[0])
        if removed or remaining:
            _journal_lock_sweep(repo, removed, remaining, held, oldest_age_min)
    return cleared


def _journal_lock_sweep(repo, removed, remaining, held, oldest_age_min):
    """One row per repo per cycle -- never one per file.

    2,642 rows would drown the file resource_medic._recent_events reads, and drowning it
    is how the NEXT recurrence goes unnoticed for five days the way this one did. A sweep
    that leaves locks behind writes a DISTINCT action, so "the self-healing is itself
    broken" is a separately countable event rather than a quieter version of success.
    """
    action = "cleared-stale-git-locks" if not remaining else "stale-git-locks-not-cleared"
    detail = (f"repo={repo} removed={removed} remaining={remaining} held={held} "
              f"oldest_age_min={oldest_age_min:.0f}")
    try:
        import resource_medic
        resource_medic.journal("git_hygiene", action, detail)
        return True
    except Exception as error:
        print(f"janitor: {action} {detail} (journal unavailable: {error})")
        return False


def _git_dir(repo):
    """Return the canonical Git directory, or an empty string on failure."""
    try:
        out = subprocess.run(["git", "rev-parse", "--git-dir"], cwd=repo,
                             capture_output=True, text=True, timeout=20)
        if out.returncode:
            return ""
        path = out.stdout.strip()
        return path if os.path.isabs(path) else os.path.join(repo, path)
    except Exception:
        return ""


def archive_stale_git_objects(repo, stale_min=None, now=None):
    """Preserve stale Git write debris without pruning recoverable work.

    This deliberately does *not* run ``git gc``.  It first creates durable
    recovery refs for dangling commits, then moves only old ``tmp_obj_*`` files
    out of ``objects/``.  Any live/recent writer or lock makes the operation a
    no-op, preventing a cleanup race from corrupting a repository.
    """
    git_dir = _git_dir(repo)
    if not git_dir:
        return {"refs": 0, "objects": 0}
    stale_seconds = (GIT_TMP_OBJECT_STALE_MIN if stale_min is None else stale_min) * 60
    current = time.time() if now is None else now
    locks = glob.glob(os.path.join(git_dir, "*.lock"))
    if any(_lock_has_live_holder(lock) or os.path.getmtime(lock) > current - stale_seconds for lock in locks):
        return {"refs": 0, "objects": 0}
    objects = []
    for prefix in glob.glob(os.path.join(git_dir, "objects", "[0-9a-f][0-9a-f]")):
        for path in glob.glob(os.path.join(prefix, "tmp_obj_*")):
            try:
                if os.path.getmtime(path) <= current - stale_seconds:
                    objects.append(path)
            except OSError:
                continue
    # No stale writer debris means there is no recovery event to process.
    if not objects:
        return {"refs": 0, "objects": 0}
    stamp = datetime.datetime.fromtimestamp(current, datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    recovered = 0
    try:
        fsck = subprocess.run(["git", "fsck", "--connectivity-only", "--no-reflogs"], cwd=repo,
                              capture_output=True, text=True, timeout=180)
        commits = {
            line.rsplit(" ", 1)[-1] for line in fsck.stdout.splitlines()
            if line.startswith("dangling commit ")
        }
        for sha in commits:
            ref = f"refs/recovery/git-write-{stamp}/{sha}"
            exists = subprocess.run(["git", "show-ref", "--verify", "--quiet", ref], cwd=repo,
                                    capture_output=True, timeout=20)
            if exists.returncode == 0:
                continue
            pin = subprocess.run(["git", "update-ref", ref, sha], cwd=repo,
                                 capture_output=True, text=True, timeout=20)
            if pin.returncode == 0:
                recovered += 1
    except Exception:
        # A failed inventory must never lead to removal/movement of objects.
        return {"refs": 0, "objects": 0}
    archive = os.path.join(git_dir, "recovery", "stale-git-objects", stamp)
    moved = []
    try:
        for path in objects:
            destination = os.path.join(archive, os.path.basename(os.path.dirname(path)), os.path.basename(path))
            os.makedirs(os.path.dirname(destination), exist_ok=True)
            os.replace(path, destination)
            moved.append({"source": path, "archive": destination})
        with open(os.path.join(archive, "manifest.json"), "w") as handle:
            json.dump({"created_at": stamp, "repo": os.path.realpath(repo), "objects": moved}, handle, indent=2)
    except OSError:
        # Files already moved remain archived; this is recoverable and never a discard.
        pass
    return {"refs": recovered, "objects": len(moved)}


def archive_stale_git_objects_across_projects():
    refs = objects = 0
    for project in db.select("projects", {"select": "repo_path"}) or []:
        repo = project.get("repo_path") or ""
        if not repo or not os.path.isdir(repo):
            continue
        result = archive_stale_git_objects(repo)
        refs += result["refs"]
        objects += result["objects"]
    return refs, objects


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


def check_vue_templates_across_projects():
    """Periodic sweep (all registered repos on this machine) for .vue components that do
    not compile -- see repo_hygiene.check_vue_templates.

    2026-08-29: an agent converted 421 hardcoded hex values to design tokens across 59
    .vue files in one pass, and several of the edits appended an attribute to an element
    that already had one. Every one is a hard compile error, and nothing noticed: the
    TypeScript lints do not read templates. They were found one at a time, by hand, when
    the local dev server refused to serve a page -- six over one afternoon.

    Reported rather than repaired. A duplicated attribute has two plausible fixes (merge
    the values, or drop one) and picking wrong silently changes what renders, so this
    surfaces the file and line and leaves the decision to whoever is working. Returns a
    list of (repo, detail)."""
    try:
        projects = db.select("projects", {"select": "repo_path"}) or []
    except Exception:
        return []
    broken = []
    for p in projects:
        repo = p.get("repo_path") or ""
        if not repo or not os.path.isdir(os.path.join(repo, ".git")):
            continue
        # check_vue_templates never raises — it returns (True, reason) when it
        # cannot look. So there is nothing to guard here.
        ok, detail = repo_hygiene.check_vue_templates(repo)
        if not ok:
            broken.append((repo, detail))
    return broken


def run():
    hb = scheduler_heartbeat()
    orphans = release_orphaned_running()
    stuck = requeue_stuck_running()
    merging = recover_stuck_merging()
    empty = requeue_empty_runs()
    refiled = refile_stranded_approvals()
    locks = clear_stale_git_locks()
    recovery_refs, archived_objects = archive_stale_git_objects_across_projects()
    stray_js = clean_stray_js_across_projects()
    broken_vue = check_vue_templates_across_projects()   # fail-soft; returns [] on error
    try:
        hosts_resumed, hosts_checked = host_resume_watch.check_and_resume()
    except Exception as e:
        print(f"queue_janitor: host_resume_watch failed: {e}")
        hosts_resumed, hosts_checked = 0, 0
    # Printed in full, not counted. A component that will not compile breaks the
    # build and the local dev server, and the message already names the file and
    # line -- burying that in a tally would waste the only useful part.
    for repo, detail in broken_vue:
        print(f"queue_janitor: ✗ {repo} has a component that will not compile:\n{detail}")
    print(f"queue_janitor: heartbeat={'ok' if hb else 'FAIL'} orphans-released={orphans} unstuck={stuck} "
          f"merge-released={merging} empty-agentic-repair={empty} cards-refiled={refiled} locks-cleared={locks} "
          f"recovery-refs={recovery_refs} stale-git-objects-archived={archived_objects} stray-js-cleaned={stray_js} "
          f"broken-vue-repos={len(broken_vue)} "
          f"hosts-checked={hosts_checked} hosts-resumed={hosts_resumed}")
    return orphans + stuck + merging + empty + refiled + locks + recovery_refs + archived_objects + stray_js + hosts_resumed


if __name__ == "__main__":
    run()
