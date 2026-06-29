#!/usr/bin/env python3
"""
replay.py - deterministic replay. capture() snapshots the exact composed prompt + model +
base commit + confidence for every run into `runs`, so any build is reproducible and
bisectable. replay(run_id) re-runs that exact prompt in a fresh worktree.
"""
import os, sys, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "claude")


def capture(task_id, project, slug, kind, model, account, repo, base, prompt, confidence=None):
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
    wt = os.path.join(os.path.dirname(repo), os.path.basename(repo) + "-wt", f"replay-{r['slug']}")
    subprocess.run([os.path.join(os.path.dirname(__file__), "setup-worktrees.sh"),
                    f"replay-{r['slug']}", r.get("base_commit", "main")], cwd=repo, capture_output=True)
    print(f"replaying run {run_id} ({r['model']}) at {r.get('base_commit')} ...")
    subprocess.run([CLAUDE_BIN, "-p", r["prompt"], "--model", r["model"],
                    "--permission-mode", "acceptEdits", "--max-turns", "60", "--output-format", "text"],
                   cwd=wt if os.path.isdir(wt) else repo)


if __name__ == "__main__":
    if len(sys.argv) >= 3:
        replay(sys.argv[1], sys.argv[2])
    else:
        print("usage: replay.py <run_id> <repo_path>")
