#!/usr/bin/env python3
"""
deploy_window.py - canary-gated nightly deploy window. Finds tasks that have been
integrated on a staging branch (state=MERGED, note contains 'staging'), runs canary
evaluation, and either promotes to main or triggers rollback.

Env: METRICS_URL, CANARY_MAX_ERROR_RATE, CANARY_MAX_P95_MS, CANARY_MIN_CONVERSION
     STAGING_BRANCH (default: staging), MAIN_BRANCH (default: main)

Called by periodic.py via `python3 periodic.py deploy`.

WORKTREE SAFETY (2026-07-08): the promote and rollback paths used to `git checkout` STAGING/MAIN
directly in `repo` — the orchestrator's own primary checkout — and never switched back
afterward, so a canary run left the primary checkout parked on whatever branch it last touched.
Both paths now run inside a `-f`-forced isolated worktree (same convention runner.py's own
zero-spend-recovery path uses): `-f` lets the worktree check out a branch that's ALSO currently
checked out in `repo` itself (which STAGING/MAIN often is) without git refusing or `repo` ever
being touched. See _run_in_branch_worktree().
"""
import os, sys, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db, canary

STAGING = os.environ.get("STAGING_BRANCH", "staging")
MAIN = os.environ.get("MAIN_BRANCH", "main")


def _worktree_path(repo, branch):
    safe = branch.replace("/", "-")
    return os.path.join(os.path.dirname(repo), os.path.basename(repo) + "-wt", f"deploy-{safe}")


def _run_in_branch_worktree(repo, branch, ops):
    """Create a forced isolated worktree checked out to `branch`, run `ops(worktree_path)`
    inside it, then always remove the worktree (the branch/ref itself is untouched by removal —
    only the temporary working-tree directory goes away). Returns ops()'s result, or None if the
    worktree couldn't be created (caller decides how to treat that). Never touches `repo`'s own
    checked-out branch."""
    wt = _worktree_path(repo, branch)
    added = None
    try:
        os.makedirs(os.path.dirname(wt), exist_ok=True)
        added = subprocess.run(["git", "worktree", "add", "-f", wt, branch], cwd=repo,
                               capture_output=True, timeout=60)
        if added.returncode != 0 or not os.path.isdir(wt):
            return None
        return ops(wt)
    finally:
        try:
            subprocess.run(["git", "worktree", "remove", "--force", wt], cwd=repo,
                           capture_output=True, timeout=30)
        except Exception:
            pass


def run():
    """Evaluate all projects with a METRICS_URL; promote or rollback each."""
    metrics_url = os.environ.get("METRICS_URL")
    if not metrics_url:
        print("deploy_window: no METRICS_URL set — skipping canary evaluation")
        return

    for proj in db.select("projects", {"select": "*"}) or []:
        repo = proj.get("repo_path", "")
        name = proj.get("name", "?")
        if not os.path.isdir(repo):
            continue
        _evaluate_project(repo, name, metrics_url)


def _evaluate_project(repo, name, metrics_url):
    # Check staging branch has commits ahead of main
    try:
        ahead = subprocess.check_output(
            ["git", "rev-list", "--count", f"{MAIN}..{STAGING}"],
            cwd=repo, text=True).strip()
        if int(ahead) == 0:
            print(f"{name}: staging == main, nothing to promote")
            return
    except Exception as e:
        print(f"{name}: could not compare branches ({e})")
        return

    print(f"{name}: {ahead} commit(s) ahead of {MAIN} on {STAGING} — evaluating canary...")
    result = canary.evaluate(metrics_url)
    verdict = result["verdict"]
    reason = result["reason"]
    print(f"{name}: canary verdict={verdict} — {reason}")

    if verdict == "promote":
        ok = _ff_merge(repo, STAGING, MAIN)
        if ok:
            db.insert("approvals", {
                "project": name, "kind": "self",
                "title": f"Canary promoted {name} to {MAIN}",
                "why": reason, "value": "metrics within thresholds — auto-promoted",
                "status": "approved", "decided_by": "canary"
            })
            print(f"{name}: promoted {STAGING} -> {MAIN}")
        else:
            db.insert("approvals", {
                # A failed canary is an operational incident, not an approved
                # code-merge card.  Merge cards must carry a canonical slug.
                "project": name, "kind": "integration_failure",
                "title": f"Canary promote FAILED for {name} (merge conflict)",
                "why": f"canary passed ({reason}) but ff-merge failed",
                "risk": "manual merge or rebase required"
            })
    else:
        # rollback: reset staging to main, inside an isolated worktree — never repo's own checkout
        def _reset(wt):
            r = subprocess.run(["git", "reset", "--hard", MAIN], cwd=wt, capture_output=True)
            return r.returncode == 0

        try:
            ok = _run_in_branch_worktree(repo, STAGING, _reset)
        except Exception as e:
            ok = False
            print(f"{name}: rollback worktree failed ({e})")
        db.insert("approvals", {
            "project": name, "kind": "self",
            "title": f"Canary rollback: {name} staging reset to {MAIN}",
            "why": reason, "risk": f"metrics breached — staging rolled back to {MAIN}",
            "status": "approved", "decided_by": "canary:auto-rollback"
        })
        print(f"{name}: rolled back {STAGING} to {MAIN} — {reason}" if ok
              else f"{name}: rollback attempt for {STAGING} may not have applied — check manually")


def _ff_merge(repo, src, dst):
    def _merge(wt):
        r = subprocess.run(["git", "merge", "--ff-only", src], cwd=wt, capture_output=True)
        return r.returncode == 0

    try:
        return bool(_run_in_branch_worktree(repo, dst, _merge))
    except Exception:
        return False


if __name__ == "__main__":
    run()
