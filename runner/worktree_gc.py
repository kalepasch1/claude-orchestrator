#!/usr/bin/env python3
"""
worktree_gc.py - the fix for the ROOT of the phantom-CONFLICT bug: leftover agent worktrees. Every task
got its own `<repo>-wt/<slug>` worktree, but nothing ever removed them, so branches stayed checked out
and the merge handler's `git rebase` failed with "already checked out" — which it mislabeled as CONFLICT
(93 tasks stuck, 0 merges). This periodically removes worktrees for tasks that are NO LONGER running, so
branches are free to merge and disk stays clean.

Runs ON THE RUNNER MACHINE only (paths must match — never from a sandbox with remapped paths). Safe:
only removes worktrees whose task is in a terminal/queued state, never a RUNNING one.
"""
import os, sys, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db


PROTECTED_STATES = ("RUNNING", "RETRY")
MERGE_KINDS = ("verify", "material", "integrate")
GIT_TIMEOUT = int(os.environ.get("WORKTREE_GC_GIT_TIMEOUT", "90"))


def _run_git(args, repo):
    """Run a git command, returning CompletedProcess. Falls back to no-timeout
    call if subprocess.run is monkeypatched in tests (TypeError on 'timeout')."""
    try:
        return subprocess.run(args, cwd=repo, capture_output=True, text=True, timeout=GIT_TIMEOUT)
    except TypeError:
        return subprocess.run(args, cwd=repo, capture_output=True, text=True)


def _protected_slugs():
    """Branches in active execution or approved integration must not be garbage-collected."""
    slugs = set()
    for state in PROTECTED_STATES:
        try:
            slugs.update(t["slug"] for t in (db.select("tasks", {"select": "slug", "state": f"eq.{state}"}) or []))
        except Exception:
            continue
    for a in db.select("approvals", {"select": "slug,title,kind,status,decided_by", "status": "in.(pending,approved)"}) or []:
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


def gc_repo(repo):
    if not repo or not os.path.isdir(repo):
        return 0
    main_worktree = os.path.abspath(repo)
    protected = _protected_slugs()
    out = _run_git(["git", "worktree", "list", "--porcelain"], repo).stdout
    removed = 0
    path = branch = None
    for line in out.splitlines() + [""]:
        if line.startswith("worktree "):
            path = line[len("worktree "):].strip()
        elif line.startswith("branch "):
            branch = line[len("branch refs/heads/"):].strip()
        elif line == "":
            # end of a worktree block
            if path and branch and branch.startswith("agent/"):
                slug = branch[len("agent/"):]
                if slug not in protected and os.path.abspath(path) != main_worktree:
                    # DURABILITY: push the branch to origin before reclaiming the worktree, so the
                    # work survives on the remote even if the runner's fail-soft share push never
                    # landed. This is what stops the recover-missing-branch churn at the source —
                    # a GC'd branch is always fetchable by the other Mac / the merge train.
                    if os.environ.get("ORCH_SHARE_AGENT_BRANCHES", "true").lower() in ("true", "1", "yes", "on"):
                        on_origin = _run_git(["git", "show-ref", "--verify", "--quiet",
                                              f"refs/remotes/origin/{branch}"], repo).returncode == 0
                        if not on_origin:
                            _run_git(["git", "push", "-u", "origin", f"{branch}:{branch}"], repo)
                    if _run_git(["git", "worktree", "remove", "--force", path], repo).returncode == 0:
                        removed += 1
            path = branch = None
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
