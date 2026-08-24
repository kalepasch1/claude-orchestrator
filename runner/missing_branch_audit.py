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


#: Per-`git` wall-clock budget. ORCH_-prefixed so a slow or NFS-backed checkout can be
#: given headroom through fleet_control.py rather than a code change.
GIT_TIMEOUT = int(os.environ.get("ORCH_MISSING_BRANCH_GIT_TIMEOUT", "15") or 15)

#: Columns the audit needs. Named once so main() and auto_recover_missing_branches()
#: cannot drift into scanning different row shapes of the same question.
_AUDIT_COLUMNS = "id,slug,project_id,state"
_RECOVER_COLUMNS = "id,slug,project_id,state,prompt,kind,base_branch"


def _branch_exists(repo, branch):
    if not repo or not os.path.isdir(repo):
        return None  # can't check -- repo not resolvable on this host
    try:
        out = subprocess.run(["git", "rev-parse", "--verify", branch],
                              cwd=repo, capture_output=True, text=True, timeout=GIT_TIMEOUT)
        return out.returncode == 0
    except Exception as e:
        # Logged, not silent: None means "could not check", and it is routed to the
        # `unresolvable_repo` bucket where it is reported as a non-answer. Without this
        # line a git binary that is missing or wedged is indistinguishable from a repo
        # path that does not exist on this host.
        sys.stderr.write(f"[missing_branch_audit] rev-parse {branch!r} in {repo!r} failed "
                         f"({type(e).__name__}: {e}); reporting as unresolvable\n")
        return None


def _all_done_tasks(columns):
    """Every DONE task, paged to exhaustion.

    FULL SCAN, not a window. The previous `db.select(..., "limit": "2000")` could not
    return 2,000 rows: PostgREST caps a single response at 1,000 regardless of `limit`,
    so the audit read an arbitrary, unordered 1,000 DONE tasks and then printed
    "DONE tasks checked: 1000" as though that were the whole set. Every DONE task
    outside that page was structurally invisible — including, by construction, the
    missing branches this module exists to find, and the ones
    auto_recover_missing_branches() would otherwise reconstruct. An audit that silently
    answers about a subset is worse than no audit, because its clean result is believed.
    """
    return db.select_all("tasks", {"select": columns, "state": "eq.DONE"},
                         order="id.asc") or []


def main():
    projects = {p["id"]: p for p in (db.select_all("projects", {"select": "*"},
                                                   order="id.asc") or [])}
    done_tasks = _all_done_tasks(_AUDIT_COLUMNS)

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
        projects = {p["id"]: p for p in (db.select_all("projects", {"select": "*"},
                                                       order="id.asc") or [])}
    except Exception as e:
        print(f"auto_recover: DB error fetching projects: {e}")
        return {"recovered": 0, "missing": 0}
    try:
        # Same full scan as main(): a recovery pass that only ever sees the first
        # unordered page can never recover a branch that fell outside it.
        done_tasks = _all_done_tasks(_RECOVER_COLUMNS)
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
