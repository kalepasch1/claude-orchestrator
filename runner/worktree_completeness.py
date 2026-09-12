#!/usr/bin/env python3
"""
worktree_completeness.py - refuse to build or test in a half-checked-out worktree.

THE DEFECT THIS EXISTS FOR (observed 2026-09-12, this repo, on a live executor run):

`git worktree add` inherits sparse-checkout from the parent repository. This repo's
.git/info/sparse-checkout is

    /*
    !/*/
    /docs/

which means: top-level files and docs/ ONLY. Every new worktree therefore came up with
no runner/, no tests/, no scripts/, no packages/. `git ls-files` listed those files and
`git status` happily staged them, because the index is complete -- only the DISK is not.

What that does to an agent is the repository's house defect in its purest form: a control
that reads as enforced and is not.

  - `pytest runner/tests/...` answers "no tests ran". That is exit 5, not a red suite, and
    it reads as "nothing to do" rather than "your checkout is missing".
  - A cherry-pick or patch apply SUCCEEDS -- it writes the index -- so the agent sees a
    clean apply and a passing (empty) test run, and concludes the work is done.
  - docs/ is the one directory that IS present, which is the likeliest reason so many
    retry branches in this repo contain nothing but a docs/*.md verification note: docs/
    was the only place an agent could actually write and then read back.

So the failure is silent, self-confirming, and points the agent at the wrong root cause.
Branches accumulate ("fix-broken-tests-*" x30 on a single slug) while the tests were never
on disk to break.

The check is cheap: `git ls-files -v` marks every sparse-excluded path with `S`
(skip-worktree). One subprocess, no stat() walk.

FAIL-LOUD ON PURPOSE. Everything else in this module is fail-soft -- an unreadable repo is
reported complete, because wrongly blocking real work is worse than one missed check. But a
worktree that IS provably sparse is refused, because the alternative is the silent green
above. `repair()` fixes it in place rather than just complaining, since the fix is one
command and the caller almost always wants it.

Entry points:
    inspect(path)                  -> dict, never raises
    ensure_complete(path, repair=) -> (ok, detail)
"""
import os
import subprocess

NAME = "worktree-completeness"

# Opt-out for the rare legitimate sparse checkout (a deliberate partial clone of a
# monorepo, say). Default on: the defect above is silent, so the guard must be too
# cheap to be worth disabling casually.
ENABLED = os.environ.get("ORCH_WORKTREE_COMPLETENESS_ENABLED", "true").lower() in (
    "1", "true", "yes", "on",
)

# How many missing paths to carry in the detail string. The count is what matters; the
# sample is there so a log line names real files instead of just a number.
SAMPLE = 8


def _git(path, *args, timeout=30):
    """(rc, stdout). Fail-soft: any failure to even run git is (1, '')."""
    try:
        out = subprocess.run(
            ["git", *args], cwd=path, capture_output=True, text=True, timeout=timeout
        )
        return out.returncode, (out.stdout or "")
    except Exception:
        return 1, ""


def is_git_worktree(path):
    rc, out = _git(path, "rev-parse", "--is-inside-work-tree")
    return rc == 0 and out.strip() == "true"


def sparse_enabled(path):
    """core.sparseCheckout, as git actually resolves it for THIS worktree.

    Read through `git config` rather than by reading .git/config: the setting can live in
    config.worktree (per-worktree) and shadow the shared value, which is exactly how this
    repo ended up with sparse=false in .git/config and true in .git/config.worktree.
    """
    rc, out = _git(path, "config", "--get", "core.sparseCheckout")
    return rc == 0 and out.strip().lower() in ("1", "true", "yes", "on")


def skipped_paths(path, limit=None):
    """Tracked paths the index has but the working tree does not.

    `git ls-files -v` prefixes each entry with its status letter; lowercase or `S` means
    skip-worktree, which is how sparse-checkout excludes a path. This is the precise
    signal -- it is what sparse-checkout SETS -- and it costs one subprocess.
    """
    rc, out = _git(path, "ls-files", "-v")
    if rc != 0:
        return []
    found = []
    for line in out.splitlines():
        if len(line) > 2 and line[0] == "S" and line[1] == " ":
            found.append(line[2:])
            if limit is not None and len(found) >= limit:
                break
    return found


def inspect(path):
    """Structured verdict. Never raises, never blocks on its own.

    complete=True is the fail-soft answer for anything unreadable: a path that is not a
    git worktree, or a git that would not run, is not evidence of a sparse checkout.
    """
    verdict = {
        "path": path,
        "checked": False,
        "sparse": False,
        "missing_count": 0,
        "missing_sample": [],
        "complete": True,
        "reason": "",
    }
    if not ENABLED:
        verdict["reason"] = "disabled by ORCH_WORKTREE_COMPLETENESS_ENABLED"
        return verdict
    if not path or not os.path.isdir(path) or not is_git_worktree(path):
        verdict["reason"] = "not a git worktree; nothing to check"
        return verdict

    verdict["checked"] = True
    verdict["sparse"] = sparse_enabled(path)
    missing = skipped_paths(path)
    verdict["missing_count"] = len(missing)
    verdict["missing_sample"] = missing[:SAMPLE]

    # The skip-worktree list is the symptom that actually hurts. Trust it over the config
    # flag: a worktree can carry stale skip-worktree bits with the flag already off, and
    # that checkout is just as incomplete.
    if missing:
        verdict["complete"] = False
        verdict["reason"] = (
            f"{len(missing)} tracked path(s) are in the index but not on disk "
            f"(sparse-checkout skip-worktree). Sample: {', '.join(missing[:SAMPLE])}"
        )
    elif verdict["sparse"]:
        # Flag on, nothing excluded yet. Not broken, but the next checkout can make it so.
        verdict["reason"] = "core.sparseCheckout is on, but no path is currently skipped"
    else:
        verdict["reason"] = "complete"
    return verdict


def repair(path):
    """Turn a sparse worktree into a full one, in place. (ok, log).

    `git sparse-checkout disable` both clears the flag and re-materializes the skipped
    paths, so this is the whole fix. Re-inspect afterwards rather than trusting the exit
    code -- the point of this module is not believing a control that says it worked.
    """
    rc, out = _git(path, "sparse-checkout", "disable", timeout=300)
    after = inspect(path)
    if after["complete"]:
        return True, "sparse-checkout disabled; worktree is complete"
    return False, f"repair failed (rc={rc}): {after['reason']} {out}".strip()


def ensure_complete(path, repair_if_sparse=True):
    """(ok, detail) -- the one callers should use before building or testing.

    Repairs by default. A sparse worktree is never what the caller wanted; refusing
    without fixing would just move the silent failure one step later.
    """
    verdict = inspect(path)
    if verdict["complete"]:
        return True, verdict["reason"]
    if not repair_if_sparse:
        return False, verdict["reason"]
    ok, log = repair(path)
    if ok:
        print(f"[{NAME}] repaired sparse worktree {path}: {verdict['reason']}")
    return ok, log
