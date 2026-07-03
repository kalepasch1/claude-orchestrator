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


PROTECTED_STATES = ("RUNNING", "MERGING", "RETRY")
MERGE_KINDS = ("verify", "material", "integrate")


def _protected_slugs():
    """Branches in active execution or approved integration must not be garbage-collected."""
    slugs = set()
    for state in PROTECTED_STATES:
        slugs.update(t["slug"] for t in (db.select("tasks", {"select": "slug", "state": f"eq.{state}"}) or []))
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
    out = subprocess.run(["git", "worktree", "list", "--porcelain"], cwd=repo,
                         capture_output=True, text=True).stdout
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
                    if subprocess.run(["git", "worktree", "remove", "--force", path],
                                      cwd=repo, capture_output=True).returncode == 0:
                        removed += 1
            path = branch = None
    subprocess.run(["git", "worktree", "prune"], cwd=repo, capture_output=True)
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
