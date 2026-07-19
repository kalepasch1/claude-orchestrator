#!/usr/bin/env python3
"""
replay.py - deterministic replay. capture() snapshots the exact composed prompt + model +
base commit + confidence for every run into `runs`, so any build is reproducible and
bisectable. replay(run_id) re-runs that exact prompt in a fresh worktree.
"""
import os, sys, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db, claude_cli, branch_lease, worktree_isolation



def capture(task_id, project, slug, kind, model, account, repo, base, prompt, confidence=None):
    """Snapshot the exact run parameters into the `runs` table for deterministic replay."""
    try:
        commit = subprocess.check_output(["git", "rev-parse", base], cwd=repo, text=True).strip()
    except Exception:
        commit = base
    try:
        db.insert("runs", {"task_id": task_id, "project": project, "slug": slug, "kind": kind,
                           "model": model, "account": account, "base_commit": commit,
                           "prompt": prompt[:200000], "confidence": confidence})
    except Exception:
        pass


def replay(run_id, repo):
    rows = db.select("runs", {"select": "*", "id": f"eq.{run_id}"}) or []
    if not rows:
        print("run not found"); return
    r = rows[0]
    tasks = db.select("tasks", {"select": "id,project_id", "id": f"eq.{r['task_id']}"}) or []
    if not tasks:
        print("replay task not found"); return
    task = tasks[0]
    replay_slug = f"replay-{r['slug']}"
    branch = f"agent/{replay_slug}"
    lease = branch_lease.acquire(task, repo, branch, r.get("base_commit", "main"))
    if not lease:
        print("replay branch lease held"); return
    try:
        wt = worktree_isolation.ensure_task_worktree(
            repo, replay_slug, r.get("base_commit", "main"),
            os.path.join(os.path.dirname(__file__), "setup-worktrees.sh"),
            task_id=str(task["id"]), lease_token=lease["token"],
        )
    except worktree_isolation.WorktreeIsolationError:
        branch_lease.release(task["id"], branch)
        print("replay worktree owner guard rejected setup"); return
    print(f"replaying run {run_id} ({r['model']}) at {r.get('base_commit')} ...")
    try:
        claude_cli.run(r["prompt"], r["model"], cwd=wt if os.path.isdir(wt) else repo,
                       max_turns=60, permission="acceptEdits")
    finally:
        branch_lease.release(task["id"], branch)


if __name__ == "__main__":
    if len(sys.argv) >= 3:
        replay(sys.argv[1], sys.argv[2])
    else:
        print("usage: replay.py <run_id> <repo_path>")
