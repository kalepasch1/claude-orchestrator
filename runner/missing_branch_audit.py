#!/usr/bin/env python3
"""
missing_branch_audit.py - standalone diagnostic (not part of the periodic pipeline).

Checks every DONE task's agent/<slug> branch against git, using the SAME repo_path
localization merge_train.py now uses (db.localize_repo_path), to distinguish:
  - genuinely missing branches (real problem, needs requeue/remediation)
  - false positives caused by checking an unlocalized/nonexistent repo path (the bug fixed
    2026-07-11 in merge_train.py; this script proves whether that was the actual cause of
    the "47 DONE tasks with missing agent branches" finding)

Usage: python3 missing_branch_audit.py
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db


def _branch_exists(repo, branch):
    if not repo or not os.path.isdir(repo):
        return None  # can't check -- repo not resolvable on this host
    try:
        out = subprocess.run(["git", "rev-parse", "--verify", branch],
                              cwd=repo, capture_output=True, text=True, timeout=15)
        return out.returncode == 0
    except Exception:
        return None


def main():
    projects = {p["id"]: p for p in (db.select("projects", {"select": "*"}) or [])}
    done_tasks = db.select("tasks", {"select": "id,slug,project_id,state", "state": "eq.DONE",
                                      "limit": "2000"}) or []

    genuinely_missing = []
    false_positives = []
    unresolvable_repo = []

    for t in done_tasks:
        proj = projects.get(t.get("project_id"), {})
        raw_repo = proj.get("repo_path", "")
        localized_repo = db.localize_repo_path(raw_repo)
        branch = f"agent/{t.get('slug')}"

        raw_exists = _branch_exists(raw_repo, branch)
        localized_exists = _branch_exists(localized_repo, branch)

        if localized_exists is None:
            unresolvable_repo.append((t.get("slug"), proj.get("name")))
        elif localized_exists is False:
            genuinely_missing.append((t.get("slug"), proj.get("name")))
        elif raw_exists is not True and localized_exists is True:
            false_positives.append((t.get("slug"), proj.get("name"), raw_repo, localized_repo))

    print(f"DONE tasks checked: {len(done_tasks)}")
    print(f"genuinely missing (branch absent even at localized path): {len(genuinely_missing)}")
    for slug, proj in genuinely_missing[:20]:
        print(f"  MISSING  {proj}: {slug}")
    print(f"false positives (raw path check failed, localized path found it fine): {len(false_positives)}")
    for slug, proj, raw, loc in false_positives[:20]:
        print(f"  FALSE-POS  {proj}: {slug}  (raw={raw} -> localized={loc})")
    print(f"unresolvable repo on this host: {len(unresolvable_repo)}")
    for slug, proj in unresolvable_repo[:20]:
        print(f"  UNRESOLVABLE  {proj}: {slug}")


def auto_recover_missing_branches(dry_run=True, max_recover=10):
    """Detect missing branches for DONE tasks and initiate recovery.

    For each genuinely missing branch, creates a recovery task that will
    re-checkout and re-apply the work from the task's original prompt.

    Args:
        dry_run: If True, only report what would be recovered
        max_recover: Maximum number of recovery tasks to create per run
    """
    import time as _time
    try:
        projects = {p["id"]: p for p in (db.select("projects", {"select": "*"}) or [])}
    except Exception as e:
        print(f"auto_recover: DB error fetching projects: {e}")
        return {"recovered": 0, "missing": 0}
    try:
        done_tasks = db.select("tasks", {
            "select": "id,slug,project_id,state,prompt,kind,base_branch",
            "state": "eq.DONE",
            "limit": "2000",
        }) or []
    except Exception as e:
        print(f"auto_recover: DB error fetching tasks: {e}")
        return {"recovered": 0, "missing": 0}

    missing = []
    for t in done_tasks:
        proj = projects.get(t.get("project_id"), {})
        localized_repo = db.localize_repo_path(proj.get("repo_path", ""))
        branch = f"agent/{t.get('slug')}"
        if _branch_exists(localized_repo, branch) is False:
            missing.append((t, proj))

    if not missing:
        print("auto_recover: no missing branches found")
        return {"recovered": 0, "missing": 0}

    print(f"auto_recover: {len(missing)} missing branches detected")

    recovered = 0
    for t, proj in missing[:max_recover]:
        slug = t.get("slug", "")
        recovery_slug = f"recover-{slug}"

        # Check if recovery task already exists
        existing = db.select("tasks", {
            "select": "id",
            "slug": f"eq.{recovery_slug}",
            "project_id": f"eq.{t.get('project_id')}",
            "limit": "1",
        }) or []
        if existing:
            print(f"  SKIP  {slug}: recovery task already exists")
            continue

        if dry_run:
            print(f"  DRY-RUN  would create recovery task for: {slug}")
            recovered += 1
            continue

        # Create recovery task
        recovery_task = {
            "slug": recovery_slug,
            "project_id": t.get("project_id"),
            "state": "QUEUED",
            "kind": t.get("kind", "build"),
            "prompt": f"Recovery: re-create missing branch agent/{slug}.\nOriginal prompt:\n{t.get('prompt', '')[:2000]}",
            "base_branch": t.get("base_branch", "master"),
            "deps": [],
            "note": f"auto-recovery for missing branch (original task {t.get('id')})",
        }
        try:
            db.insert("tasks", recovery_task)
            recovered += 1
            print(f"  RECOVERED  created recovery task: {recovery_slug}")
        except Exception as exc:
            print(f"  ERROR  failed to create recovery for {slug}: {exc}")

    result = {"recovered": recovered, "missing": len(missing)}
    print(f"auto_recover complete: {recovered}/{len(missing)} recovery tasks created (dry_run={dry_run})")
    return result


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--recover", action="store_true", help="Auto-recover missing branches")
    parser.add_argument("--no-dry-run", action="store_true", help="Actually create recovery tasks")
    parser.add_argument("--max-recover", type=int, default=10, help="Max recovery tasks to create")
    args = parser.parse_args()

    if args.recover:
        auto_recover_missing_branches(dry_run=not args.no_dry_run, max_recover=args.max_recover)
    else:
        main()
