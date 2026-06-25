#!/usr/bin/env python3
"""
pr_integrate.py - PR-native integration. Instead of a local ff-merge, push the branch
and open a GitHub PR with the verification summary, then let YOUR existing CI
(sfc / gitleaks / vercel / preflight) be the gate. Auto-merge when all checks are green;
otherwise leave the PR open for review (with the runner's verdict in the body).

Requires the `gh` CLI authenticated on the runner. Set INTEGRATION_MODE=pr to use this
(else runner.py does local integrate). This ties the swarm into the exact checks that
blocked your bilateral PR, and gives partners a real review trail.
"""
import os, subprocess, json, time
import supabase_twin

AUTO_MERGE = os.environ.get("PR_AUTO_MERGE", "true").lower() == "true"
POLL = int(os.environ.get("PR_CHECK_POLL", "30"))
MAX_WAIT = int(os.environ.get("PR_CHECK_MAX_WAIT", "1800"))
TWIN_ENABLED = os.environ.get("SUPABASE_ACCESS_TOKEN") and os.environ.get("SUPABASE_PROJECT_REF")


def _gh(args, cwd, **kw):
    return subprocess.run(["gh", *args], cwd=cwd, capture_output=True, text=True, **kw)


def open_pr(repo, branch, base, slug, verify_notes, test_summary):
    subprocess.run(["git", "push", "-u", "origin", branch], cwd=repo, capture_output=True, text=True)
    body = (f"Automated by Claude Orchestrator.\n\n"
            f"**Verification (cheap-model review):** {verify_notes}\n"
            f"**Tests:** {test_summary}\n\n"
            f"Branch `{branch}` → `{base}`. CI (sfc/gitleaks/vercel/preflight) gates this merge.")
    r = _gh(["pr", "create", "--base", base, "--head", branch,
             "--title", f"[orchestrator] {slug}", "--body", body], repo)
    if r.returncode != 0 and "already exists" not in (r.stderr or ""):
        return {"ok": False, "error": r.stderr.strip()}
    num = _gh(["pr", "view", branch, "--json", "number", "-q", ".number"], repo).stdout.strip()

    # digital-twin: create an isolated Supabase branch for this PR
    if TWIN_ENABLED and num:
        try:
            twin = supabase_twin.create(num, branch_name=f"pr-{num}")
            if twin.get("db_host"):
                supabase_twin.vercel_env_update(num, twin["db_host"])
        except Exception as e:
            print(f"pr_integrate: twin creation warning ({e})")

    return {"ok": True, "pr": num}


def wait_and_merge(repo, branch):
    """Poll checks; auto-merge on green. Returns MERGED | CHECKS_FAILED | OPEN."""
    waited = 0
    pr_num = None
    try:
        pr_num = _gh(["pr", "view", branch, "--json", "number", "-q", ".number"], repo).stdout.strip()
    except Exception:
        pass

    while waited < MAX_WAIT:
        r = _gh(["pr", "checks", branch, "--json", "state,bucket"], repo)
        try:
            checks = json.loads(r.stdout or "[]")
        except Exception:
            checks = []
        if checks:
            buckets = {c.get("bucket") for c in checks}
            if "fail" in buckets:
                return "CHECKS_FAILED"
            if buckets and buckets.issubset({"pass", "skipping"}):
                if AUTO_MERGE:
                    m = _gh(["pr", "merge", branch, "--squash", "--auto", "--delete-branch"], repo)
                    outcome = "MERGED" if m.returncode == 0 else "OPEN"
                    # digital-twin cleanup on merge
                    if outcome == "MERGED" and TWIN_ENABLED and pr_num:
                        try:
                            supabase_twin.delete(pr_num)
                        except Exception as e:
                            print(f"pr_integrate: twin delete warning ({e})")
                    return outcome
                return "OPEN"
        time.sleep(POLL); waited += POLL
    return "OPEN"
