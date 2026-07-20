#!/usr/bin/env python3
"""
branch_gc.py — safe branch garbage collection for merged/quarantined tasks.

Deletes local agent branches whose tasks are in terminal states (DONE,
MERGED, QUARANTINED) and whose branches are older than GC_MIN_AGE_DAYS.
Never touches remote branches — that's the merge train's job.

Env vars:
    ORCH_BRANCH_GC_ENABLED     "true" to enable (default "true")
    ORCH_BRANCH_GC_DRY_RUN     "true" for dry-run (default "true")
    ORCH_BRANCH_GC_MIN_AGE     min age in days before GC (default 3)
    ORCH_BRANCH_GC_BATCH       max branches per run (default 20)
"""
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ENABLED = os.environ.get("ORCH_BRANCH_GC_ENABLED", "true").lower() in ("1", "true", "yes")
DRY_RUN = os.environ.get("ORCH_BRANCH_GC_DRY_RUN", "false").lower() in ("1", "true", "yes")
MIN_AGE_DAYS = int(os.environ.get("ORCH_BRANCH_GC_MIN_AGE", "3"))
BATCH_SIZE = int(os.environ.get("ORCH_BRANCH_GC_BATCH", "100"))
TIMEOUT = 15


def _git(repo, *args):
    try:
        r = subprocess.run(["git"] + list(args), cwd=repo,
                           capture_output=True, text=True, timeout=TIMEOUT)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except Exception as e:
        return -1, "", str(e)


def _branch_age_days(repo_path, branch):
    """Return age of branch in days, or None."""
    rc, out, _ = _git(repo_path, "log", "-1", "--format=%ct", branch)
    if rc != 0 or not out.strip():
        return None
    try:
        return (time.time() - int(out.strip())) / 86400
    except ValueError:
        return None


def collect_garbage(repo_path, terminal_slugs):
    """Delete local agent branches for terminal tasks older than MIN_AGE_DAYS.

    *terminal_slugs* is a set of slugs in DONE/MERGED/QUARANTINED state.
    Returns dict with 'deleted', 'skipped', 'errors'.
    """
    if not ENABLED or not repo_path or not os.path.isdir(repo_path):
        return {"deleted": 0, "skipped": 0, "errors": 0, "reason": "disabled or no repo"}

    rc, out, _ = _git(repo_path, "branch", "--list", "agent/*")
    if rc != 0:
        return {"deleted": 0, "skipped": 0, "errors": 1, "reason": "git branch list failed"}

    branches = [b.strip().lstrip("* ") for b in out.splitlines() if b.strip()]
    deleted = []
    skipped = 0
    errors = 0

    for branch in branches[:BATCH_SIZE]:
        slug = branch.replace("agent/", "", 1) if branch.startswith("agent/") else branch
        if slug not in terminal_slugs:
            skipped += 1
            continue
        age = _branch_age_days(repo_path, branch)
        if age is None or age < MIN_AGE_DAYS:
            skipped += 1
            continue
        if DRY_RUN:
            deleted.append({"branch": branch, "age_days": round(age, 1), "dry_run": True})
        else:
            rc, _, err = _git(repo_path, "branch", "-D", branch)
            if rc == 0:
                deleted.append({"branch": branch, "age_days": round(age, 1), "dry_run": False})
            else:
                errors += 1

    return {"deleted": len(deleted), "skipped": skipped, "errors": errors,
            "dry_run": DRY_RUN, "branches": deleted[:10]}


def run():
    """CLI entry point — collect garbage with terminal slugs from DB."""
    try:
        import db
        rows = db.select("tasks", {
            "select": "slug",
            "state": "in.(DONE,MERGED,QUARANTINED)",
        }) or []
        terminal = {r["slug"] for r in rows if r.get("slug")}
    except Exception:
        terminal = set()

    repo = os.environ.get("ORCH_REPO_PATH",
                          os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    result = collect_garbage(repo, terminal)
    print(f"branch_gc: {result['deleted']} deleted, {result['skipped']} skipped, "
          f"{result['errors']} errors (dry_run={DRY_RUN})")
    return result


if __name__ == "__main__":
    import json
    print(json.dumps(run(), indent=2, default=str))
