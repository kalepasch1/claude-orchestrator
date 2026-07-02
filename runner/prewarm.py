#!/usr/bin/env python3
"""
prewarm.py - turn idle gaps into throughput. Before a worker is free, pre-create the git worktree
and pre-compute the scoped file focus (context_retrieval) for the NEXT claimable tasks, so when a
slot opens the agent starts instantly instead of paying worktree-setup + context-scan latency.

Safe: only sets up worktrees + warms a read-only context cache. It NEVER claims or runs a task and
NEVER calls a model, so it cannot spend or double-run. Idempotent (setup-worktrees.sh is a no-op if
the worktree exists). Schedule on a short interval.
"""
import os, sys, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

PREWARM_N = int(os.environ.get("PREWARM_N", "4"))
_DIR = os.path.dirname(os.path.abspath(__file__))


def _claimable_next(limit):
    """Mirror db.claim_task ordering to predict which tasks will run next (dep-satisfied, QUEUED)."""
    projs = {p["id"]: p for p in (db.select("projects", {"select": "*"}) or [])}
    done = {t["slug"] for t in (db.select("tasks", {"select": "slug", "state": "in.(DONE,MERGED)"}) or [])}
    q = db.select("tasks", {"select": "*", "state": "eq.QUEUED"}) or []
    q = [t for t in q if all(d in done for d in (t.get("deps") or []))]
    q.sort(key=lambda t: ((projs.get(t.get("project_id"), {}) or {}).get("priority") or 5,
                          -float((projs.get(t.get("project_id"), {}) or {}).get("concurrency_weight") or 1),
                          t.get("created_at") or ""))
    return q[:limit], projs


def run():
    tasks, projs = _claimable_next(PREWARM_N)
    warmed = 0
    for t in tasks:
        proj = projs.get(t.get("project_id"), {}) or {}
        repo = proj.get("repo_path", "")
        if not repo or not os.path.isdir(repo):
            continue
        slug = t["slug"]
        base = t.get("base_branch") or "main"
        try:
            subprocess.run([os.path.join(_DIR, "setup-worktrees.sh"), slug, base],
                           cwd=repo, capture_output=True, timeout=60)
            # warm the scoped-context cache (read-only; no model call)
            try:
                import context_retrieval
                context_retrieval.select_files(repo, t.get("prompt", ""))
            except Exception:
                pass
            warmed += 1
        except Exception as e:
            print(f"prewarm: {slug} skipped ({e})")
    print(f"prewarm: warmed {warmed}/{len(tasks)} upcoming task worktrees")
    return warmed


if __name__ == "__main__":
    run()
