#!/usr/bin/env python3
"""
worktree_gc.py - the fix for the ROOT of the phantom-CONFLICT bug: leftover agent worktrees. Every task
got its own `<repo>-wt/<slug>` worktree, but nothing ever removed them, so branches stayed checked out
and the merge handler's `git rebase` failed with "already checked out" — which it mislabeled as CONFLICT
(93 tasks stuck, 0 merges). This periodically removes worktrees for tasks that are NO LONGER running, so
branches are free to merge and disk stays clean.

Runs ON THE RUNNER MACHINE only (paths must match — never from a sandbox with remapped paths). Safe:
only removes worktrees whose task is in a terminal/queued state, never a RUNNING one.

Safety invariants:
  - RUNNING and RETRY tasks are always protected (see PROTECTED_STATES).
  - Pending/approved merge approvals are also protected to avoid racing the merge handler.
  - Before removing a worktree, the branch is pushed to origin (unless ORCH_SHARE_AGENT_BRANCHES
    is disabled) so work is never lost — this eliminated the recover-missing-branch churn.

Environment variables:
  WORKTREE_GC_GIT_TIMEOUT   Max seconds for any single git subprocess (default: 90).
  ORCH_SHARE_AGENT_BRANCHES Push agent branches to origin before GC (default: true).
"""
import os, sys, time, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db


PROTECTED_STATES = ("RUNNING", "RETRY")
MERGE_KINDS = ("verify", "material", "integrate")
GIT_TIMEOUT = int(os.environ.get("WORKTREE_GC_GIT_TIMEOUT", "90"))
# Never GC a worktree that showed filesystem/git activity within this window. Cowork/manual
# executors create worktrees that may sit briefly before their task row flips to RUNNING,
# and a fresh checkout has zero commits ahead of base — recency is the only reliable signal.
MIN_AGE_MIN = int(os.environ.get("WORKTREE_GC_MIN_AGE_MIN", "180"))


def _run_git(args, repo):
    try:
        return subprocess.run(args, cwd=repo, capture_output=True, text=True, timeout=GIT_TIMEOUT)
    except subprocess.TimeoutExpired:
        # Return a failed-looking result so callers degrade gracefully instead of crashing.
        return subprocess.CompletedProcess(args, returncode=124, stdout="", stderr="git timeout")
    except TypeError:
        # Unit tests monkeypatch subprocess.run with a minimal signature.
        return subprocess.run(args, cwd=repo, capture_output=True, text=True)


def _protected_slugs():
    """Branches in active execution or approved integration must not be garbage-collected.

    FAIL CLOSED: returns None if the task/approval DB cannot be read. An empty protected set
    caused mass deletion of in-use worktrees whenever Supabase errored or rate-limited (the
    old code swallowed the exception and 'protected' nothing) — executors then lost RUNNING
    work mid-task. Callers MUST skip GC entirely when this returns None."""
    slugs = set()
    for state in PROTECTED_STATES:
        try:
            rows = db.select("tasks", {"select": "slug", "state": f"eq.{state}"})
        except Exception:
            return None
        if rows is None:
            return None
        slugs.update(t["slug"] for t in rows)
    try:
        approvals = db.select("approvals", {"select": "slug,title,kind,status,decided_by", "status": "in.(pending,approved)"})
    except Exception:
        return None
    if approvals is None:
        return None
    for a in approvals:
        if a.get("kind") not in MERGE_KINDS:
            continue
        if str(a.get("decided_by") or "").startswith(("merge-handler", "train")):
            continue
        slug = a.get("slug")
        if not slug:
            try:
                slug = __import__("approval_merge")._slug_from(a)
            except Exception:
                slug = None
        if slug:
            slugs.add(slug)
    return slugs


def _is_dirty(path):
    """True if the worktree has uncommitted/staged/untracked changes. Fail closed (dirty)."""
    try:
        r = _run_git(["git", "status", "--porcelain"], path)
        if r.returncode != 0:
            return True
        return bool((r.stdout or "").strip())
    except Exception:
        return True


def _recently_active(path):
    """True if the worktree (or its git admin dir/index) was touched within MIN_AGE_MIN.
    Catches freshly created worktrees and ones an executor is actively using, even when
    the task row isn't (yet/anymore) in a protected state. Fail closed (recent)."""
    if MIN_AGE_MIN <= 0:
        return False
    cands = [path, os.path.join(path, ".git")]
    try:
        with open(os.path.join(path, ".git")) as f:
            g = f.read().strip()
        if g.startswith("gitdir:"):
            admin = g.split(":", 1)[1].strip()
            cands += [admin, os.path.join(admin, "index")]
    except Exception:
        return True
    newest = 0.0
    for c in cands:
        try:
            newest = max(newest, os.path.getmtime(c))
        except Exception:
            pass
    if newest == 0.0:
        return True
    return newest > time.time() - MIN_AGE_MIN * 60


def gc_repo(repo):
    if not repo or not os.path.isdir(repo):
        return 0
    main_worktree = os.path.abspath(repo)
    protected = _protected_slugs()
    if protected is None:
        # FAIL CLOSED: DB unreachable — we cannot know which tasks are RUNNING.
        # Deleting on an empty set is what wiped executors' worktrees mid-task.
        print(f"worktree_gc: task DB unavailable — failing closed, skipping GC for {repo}")
        return 0
    out = _run_git(["git", "worktree", "list", "--porcelain"], repo).stdout
    removed = 0
    path = branch = None
    locked = False
    for line in out.splitlines() + [""]:
        if line.startswith("worktree "):
            path = line[len("worktree "):].strip()
        elif line.startswith("branch "):
            branch = line[len("branch refs/heads/"):].strip()
        elif line.startswith("locked"):
            locked = True
        elif line == "":
            # end of a worktree block
            if path and branch and branch.startswith("agent/"):
                slug = branch[len("agent/"):]
                # NOTE: creation locks (git worktree lock) protect against OTHER deleters
                # (resource_governor, merge handlers). Here the guards below decide; once they
                # all pass we unlock and reclaim, so finished worktrees don't leak disk.
                if _is_dirty(path):
                    pass  # uncommitted work — never GC
                elif _recently_active(path):
                    pass  # fresh checkout or active executor — never GC
                elif slug not in protected and os.path.abspath(path) != main_worktree:
                    # DURABILITY: push the branch to origin before reclaiming the worktree, so the
                    # work survives on the remote even if the runner's fail-soft share push never
                    # landed. This is what stops the recover-missing-branch churn at the source —
                    # a GC'd branch is always fetchable by the other Mac / the merge train.
                    if os.environ.get("ORCH_SHARE_AGENT_BRANCHES", "true").lower() in ("true", "1", "yes", "on"):
                        on_origin = _run_git(["git", "show-ref", "--verify", "--quiet",
                                              f"refs/remotes/origin/{branch}"], repo).returncode == 0
                        if not on_origin:
                            _run_git(["git", "push", "-u", "origin", f"{branch}:{branch}"], repo)
                    # All guards passed (task terminal, clean, aged): clear any stale creation
                    # lock left by the runner so a finished worktree can actually be reclaimed.
                    _run_git(["git", "worktree", "unlock", path], repo)
                    if _run_git(["git", "worktree", "remove", "--force", path], repo).returncode == 0:
                        removed += 1
            path = branch = None
            locked = False
    _run_git(["git", "worktree", "prune"], repo)
    return removed


def run():
    total = 0
    for p in db.select("projects", {"select": "name,repo_path"}) or []:
        try:
            n = gc_repo(p.get("repo_path", ""))
            if n:
                print(f"worktree_gc: {p['name']} removed {n} stale worktree(s)")
            total += n
        except Exception as e:
            print(f"worktree_gc: {p.get('name')} error {e}")
    print(f"worktree_gc: removed {total} stale worktree(s) across repos")
    return total


if __name__ == "__main__":
    run()
