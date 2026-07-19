#!/usr/bin/env python3
"""
git_branch_scanner.py - proactively detect and fix missing agent branches.

Complements integration_sweeper, which only sweeps DONE/BLOCKED tasks after work
is verified. This scanner covers the full active task set — QUEUED, RUNNING, DONE,
BLOCKED — and records a structured branch-issue manifest in the controls table for
dashboard visibility. The fix() path reuses the same recovery-task pattern as
integration_sweeper so recovery_dedup logic applies fleet-wide.

Usage:
    python runner/git_branch_scanner.py          # detect + store + fix
    python -c "import git_branch_scanner; git_branch_scanner.detect()"
"""
import datetime
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

CONTROL_KEY = "git_branch_issues"
SCAN_STATES = ("QUEUED", "RUNNING", "DONE", "BLOCKED")
RECOVERY_PREFIX = db.RECOVERY_PREFIX
SCAN_LIMIT = int(os.environ.get("GIT_BRANCH_SCANNER_LIMIT", "500") or 500)
# Only flag tasks older than this — agent may still be running on very new tasks.
MIN_AGE_SECONDS = int(os.environ.get("GIT_BRANCH_SCANNER_MIN_AGE_S", "300") or 300)


def _branch_exists_local(repo, branch):
    if not repo or not os.path.isdir(repo):
        return False
    return subprocess.run(
        ["git", "rev-parse", "--verify", branch],
        cwd=repo, capture_output=True,
    ).returncode == 0


def _branch_exists_remote(repo, branch):
    if not repo or not os.path.isdir(repo):
        return False
    return subprocess.run(
        ["git", "rev-parse", "--verify", f"refs/remotes/origin/{branch}"],
        cwd=repo, capture_output=True,
    ).returncode == 0


def _branch_exists(repo, branch):
    return _branch_exists_local(repo, branch) or _branch_exists_remote(repo, branch)


def _age_seconds(ts):
    if not ts:
        return 0
    raw = str(ts).replace("Z", "+00:00")
    try:
        dt = datetime.datetime.fromisoformat(raw)
        now = datetime.datetime.now(dt.tzinfo) if dt.tzinfo else datetime.datetime.utcnow()
        return max(0, int((now - dt).total_seconds()))
    except Exception:
        return 0


def detect(limit=SCAN_LIMIT, min_age_s=MIN_AGE_SECONDS):
    """Scan active tasks; return list of branch-issue dicts for missing branches."""
    projects = {p["id"]: p for p in (db.select("projects") or [])}
    state_filter = "in.(" + ",".join(SCAN_STATES) + ")"
    rows = db.select(
        "tasks",
        {"select": "id,slug,project_id,state,note,created_at",
         "state": state_filter,
         "order": "created_at.asc",
         "limit": str(limit)},
    ) or []
    issues = []
    for t in rows:
        slug = t.get("slug") or ""
        if not slug or RECOVERY_PREFIX in slug:
            continue  # skip recovery/rework slugs — nesting guard
        if _age_seconds(t.get("created_at")) < min_age_s:
            continue  # too new; agent may still be creating the branch
        proj = projects.get(t.get("project_id")) or {}
        repo = proj.get("repo_path", "")
        branch = f"agent/{slug}"
        if not _branch_exists(repo, branch):
            issues.append({
                "task_id": t["id"],
                "slug": slug,
                "project_id": t.get("project_id"),
                "project_name": proj.get("name", ""),
                "repo_path": repo,
                "branch": branch,
                "task_state": t.get("state"),
                "age_seconds": _age_seconds(t.get("created_at")),
                "issue_type": "missing_branch",
            })
    return issues


def store_issues(issues):
    """Persist the issue manifest to the controls table for dashboard/query access."""
    payload = {
        "generated_at": datetime.datetime.utcnow().isoformat(),
        "count": len(issues),
        "issues": issues,
    }
    try:
        db.insert(
            "controls",
            {"key": CONTROL_KEY, "value": json.dumps(payload), "updated_at": "now()"},
            upsert=True,
        )
    except Exception as e:
        print(f"[git_branch_scanner] store_issues error: {e}")
    return payload


def fix(issues):
    """Queue recovery tasks for detected missing-branch issues.

    Reuses the RECOVERY_PREFIX convention so integration_sweeper's recovery_dedup
    logic deduplicates across both code paths.
    """
    queued = 0
    skipped = 0
    for issue in issues:
        slug = issue.get("slug")
        project_id = issue.get("project_id")
        if not slug or not project_id:
            skipped += 1
            continue
        try:
            existing = db.select(
                "tasks",
                {"select": "id",
                 "project_id": f"eq.{project_id}",
                 "slug": f"eq.{RECOVERY_PREFIX}{slug}",
                 "state": "in.(QUEUED,RUNNING,RETRY,DONE,MERGED,BLOCKED)",
                 "limit": "1"},
            ) or []
            if existing:
                skipped += 1
                continue
        except Exception:
            skipped += 1
            continue
        recovery_slug = f"{RECOVERY_PREFIX}{slug}"
        row = {
            "project_id": project_id,
            "slug": recovery_slug,
            "state": "QUEUED",
            "kind": "bugfix",
            "deps": [],
            "force_coder": "ollama",
            "model": "ollama",
            "prompt": (
                f"Recover missing agent branch for task '{slug}'.\n"
                f"Branch '{issue.get('branch')}' is absent from both local and remote.\n"
                "Reconstruct the smallest equivalent patch, commit it, run checks."
            ),
            "note": (
                f"git_branch_scanner: missing branch; task state was {issue.get('task_state')}"
            ),
        }
        try:
            db.insert("tasks", row, upsert=True)
            queued += 1
        except Exception as e:
            print(f"[git_branch_scanner] failed to queue recovery for {slug}: {e}")
            skipped += 1
    return {"queued": queued, "skipped": skipped}


def run(limit=SCAN_LIMIT):
    issues = detect(limit=limit)
    store_issues(issues)
    fix_result = fix(issues)
    summary = {"detected": len(issues), **fix_result}
    print(
        f"git_branch_scanner: detected={len(issues)} "
        f"queued={fix_result['queued']} skipped={fix_result['skipped']}"
    )
    return summary


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, default=str))
