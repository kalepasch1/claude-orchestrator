#!/usr/bin/env python3
"""
queue_elimination.py — Zero-token task elimination at queue time (500X).

Before a task is even claimed by a runner, check if it can be resolved
via existing knowledge (intent graph replay, speculative diff, distilled
prompts). If so, mark it DONE without ever creating a worktree or calling
a model.

This runs as a periodic job that scans QUEUED tasks and attempts
zero-token resolution on each.

Flow:
  1. Scan QUEUED tasks (newest first, up to SCAN_LIMIT)
  2. For each: check intent_graph → speculative_diff → prompt_distillation
  3. If zero-token resolution succeeds: apply diff, run tests, mark DONE
  4. If not: leave QUEUED for normal runner claim

Usage:
    import queue_elimination
    queue_elimination.run()  # periodic scan
    # Or for a single task:
    result = queue_elimination.try_eliminate(task, project_row)
"""
import os, sys, json, subprocess, time, hashlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

SCAN_LIMIT = int(os.environ.get("ORCH_ELIM_SCAN_LIMIT", "10"))
ELIM_MIN_CONFIDENCE = float(os.environ.get("ORCH_ELIM_MIN_CONF", "0.9"))
ELIM_ENABLED = os.environ.get("ORCH_QUEUE_ELIMINATION", "true").lower() in ("true", "1", "yes")


def _get_project(project_id):
    try:
        rows = db.select("projects", {"select": "id,name,repo_path", "id": f"eq.{project_id}"})
        return rows[0] if rows else None
    except Exception:
        return None


def try_eliminate(task, project_row=None):
    """Attempt zero-token elimination of a single task.

    Returns: {eliminated: bool, method: str, reason: str}
    """
    if not ELIM_ENABLED:
        return {"eliminated": False, "method": "disabled", "reason": "queue elimination disabled"}

    task_id = task.get("id", "")
    prompt = task.get("prompt", "")

    if not project_row:
        project_row = _get_project(task.get("project_id", ""))
    if not project_row:
        return {"eliminated": False, "method": "no_project", "reason": "project not found"}

    repo = project_row.get("repo_path", "")
    name = project_row.get("name", "")

    if not repo or not os.path.isdir(repo):
        return {"eliminated": False, "method": "no_repo", "reason": "repo not found"}

    # 1. Check intent graph for high-confidence replay
    try:
        import intent_graph
        replay = intent_graph.find_replay(task, repo)
        if replay and replay.get("confidence", 0) >= ELIM_MIN_CONFIDENCE:
            # Try applying the cached diff
            diff_text = replay.get("diff_text", "")
            if diff_text:
                result = _apply_and_verify(repo, diff_text, task_id)
                if result.get("success"):
                    _mark_done(task, name, "intent_graph_replay", replay)
                    return {"eliminated": True, "method": "intent_graph",
                            "reason": f"replay confidence {replay['confidence']:.0%}"}
    except Exception:
        pass

    # 2. Check speculative diff
    try:
        import speculative_diff
        spec = speculative_diff.try_replay(task, repo, "HEAD", repo)
        if spec and spec.get("applied"):
            _mark_done(task, name, "speculative_diff", spec)
            return {"eliminated": True, "method": "speculative_diff",
                    "reason": "exact diff replay succeeded"}
    except Exception:
        pass

    # 3. Check if prompt distillation has a very mature template
    try:
        import prompt_distillation
        distilled = prompt_distillation.find_distilled(task, current_project=name)
        if distilled and distilled.get("merge_count", 0) >= 10:
            # Very mature — but we need a diff to apply, not just a prompt
            # Check if intent graph has edges for this distilled key
            try:
                import intent_graph
                graph = intent_graph._graph()
                key = distilled.get("key", "")
                matching_edges = [e for e in graph.get("edges", [])
                                  if e.get("intent_fp", "").startswith(key[:8]) and e.get("merged")]
                if matching_edges:
                    latest = max(matching_edges, key=lambda e: e.get("timestamp", 0))
                    change = graph.get("changes", {}).get(latest.get("change_key", ""), {})
                    diff_text = change.get("diff_text", "")
                    if diff_text:
                        result = _apply_and_verify(repo, diff_text, task_id)
                        if result.get("success"):
                            _mark_done(task, name, "distilled_replay", distilled)
                            return {"eliminated": True, "method": "distilled_replay",
                                    "reason": f"mature distillation ({distilled['merge_count']} merges)"}
            except Exception:
                pass
    except Exception:
        pass

    return {"eliminated": False, "method": "none", "reason": "no zero-token path found"}


def _worktree_path(repo, branch):
    return os.path.join(os.path.dirname(repo), os.path.basename(repo) + "-wt", branch)


def _cleanup_worktree(repo, wt, branch, keep_branch):
    """Best-effort cleanup — never raises, this runs on every exit path including exceptions."""
    try:
        subprocess.run(["git", "worktree", "remove", "--force", wt], cwd=repo,
                       capture_output=True, timeout=30)
    except Exception:
        pass
    if not keep_branch:
        try:
            subprocess.run(["git", "branch", "-D", branch], cwd=repo, capture_output=True, timeout=15)
        except Exception:
            pass


def _apply_and_verify(repo, diff_text, task_id):
    """Apply a diff and verify with build+test, entirely inside an isolated worktree — this
    used to `git checkout -b` directly in `repo` (the primary checkout), which parked the
    orchestrator's own live checkout on a throwaway branch for the duration of a build+test run
    (up to 180s), and left it there permanently on the success path (only the failure/exception
    paths tried to switch back). Any concurrent process reading `repo`'s working tree during that
    window — including a human — would see the wrong branch. Matches the same
    `<repo>-wt/<slug>` isolated-worktree convention runner.py's own zero-spend-recovery path
    already uses. Revert on failure by discarding the worktree/branch; `repo` itself is never
    touched."""
    branch = f"elim-{task_id[:8]}-{int(time.time())}"
    wt = _worktree_path(repo, branch)
    try:
        # Check first (this alone is safe against repo's working tree — --check never writes)
        check = subprocess.run(
            ["git", "apply", "--check", "--3way"],
            input=diff_text, cwd=repo,
            capture_output=True, text=True, timeout=30
        )
        if check.returncode != 0:
            return {"success": False, "reason": "diff doesn't apply"}

        os.makedirs(os.path.dirname(wt), exist_ok=True)
        added = subprocess.run(["git", "worktree", "add", "-b", branch, wt, "HEAD"], cwd=repo,
                               capture_output=True, text=True, timeout=60)
        if added.returncode != 0 or not os.path.isdir(wt):
            return {"success": False, "reason": f"worktree add failed: {(added.stderr or '')[:200]}"}

        # Apply — inside the worktree, never repo
        apply_result = subprocess.run(
            ["git", "apply", "--3way"],
            input=diff_text, cwd=wt,
            capture_output=True, text=True, timeout=30
        )
        if apply_result.returncode != 0:
            _cleanup_worktree(repo, wt, branch, keep_branch=False)
            return {"success": False, "reason": "apply failed"}

        # Build+test — inside the worktree
        test_cmd = os.environ.get("TEST_CMD", "npm test")
        test = subprocess.run(
            test_cmd, shell=True, cwd=wt,
            capture_output=True, text=True, timeout=180,
            env={**os.environ, "CI": "true"}
        )

        if test.returncode == 0:
            # Commit the change in the worktree, then remove the worktree directory but KEEP
            # the branch (the commit) — matches the original return contract of {"branch": ...}.
            subprocess.run(["git", "add", "-A"], cwd=wt, capture_output=True, timeout=15)
            subprocess.run(["git", "commit", "-m", f"[queue-elim] zero-token resolution for {task_id[:8]}"],
                          cwd=wt, capture_output=True, timeout=15)
            _cleanup_worktree(repo, wt, branch, keep_branch=True)
            return {"success": True, "branch": branch}
        else:
            _cleanup_worktree(repo, wt, branch, keep_branch=False)
            return {"success": False, "reason": "tests failed"}

    except Exception as e:
        _cleanup_worktree(repo, wt, branch, keep_branch=False)
        return {"success": False, "reason": str(e)[:200]}


def _mark_done(task, project_name, method, context):
    """Mark a task as DONE via queue elimination."""
    try:
        db.update("tasks", {"id": task["id"]}, {
            "state": "MERGED",
            "note": f"[queue-elim] zero-token via {method}",
            "finished_at": "now()",
        })
    except Exception:
        pass

    # Record in deployment tracking
    try:
        import cade_tournaments
        cade_tournaments.writeback_outcome(
            task, {"merged": True, "method": method, "diff_summary": f"queue-eliminated via {method}"},
            project=project_name, model="none", coder="zero-token",
            cost_usd=0, tokens_in=0, tokens_out=0
        )
    except Exception:
        pass


def run():
    """Periodic: scan QUEUED tasks for zero-token elimination."""
    if not ELIM_ENABLED:
        print("[queue-elim] disabled")
        return

    try:
        tasks = db.select("tasks", {
            "select": "id,prompt,project_id,kind,slug,state",
            "state": "eq.QUEUED",
            "order": "created_at.desc",
            "limit": SCAN_LIMIT,
        }) or []
    except Exception:
        print("[queue-elim] failed to fetch tasks")
        return

    eliminated = 0
    for t in tasks:
        result = try_eliminate(t)
        if result.get("eliminated"):
            eliminated += 1
            print(f"[queue-elim] eliminated {t.get('slug', t['id'][:8])} via {result['method']}")

    print(f"[queue-elim] scanned {len(tasks)}, eliminated {eliminated}")


if __name__ == "__main__":
    run()
