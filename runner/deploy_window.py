#!/usr/bin/env python3
"""
deploy_window.py - canary-gated nightly deploy window. Finds tasks that have been
integrated on a staging branch (state=MERGED, note contains 'staging'), runs canary
evaluation, and either promotes to main or triggers rollback.

Env: METRICS_URL, CANARY_MAX_ERROR_RATE, CANARY_MAX_P95_MS, CANARY_MIN_CONVERSION
     STAGING_BRANCH (default: staging), MAIN_BRANCH (default: main)

Called by periodic.py via `python3 periodic.py deploy`.
"""
import os, sys, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db, canary

STAGING = os.environ.get("STAGING_BRANCH", "staging")
MAIN = os.environ.get("MAIN_BRANCH", "main")


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
                "project": name, "kind": "integrate",
                "title": f"Canary promote FAILED for {name} (merge conflict)",
                "why": f"canary passed ({reason}) but ff-merge failed",
                "risk": "manual merge or rebase required"
            })
    else:
        # rollback: reset staging to main
        r = subprocess.run(["git", "checkout", STAGING], cwd=repo, capture_output=True)
        subprocess.run(["git", "reset", "--hard", MAIN], cwd=repo, capture_output=True)
        db.insert("approvals", {
            "project": name, "kind": "self",
            "title": f"Canary rollback: {name} staging reset to {MAIN}",
            "why": reason, "risk": f"metrics breached — staging rolled back to {MAIN}",
            "status": "approved", "decided_by": "canary:auto-rollback"
        })
        print(f"{name}: rolled back {STAGING} to {MAIN} — {reason}")


def _ff_merge(repo, src, dst):
    try:
        subprocess.run(["git", "checkout", dst], cwd=repo, check=True, capture_output=True)
        r = subprocess.run(["git", "merge", "--ff-only", src], cwd=repo, capture_output=True)
        return r.returncode == 0
    except Exception:
        return False


if __name__ == "__main__":
    run()
