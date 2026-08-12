#!/usr/bin/env python3
"""Fail-closed task worktree creation and validation."""
from __future__ import annotations

import logging
import os
import shutil
import subprocess

import repo_lock
from typing import Optional

log = logging.getLogger(__name__)


class WorktreeIsolationError(RuntimeError):
    """An isolated task checkout could not be proven safe."""


def task_worktree_path(repo: str, slug: str) -> str:
    repo = os.path.realpath(repo)
    return os.path.join(os.path.dirname(repo), os.path.basename(repo) + "-wt", slug)


def owner_marker_path(repo: str, slug: str) -> str:
    wt_root = os.path.dirname(task_worktree_path(repo, slug))
    return os.path.join(wt_root, ".orchestrator-owners", slug)


def validate_owner(repo: str, slug: str, task_id: str, lease_token: str) -> None:
    try:
        with open(owner_marker_path(repo, slug), encoding="utf-8") as marker:
            lines = [line.rstrip("\n") for line in marker.readlines()[:3]]
    except OSError as exc:
        raise WorktreeIsolationError("worktree owner marker is missing") from exc
    if lines[:2] != [task_id, lease_token]:
        raise WorktreeIsolationError("worktree is owned by another task or lease")


def owner_claim(repo: str, slug: str) -> Optional[list]:
    """Return the [task_id, lease_token, branch] recorded for `slug`, or None."""
    try:
        with open(owner_marker_path(repo, slug), encoding="utf-8") as marker:
            return [line.rstrip("\n") for line in marker.readlines()[:3]]
    except OSError:
        return None


def reclaim_reason(repo: str, slug: str, task_id: str) -> Optional[str]:
    """Why a leftover worktree may be reclaimed by `task_id`, or None if it may not.

    This guard exists to stop one task bulldozing ANOTHER task's checkout. It must not
    stop a task from reclaiming a checkout that no other task owns. Two such cases:

    * The marker is missing - the worktree predates the ownership guard, or GC dropped
      the marker but left the directory. On 2026-08-02, 238 of 240 worktrees across this
      fleet were in exactly this state, and every one PERMANENTLY wedged its task:
      validate_owner() raised "owner marker is missing", the runner set RETRY, and
      worktree_gc skipped the directory because setup-worktrees.sh had `git worktree
      lock`ed it. Nothing ever wrote the marker, so agent/<slug> was never created and
      the merge train waited forever. Zero tasks completed.

    * The marker names THIS task under a superseded lease token. branch_lease.acquire()
      mints a fresh uuid4 on EVERY call, so a task interrupted by a runner restart,
      timeout or RETRY can never present the token its own previous attempt recorded.
      Owner markers are per-machine, so a same-task marker here is our own corpse.

    * The marker names a task id that is no longer RUNNING - see _owner_is_live() below.

    A marker naming a DIFFERENT task that is still RUNNING is refused - that is the real
    collision the guard was written for, and the branch lease remains the cross-machine
    authority.
    """
    claim = owner_claim(repo, slug)
    if claim is None or not any(str(c).strip() for c in claim):
        return "no owner marker (pre-guard or GC-dropped worktree)"
    if claim[0] == task_id:
        return "owned by this task under a superseded lease token"
    if not _owner_is_live(claim[0]):
        return "owner task %s is no longer RUNNING (stale marker for this slug)" % (
            str(claim[0])[:12],
        )
    return None


def _owner_is_live(owner_task_id: str) -> bool:
    """Is the task named in an owner marker still RUNNING?

    A worktree path is derived from the SLUG, so any marker found there belongs to this
    slug's work. But this fleet recreates task rows for the same slug with a fresh uuid
    (decomposition, respawn, re-insert), and the new row can never present the old row's
    id. On 2026-08-03 that wedged ~20 tasks per 20 minutes with "worktree is owned by
    another task or lease": they claimed a lane, could not get their own checkout, and went
    straight back to QUEUED without ever running. A dead owner is a corpse, not a collision.

    Fails CLOSED. Any error, or an owner row that is genuinely RUNNING, returns True so the
    caller refuses the reclaim exactly as it did before this change. Only a definitive "that
    row exists and is not RUNNING", or "that row no longer exists", frees the worktree.
    """
    owner_task_id = str(owner_task_id or "").strip()
    if not owner_task_id:
        return False
    try:
        import db
        rows = db.select("tasks", {"select": "id,state", "id": "eq.%s" % owner_task_id,
                                   "limit": "1"})
    except Exception:
        return True   # cannot tell -> behave exactly as before
    if rows is None:
        return True
    if not rows:
        return False  # the owning row is gone; nothing left to collide with
    return str(rows[0].get("state") or "").upper() == "RUNNING"


def _git(repo: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, timeout=120
    )


#: Branches whose worktree is NEVER disposable. These are integration and
#: release lines an operator works in directly; an agent worktree is always
#: `agent/<slug>`, so nothing here can be a task checkout.
DEFAULT_RESERVED_BRANCHES = ("orchestrator/dev", "master", "main", "production")

#: Drop this file at a worktree root to protect it regardless of branch.
RESERVED_MARKER = ".orchestrator-reserved"


def reserved_branches() -> tuple:
    raw = os.environ.get("ORCH_RESERVED_BRANCHES", "").strip()
    if not raw:
        return DEFAULT_RESERVED_BRANCHES
    return tuple(b.strip() for b in raw.split(",") if b.strip())


def reserved_worktree_reason(repo: str, wt: str) -> Optional[str]:
    """Why `wt` must never be force-removed or reused as a task checkout.

    WHY THIS EXISTS (2026-08-12). `approval_merge._free_branch()` resolves a
    branch to whichever worktree holds it and runs `git worktree remove --force`
    on it. Its only exemption was the PRIMARY checkout — so any LINKED worktree
    was fair game, including the one an operator has the integration branch
    checked out in. Observed the same night: an agent wrote into
    apparently-wt/promote-20260811 (holding orchestrator/dev) while it was in
    use, leaving a conflicted index with no MERGE_HEAD and four raw conflict
    markers in a tracked .ts file. `--force` would not have stopped at
    uncommitted work.

    `validate_task_worktree()` below already refuses anything whose branch is
    not `agent/<slug>`, which is the same invariant — but the destructive paths
    in approval_merge and self_healing_merge never call it. This is that
    invariant, factored out so those paths can share it rather than growing a
    second, weaker copy.

    Returns a reason string when the worktree is protected, else None.
    """
    repo = os.path.realpath(repo)
    wt_real = os.path.realpath(wt)

    if wt_real == repo:
        return "it is the primary checkout"

    if os.path.exists(os.path.join(wt_real, RESERVED_MARKER)):
        return f"it carries a {RESERVED_MARKER} marker"

    branch = _git(wt_real, "symbolic-ref", "--quiet", "--short", "HEAD")
    name = branch.stdout.strip() if not branch.returncode else ""

    if not name:
        # Detached HEAD is not provably a task checkout, and force-removing it
        # discards whatever it holds. Refuse rather than guess.
        return "its HEAD is detached, so it cannot be shown to be a task worktree"

    if name in reserved_branches():
        return f"it has the reserved branch {name} checked out"

    if not name.startswith("agent/"):
        # The positive form of the rule: only agent/<slug> checkouts are
        # disposable. Anything else is someone's working tree.
        return f"its branch {name} is not an agent/<slug> task branch"

    return None


def is_disposable_worktree(repo: str, wt: str) -> bool:
    """True when `wt` is a task checkout that may be force-removed."""
    return reserved_worktree_reason(repo, wt) is None


def is_nested_in(child: str, parent: str) -> bool:
    """True if `child` lives inside `parent` (not equal to it)."""
    child = os.path.realpath(child)
    parent = os.path.realpath(parent)
    if child == parent:
        return False
    try:
        return os.path.commonpath([child, parent]) == parent
    except ValueError:  # different drives / unrelated roots
        return False


def validate_task_worktree(repo: str, slug: str, worktree: Optional[str] = None) -> str:
    repo = os.path.realpath(repo)
    wt = os.path.realpath(worktree or task_worktree_path(repo, slug))
    if wt == repo:
        raise WorktreeIsolationError("task worktree resolved to the primary checkout")
    # A worktree nested inside the primary checkout is never valid, even though it
    # "works" at first. When it is later pruned, its .git gitlink dangles and breaks
    # `git status` repo-wide (fatal: not a git repository), which silently disables
    # the sentinel's own dirty-check and the merge pipeline. It also gets swept by
    # stash and can be committed as a gitlink. Observed 2026-07-16 with
    # claude-orchestrator/claude-orchestrator-wt/agent-cade-inbound-triage.
    if is_nested_in(wt, repo):
        raise WorktreeIsolationError(
            f"task worktree must be a sibling of the primary checkout, not nested inside it: {wt}"
        )
    if not os.path.isdir(wt):
        raise WorktreeIsolationError(f"task worktree is missing: {wt}")

    top = _git(wt, "rev-parse", "--show-toplevel")
    if top.returncode or os.path.realpath(top.stdout.strip()) != wt:
        raise WorktreeIsolationError("task path is not the expected git worktree")

    branch = _git(wt, "symbolic-ref", "--quiet", "--short", "HEAD")
    expected = f"agent/{slug}"
    if branch.returncode or branch.stdout.strip() != expected:
        actual = branch.stdout.strip() or "detached/unknown"
        raise WorktreeIsolationError(
            f"task worktree branch mismatch: expected {expected}, found {actual}"
        )

    listed = _git(repo, "worktree", "list", "--porcelain")
    registered = {
        os.path.realpath(line.removeprefix("worktree ").strip())
        for line in listed.stdout.splitlines()
        if line.startswith("worktree ")
    }
    if listed.returncode or wt not in registered:
        raise WorktreeIsolationError("task worktree is not registered by the primary repository")
    return wt


def _salvage_commit(worktree: str, slug: str) -> None:
    """Keep an interrupted agent's uncommitted edits on its own branch before reclaim.

    Best-effort and deliberately narrow: only commits when HEAD is already the expected
    agent/<slug> branch, so nothing can leak into a shared branch. Committed work always
    survives reclaim anyway (the branch outlives the worktree); this only rescues edits
    an agent had not committed when its runner was killed.
    """
    branch = _git(worktree, "symbolic-ref", "--quiet", "--short", "HEAD")
    if branch.returncode or branch.stdout.strip() != f"agent/{slug}":
        return
    if not _git(worktree, "status", "--porcelain").stdout.strip():
        return
    _git(worktree, "add", "-A")
    _git(worktree, "commit", "--no-verify", "-m", f"salvage: interrupted work for {slug}")


def reclaim_worktree(repo: str, slug: str, worktree: str) -> None:
    """Drop a leftover worktree so a fresh, properly-owned one can be created.

    setup-worktrees.sh `git worktree lock`s every checkout it makes, which is why
    worktree_gc reported these as "in-use/locked" and never reclaimed them. Unlock first,
    then remove; fall back to rmtree + prune when git refuses.
    """
    try:
        _salvage_commit(worktree, slug)
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("worktree_isolation: salvage commit failed for %s: %s", slug, exc)
    _git(repo, "worktree", "unlock", worktree)
    removed = _git(repo, "worktree", "remove", "--force", worktree)
    if removed.returncode and os.path.isdir(worktree):
        shutil.rmtree(worktree, ignore_errors=True)
    _git(repo, "worktree", "prune")
    try:
        os.remove(owner_marker_path(repo, slug))
    except OSError:
        pass
    if os.path.isdir(worktree):
        raise WorktreeIsolationError(
            f"could not reclaim leftover worktree: {worktree}"
        )


def ensure_task_worktree(repo: str, slug: str, base: str, setup_script: str, *,
                         task_id: Optional[str] = None, lease_token: Optional[str] = None) -> str:
    """Create or reuse a task worktree while holding the repository lock."""
    wt = task_worktree_path(repo, slug)
    with repo_lock.hold(repo, timeout=120) as acquired:
        if not acquired:
            raise WorktreeIsolationError("repository isolation lock unavailable")

        if not task_id or not lease_token:
            raise WorktreeIsolationError("task and branch-lease identity are required")

        # Preserve interrupted work only for the exact still-leased writer.
        # A matching branch name is not ownership proof.
        #
        # But "not provably mine" is not the same as "provably someone else's". A
        # leftover directory with no marker, or one carrying this same task's superseded
        # lease token, belongs to no live writer and must be reclaimed — refusing it
        # wedges the task forever (see reclaim_reason). Only a marker naming a DIFFERENT
        # task is a genuine collision, and that is still refused.
        if os.path.isdir(wt):
            try:
                validate_owner(repo, slug, task_id, lease_token)
            except WorktreeIsolationError as exc:
                reason = reclaim_reason(repo, slug, task_id)
                if reason is None:
                    raise
                log.warning("worktree_isolation: reclaiming leftover worktree %s "
                            "for task %s — %s (%s)", wt, slug, reason, exc)
                reclaim_worktree(repo, slug, wt)
            else:
                return validate_task_worktree(repo, slug, wt)

        created = subprocess.run(
            [setup_script, slug, base, task_id, lease_token],
            cwd=repo, capture_output=True, text=True, timeout=300,
        )
        if created.returncode:
            detail = (created.stderr or created.stdout or "unknown setup error").strip()[-1000:]
            raise WorktreeIsolationError(f"worktree setup failed: {detail}")
        validate_owner(repo, slug, task_id, lease_token)
        return validate_task_worktree(repo, slug, wt)


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Create and validate one isolated task worktree")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--slug", required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--lease-token", required=True)
    parser.add_argument(
        "--setup-script", default=os.path.join(os.path.dirname(__file__), "setup-worktrees.sh")
    )
    args = parser.parse_args()
    try:
        print(ensure_task_worktree(
            args.repo, args.slug, args.base, args.setup_script,
            task_id=args.task_id, lease_token=args.lease_token,
        ))
        return 0
    except WorktreeIsolationError as exc:
        print(f"worktree isolation failed: {exc}", file=__import__("sys").stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
