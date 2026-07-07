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
import dependency_prewarm

PREWARM_N = int(os.environ.get("PREWARM_N", "4"))
_DIR = os.path.dirname(os.path.abspath(__file__))
RECOVERY_PREFIX = "recover-missing-branch-"
CANARY_PREFIX = "canary-"
IMPROVEMENT_PREFIX = "improve-"
RELEASE_FIX_PREFIXES = ("relfix-", "qafix-", "deployfix-", "buildfix-")


def _git(repo, *args, timeout=30):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, timeout=timeout)


def _branch_exists(repo, branch):
    return bool(branch) and _git(repo, "rev-parse", "--verify", branch).returncode == 0


def _normalize_base(repo, proj, requested):
    for b in (requested, proj.get("default_base"), proj.get("prod_branch"), "main", "master"):
        if _branch_exists(repo, b):
            return b
    return requested or proj.get("default_base") or "main"


def _claimable_next(limit):
    """Mirror db.claim_task ordering to predict which tasks will run next (dep-satisfied, QUEUED)."""
    projs = {p["id"]: p for p in (db.select("projects", {"select": "*"}) or [])}
    done = {t["slug"] for t in (db.select("tasks", {"select": "slug", "state": "in.(DONE,MERGED)"}) or [])}
    q = db.select("tasks", {"select": "*", "state": "eq.QUEUED"}) or []
    q = [t for t in q if all(d in done for d in (t.get("deps") or []))]
    recovery_backlog = (
        os.environ.get("ORCH_RECOVERY_JUMP_QUEUE", "true").lower() in ("true", "1", "yes", "on")
        and any(str(t.get("slug") or "").startswith(RECOVERY_PREFIX) for t in q)
    )
    release_fix_backlog = (
        os.environ.get("ORCH_RELEASE_FIX_JUMP_QUEUE", "true").lower() in ("true", "1", "yes", "on")
        and any(str(t.get("slug") or "").startswith(RELEASE_FIX_PREFIXES)
                or "release_train" in str(t.get("note") or "").lower()
                or "vercel" in str(t.get("note") or "").lower()
                for t in q)
    )
    improvement_backlog = (
        os.environ.get("ORCH_IMPROVEMENT_JUMP_QUEUE", "true").lower() in ("true", "1", "yes", "on")
        and any(str(t.get("slug") or "").startswith(IMPROVEMENT_PREFIX) for t in q)
    )
    evidence_backlog = (
        os.environ.get("ORCH_EVIDENCE_JUMP_QUEUE", "true").lower() in ("true", "1", "yes", "on")
        and any(str(t.get("slug") or "").startswith(CANARY_PREFIX) or "coder-canary" in str(t.get("note") or "").lower()
                for t in q)
    )

    def release_fix_urgency(t):
        slug = str(t.get("slug") or "")
        if slug.startswith(RELEASE_FIX_PREFIXES):
            return 0
        note = str(t.get("note") or "").lower()
        if "release_train" in note or "vercel" in note:
            return 1
        return 9

    q.sort(key=lambda t: (
                          0 if (release_fix_backlog and (
                              str(t.get("slug") or "").startswith(RELEASE_FIX_PREFIXES)
                              or "release_train" in str(t.get("note") or "").lower()
                              or "vercel" in str(t.get("note") or "").lower()))
                          else (1 if release_fix_backlog else 0),
                          release_fix_urgency(t),
                          0 if (recovery_backlog and str(t.get("slug") or "").startswith(RECOVERY_PREFIX))
                          else (1 if recovery_backlog else 0),
                          0 if (evidence_backlog and (
                              str(t.get("slug") or "").startswith(CANARY_PREFIX)
                              or "coder-canary" in str(t.get("note") or "").lower()))
                          else (1 if evidence_backlog else 0),
                          0 if (improvement_backlog and str(t.get("slug") or "").startswith(IMPROVEMENT_PREFIX))
                          else (1 if improvement_backlog else 0),
                          (projs.get(t.get("project_id"), {}) or {}).get("priority") or 5,
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
        base = _normalize_base(repo, proj, t.get("base_branch") or proj.get("default_base"))
        try:
            subprocess.run([os.path.join(_DIR, "setup-worktrees.sh"), slug, base],
                           cwd=repo, capture_output=True, timeout=60)
            deps = dependency_prewarm.ensure_all(repo, reason="idle_prewarm")
            if not deps.get("ok"):
                print(f"prewarm: {slug} dependency warm skipped ({(deps.get('error') or deps)})")
            # warm the scoped-context cache (read-only; no model call)
            try:
                import context_retrieval
                context_retrieval.select_files(repo, t.get("prompt", ""))
            except Exception:
                pass
            # warm reuse artifacts too: prior merged diffs and optional failing-test reproduction.
            try:
                import merged_diff_library
                merged_diff_library.find(t, limit=3)
            except Exception:
                pass
            try:
                test_cmd = proj.get("test_cmd") or os.environ.get("TEST_CMD")
                if test_cmd and os.environ.get("ORCH_PREWARM_REPRO_TESTS", "false").lower() in ("1", "true", "yes", "on"):
                    subprocess.run(test_cmd, cwd=repo, shell=True, capture_output=True,
                                   timeout=int(os.environ.get("ORCH_PREWARM_TEST_TIMEOUT", "90")))
            except Exception:
                pass
            warmed += 1
        except Exception as e:
            print(f"prewarm: {slug} skipped ({e})")
    print(f"prewarm: warmed {warmed}/{len(tasks)} upcoming task worktrees")
    return warmed


if __name__ == "__main__":
    run()
