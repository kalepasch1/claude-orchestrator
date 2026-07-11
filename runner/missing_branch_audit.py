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


if __name__ == "__main__":
    main()
