#!/usr/bin/env python3
"""
branch_repair_bot.py - automated branch management: detects missing branches,
resolves simple conflicts, and triggers merges for low-risk DONE tasks.

Runs periodically. For each DONE task whose agent/<slug> branch is missing
or has conflicts with the base branch, it takes remedial action:

  - Missing branch: marks the task for requeue with a recovery slug
  - Conflicting branch: attempts auto-rebase for low-risk (test/docs/chore) tasks
  - Clean branch: flags as merge-ready

Env vars:
    ORCH_BRANCH_REPAIR_BOT       "true" (default) to enable
    ORCH_BRANCH_REPAIR_DRY_RUN   "true" for dry-run mode (default: "true")
    ORCH_BRANCH_REPAIR_BATCH      max tasks per run (default: 10)
"""
import os, sys, subprocess, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import log as _log_mod
_log = _log_mod.get("branch_repair_bot")
import db

ENABLED = os.environ.get("ORCH_BRANCH_REPAIR_BOT", "true").lower() in ("1", "true", "yes", "on")
DRY_RUN = os.environ.get("ORCH_BRANCH_REPAIR_DRY_RUN", "true").lower() in ("1", "true", "yes", "on")
BATCH_SIZE = int(os.environ.get("ORCH_BRANCH_REPAIR_BATCH", "10") or 10)

LOW_RISK_KINDS = {"test", "docs", "chore", "cleanup", "mechanical", "bugfix"}


def _git(repo, *args, timeout=30):
    """Run a git command, return (returncode, stdout, stderr)."""
    try:
        r = subprocess.run(["git"] + list(args), cwd=repo,
                           capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except Exception as e:
        return -1, "", str(e)


def _branch_exists(repo, branch):
    rc, out, _ = _git(repo, "rev-parse", "--verify", branch)
    return rc == 0


def _merge_state(repo, base, branch):
    """"clean" | "conflict" | "unknown" for merging `branch` into `base`.

    THREE states, not two. `git merge-tree` exits non-zero for reasons that are
    not conflicts at all -- "master - not something we can merge" when the base
    branch is named differently here, a corrupt object, an unreadable repo --
    and the old bool collapsed every one of them into "conflict". That is the
    safe direction (it routes to manual) but it is not the true one, and it made
    a project whose base is `main` look like every branch in it conflicted.
    """
    rc, out, _ = _git(repo, "merge-tree", base, branch)
    if rc != 0:
        return "unknown"
    return "conflict" if ("changed in both" in out.lower() or "CONFLICT" in out) else "clean"


def _has_conflicts(repo, base, branch):
    """Bool view of _merge_state: anything that is not provably clean.

    Kept because the conservative reading is the right default for callers that
    can only branch two ways.
    """
    return _merge_state(repo, base, branch) != "clean"


def _auto_rebase(repo, base, branch):
    """Attempt a non-interactive rebase, leaving the checkout where it found it.

    THIS RUNS AGAINST projects.repo_path — the PRIMARY checkout, not a worktree.
    It used to `git checkout <agent branch>` and never come back:

        _git(repo, "checkout", branch)
        rc, _, err = _git(repo, "rebase", base, timeout=60)
        if rc != 0:
            _git(repo, "rebase", "--abort")
            return False
        return True

    That is the same defect 5e9b862a and 8b93a4f2 fixed in
    conflict_auto_resolve.attempt_auto_rebase — "auto-rebase must not park the
    primary checkout on agent branches", 1001 checkout-drift events by
    2026-07-16. The drift is load-bearing rather than cosmetic: while parked on
    an agent branch the repo runs THAT branch's code and honours THAT branch's
    .gitignore, so fixes committed to master go inert exactly when they matter.
    conflict_auto_resolve was later rewritten wholesale and that function
    disappeared, taking the fix with it while this copy survived untouched.
    runner/tests/test_auto_rebase_no_drift.py, which was written for the deleted
    function, now guards this one.

    Nothing currently imports branch_repair_bot, so this has been latent rather
    than active — but `.env.example` documents its three env vars as live
    configuration, so it reads as wired, and a single import would arm it.

    Refuses rather than guesses when the current branch cannot be read (a
    detached HEAD, or an unreadable repo): checking out without knowing where to
    return is precisely how the drift happened.
    """
    rc, original, _ = _git(repo, "branch", "--show-current")
    if rc != 0 or not original:
        _log.info("branch_repair_bot: refusing to rebase %s — current branch of %s "
                  "is unknown (detached HEAD?), so it could not be restored",
                  branch, repo)
        return False

    if original == branch:
        rc, _, _ = _git(repo, "rebase", base, timeout=60)
        if rc != 0:
            _git(repo, "rebase", "--abort")
            return False
        return True

    rc, _, _ = _git(repo, "checkout", branch)
    if rc != 0:
        # Never left, so nothing to restore.
        return False
    try:
        rc, _, _ = _git(repo, "rebase", base, timeout=60)
        if rc != 0:
            _git(repo, "rebase", "--abort")
            return False
        return True
    finally:
        # In a finally, not on the success path: an exception here would
        # otherwise leave the primary checkout parked on the agent branch, which
        # is the failure mode with the widest blast radius in this module.
        _git(repo, "checkout", original)


def _attempt_build_fix(repo, branch, build_log=""):
    """Attempt to fix simple build failures (missing imports, syntax)."""
    if not build_log:
        return False
    # Simple heuristic: if build log mentions ModuleNotFoundError for a known module,
    # check if sys.path insert is missing
    if "ModuleNotFoundError" in build_log or "ImportError" in build_log:
        _log.info(f"Build failure on {branch}: import error detected, marking for rework")
        return False  # cannot auto-fix; queue for rework
    return False


def repo_accessible(repo):
    """True when `repo` is a directory git will actually answer questions about.

    THE DISTINCTION THIS MODULE DID NOT MAKE. _git() catches every exception and
    returns rc=-1, so a repo path that is not mounted, not yet cloned, or simply
    wrong produced exactly the same answer as a repo whose branch really is
    gone: `_branch_exists` False, "branch missing", requeue. One unmounted
    volume would therefore have requeued EVERY DONE task in that project --
    rewriting their state and their slug -- on the strength of a git invocation
    that never ran. DRY_RUN defaults to true, which is the only reason this was
    latent; ORCH_BRANCH_REPAIR_DRY_RUN=false would have armed it.
    """
    if not repo or not os.path.isdir(repo):
        return False
    rc, _, _ = _git(repo, "rev-parse", "--git-dir")
    return rc == 0


def check_task(task, repo):
    """Diagnose one task's branch. Reads only; decides nothing irreversible.

    Returns a dict with:
        status: "check_failed" | "branch_missing" | "conflict" | "clean"
        action: "manual" | "requeue" | "rebase" | "merge_ready"

    "check_failed" means we could not look, which is NOT the same as "nothing
    is there" -- see repo_accessible above. Its action is "manual" so that
    repair_task refuses to act on an answer nobody actually got.
    """
    slug = task.get("slug", "")
    result = {
        "task_id": task.get("id"),
        "slug": slug,
        "branch": f"agent/{slug}",
        "status": "check_failed",
        "action": "manual",
    }
    if not repo_accessible(repo):
        result["reason"] = "repo not accessible"
        return result

    base = task.get("base_branch") or "master"
    if not _branch_exists(repo, result["branch"]):
        result["status"] = "branch_missing"
        result["action"] = "requeue"
        return result

    state = _merge_state(repo, base, result["branch"])
    if state == "conflict":
        result["status"] = "conflict"
        low_risk = (task.get("kind") or "") in LOW_RISK_KINDS
        result["action"] = "rebase" if low_risk else "manual"
        return result
    if state == "unknown":
        # merge-tree could not answer -- most often because `base` does not
        # exist under that name here. Not a conflict, and certainly not a
        # merge-ready branch: say so and let a person look.
        result["status"] = "unknown"
        result["action"] = "manual"
        result["reason"] = f"could not compare {result['branch']} against {base}"
        return result

    result["status"] = "clean"
    result["action"] = "merge_ready"
    return result


def repair_task(task, repo, result):
    """Carry out what check_task decided. Returns result + "executed": bool.

    Every path that does not change something leaves executed False, so a
    caller can count real repairs without re-deriving them from the status.
    """
    out = dict(result)
    out["executed"] = False
    status = result.get("status")
    action = result.get("action")

    if status == "check_failed":
        # Refuse on a non-answer. Requeueing a project's finished work because a
        # volume was unmounted is the worst thing this module can do.
        out["reason"] = "check failed; no action taken"
        return out

    if action not in ("requeue", "rebase"):
        out["reason"] = action or "none"
        return out

    if DRY_RUN:
        out["reason"] = "dry_run"
        return out

    slug = result.get("slug", "")
    if action == "requeue":
        # ARGUMENTS WERE SWAPPED here before. update(table, match, patch): the
        # old call passed the patch as the MATCH and {"id": tid} as the PATCH,
        # so it asked PostgREST to SET id=<tid> on every row matching
        # state/note/slug. The arity is right, which is why a signature check
        # does not catch it.
        db.update("tasks", {"id": result.get("task_id")}, {
            "state": "QUEUED",
            "note": "branch_repair_bot: branch missing, requeued",
            "slug": slug if slug.startswith("recover-") else f"recover-{slug}",
        })
        out["executed"] = True
        return out

    base = task.get("base_branch") or "master"
    out["executed"] = bool(_auto_rebase(repo, base, result["branch"]))
    if not out["executed"]:
        out["reason"] = "rebase_failed"
    return out


def scan_and_repair(repo_path, project_id):
    """Main entry for ONE project: scan DONE tasks and repair their branches."""
    if not ENABLED:
        return {"skipped": True, "reason": "disabled"}

    # PostgREST filters carry an operator: `project_id=eq.<uuid>`, not
    # `project_id=<uuid>`. Bare values are rejected with a 400, so this select
    # could not have returned rows. `limit` must be a string for urlencode.
    tasks = db.select("tasks", {
        "select": "id,slug,kind,base_branch,note",
        "project_id": f"eq.{project_id}",
        "state": "eq.DONE",
        "limit": str(BATCH_SIZE),
    }) or []

    if not repo_accessible(repo_path):
        _log.info("branch_repair_bot: skipping project %s — %s is not a readable "
                  "git repo on this host", project_id, repo_path)
        return {"checked": 0, "skipped": True, "reason": "repo_not_accessible",
                "results": []}

    results = []
    for t in tasks:
        checked = check_task(t, repo_path)
        if checked["status"] == "branch_missing":
            _log.info("Branch missing for %s, marking for recovery", checked["slug"])
        results.append(repair_task(t, repo_path, checked))
    return {"checked": len(tasks), "results": results}


def _local_repo(repo_path):
    """This host's path for a project repo, or the stored path if it cannot map.

    The stored path is another machine's; repo_accessible() will simply report
    it as unreachable, which is the correct outcome and not a crash.
    """
    try:
        return db.localize_repo_path(repo_path)
    except Exception:
        return repo_path


def run(project_id=None):
    """Sweep every project (or one) and repair what it finds. Returns a list.

    branch_repair_bot had no fleet-wide entry point at all: scan_and_repair
    takes one repo and one project id, and nothing in the repository called it,
    so this bot has never run despite .env.example documenting its three env
    vars as live configuration. Projects whose repo is not on this host are
    skipped rather than treated as projects whose branches all vanished.
    """
    if not ENABLED:
        return []
    filt = {"select": "id,repo_path"}
    if project_id:
        filt["id"] = f"eq.{project_id}"
    projects = db.select("projects", filt) or []

    out = []
    for proj in projects:
        summary = scan_and_repair(_local_repo(proj.get("repo_path") or ""),
                                  proj.get("id"))
        summary["project_id"] = proj.get("id")
        out.append(summary)
    return out
