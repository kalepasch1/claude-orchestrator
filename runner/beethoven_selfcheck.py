#!/usr/bin/env python3
"""Watch what agents merge into the orchestrator itself, and stop them if it breaks it.

WHY THIS PROJECT IS DIFFERENT FROM EVERY OTHER ONE ON THE FLEET.

`beethoven`'s repo_path IS this orchestrator. A merge into it changes the code that
gates the NEXT merge. Every other project can be judged by the trains; beethoven is
the trains. A change that passes its own suite can still break the machinery that
would have caught the following one, and by then the thing that catches mistakes is
the thing that is broken.

That is not hypothetical. During the 2026-09-03 session, changes to this repo that
each passed their own targeted tests went on to:

  * break seven merge_train tests by making the card path depend on the host's load
  * drop a self-heal, so a failed staging publish left a red release and nothing
    working on it
  * reintroduce a tail truncation that a guard test exists specifically to forbid

Every one was caught by running a WIDER suite than the change appeared to need. This
module makes that reflex automatic for the one repo where the cost of missing it is
the fleet's own gates.

WHAT IT DOES.

Differential, not absolute. It runs the impacted tests at the base commit and at the
merged commit and compares. A test that was already red stays the base's problem; a
test that goes green -> red is the merge's. Blaming a merge for a pre-existing
failure would train everyone to ignore this, which is worse than not having it.

Impacted means: the test files that name the modules the merge touched, plus a small
always-run core (the trains and the push guard) because those are what the fleet's
safety rests on. Bounded by a test-file cap and a wall-clock timeout, because a
self-check that outruns the merge interval is a self-check nobody keeps.

ON REGRESSION it records a runner_alert and, when ORCH_BEETHOVEN_AUTOPAUSE is on,
pauses beethoven again. Pausing is reversible and costs a queue; letting agents keep
merging into broken orchestrator machinery is not reversible in the same cheap way.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

RUNNER_DIR = os.path.dirname(os.path.abspath(__file__))

#: Always run these, whatever the diff touched: they are the machinery every other
#: project's safety depends on, so a beethoven merge that breaks one is a fleet-wide
#: event even when the diff looks unrelated.
CORE_TESTS = (
    "tests/test_merge_train.py",
    "tests/test_production_push_guard.py",
    "tests/test_release_push_fast_forward.py",
)

#: A self-check that outruns the merge interval is a self-check nobody keeps.
MAX_TEST_FILES = int(os.environ.get("ORCH_BEETHOVEN_MAX_TEST_FILES", "12"))
TIMEOUT_S = int(os.environ.get("ORCH_BEETHOVEN_SELFCHECK_TIMEOUT_S", "900"))

ALERT_KIND = "beethoven_selfcheck_regression"


def _git(repo, *args, timeout=60):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True,
                          text=True, timeout=timeout)


def changed_modules(repo, before, after):
    """Runner module basenames touched between two commits, without .py."""
    result = _git(repo, "diff", "--name-only", f"{before}..{after}")
    if result.returncode:
        return []
    names = []
    for path in result.stdout.split():
        if not path.startswith("runner/") or not path.endswith(".py"):
            continue
        if "/tests/" in path:
            continue
        names.append(os.path.basename(path)[:-3])
    return sorted(set(names))


def impacted_tests(repo, before, after, tests_dir=None):
    """Test files worth running for this merge: core, plus anything naming a changed module.

    Substring matching on purpose. `test_qa_overlay_is_a_git_repository.py` does not
    contain "commit_overlay", but `test_delivery_accelerators.py` does -- and it was
    the file that caught the overlay change breaking a worktree-registration assertion.
    Matching by module name inside the test's own source finds the tests that actually
    exercise the module, not just the ones named after it.
    """
    tests_dir = tests_dir or os.path.join(RUNNER_DIR, "tests")
    modules = changed_modules(repo, before, after)
    chosen = [t for t in CORE_TESTS
              if os.path.isfile(os.path.join(os.path.dirname(tests_dir), t))]
    if not modules:
        return chosen
    pattern = re.compile("|".join(re.escape(m) for m in modules))
    try:
        entries = sorted(os.listdir(tests_dir))
    except OSError:
        return chosen
    for name in entries:
        if not (name.startswith("test_") and name.endswith(".py")):
            continue
        rel = f"tests/{name}"
        if rel in chosen:
            continue
        path = os.path.join(tests_dir, name)
        try:
            with open(path, encoding="utf-8", errors="replace") as handle:
                body = handle.read()
        except OSError:
            continue
        if pattern.search(name) or pattern.search(body):
            chosen.append(rel)
        if len(chosen) >= MAX_TEST_FILES:
            break
    return chosen


def failing_tests(repo, test_files, timeout=None):
    """{nodeid} that failed, or None when the run could not be completed.

    None is NOT an empty set. A run that could not happen says nothing about the
    merge, and reporting "no failures" for it would turn a broken self-check into a
    green light -- the exact shape of the bug this whole session kept finding.
    """
    if not test_files:
        return set()
    cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
           "--no-header", "-rf", *test_files]
    try:
        result = subprocess.run(cmd, cwd=os.path.join(repo, "runner"),
                                capture_output=True, text=True,
                                timeout=timeout or TIMEOUT_S)
    except (subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode not in (0, 1):        # 0 = green, 1 = tests failed
        return None
    failed = set()
    for line in (result.stdout or "").splitlines():
        if line.startswith("FAILED "):
            failed.add(line.split(" ", 1)[1].split(" - ")[0].strip())
    return failed


def verify_merge(repo, before, after, test_files=None):
    """Did this merge break something that worked before it? Never raises.

    Returns {"ok", "newly_failing", "already_failing", "tests", "reason"}.
    """
    out = {"ok": True, "newly_failing": [], "already_failing": [],
           "tests": [], "reason": ""}
    try:
        files = test_files if test_files is not None else \
            impacted_tests(repo, before, after)
        out["tests"] = list(files)
        if not files:
            out["reason"] = "no impacted test files; nothing to compare"
            return out
        after_failed = failing_tests(repo, files)
        if after_failed is None:
            out["reason"] = "self-check could not run at the merged commit"
            return out
        if not after_failed:
            out["reason"] = f"{len(files)} test file(s) green at the merged commit"
            return out
        # Something is red. Only now is it worth paying for the baseline run --
        # most merges are green and never reach this.
        before_failed = _failures_at(repo, before, files)
        if before_failed is None:
            out["reason"] = ("red at the merged commit, and the base could not be "
                             "measured to say whether the merge caused it")
            out["already_failing"] = []
            out["newly_failing"] = sorted(after_failed)
            out["ok"] = False
            return out
        out["already_failing"] = sorted(after_failed & before_failed)
        out["newly_failing"] = sorted(after_failed - before_failed)
        out["ok"] = not out["newly_failing"]
        out["reason"] = (f"{len(out['newly_failing'])} newly failing, "
                         f"{len(out['already_failing'])} already failing at the base")
        return out
    except Exception as exc:
        out["reason"] = f"self-check error: {type(exc).__name__}: {exc}"
        return out


def _failures_at(repo, ref, files):
    """Failures at `ref`, measured in a throwaway overlay so the live tree never moves.

    Checking the base out in place would swap the orchestrator's own source from under
    the running fleet. commit_overlay materialises a commit without touching the repo.
    """
    try:
        import commit_overlay
        with commit_overlay.checkout(repo, ref, prefix="beethoven-baseline-") as overlay:
            return failing_tests(overlay["path"], files)
    except Exception:
        return None


def report(repo, before, after, result=None):
    """Record the verdict; alert and optionally re-pause when a merge broke something."""
    result = result or verify_merge(repo, before, after)
    if result.get("ok"):
        return result
    detail = (f"beethoven merge {before[:12]}..{after[:12]} broke "
              f"{len(result['newly_failing'])} test(s) that passed at the base: "
              + ", ".join(result["newly_failing"][:10]))[:2000]
    print(f"[beethoven-selfcheck] {detail}", flush=True)
    try:
        import db
        db.insert("runner_alerts", {"kind": ALERT_KIND, "detail": detail,
                                    "resolved": False})
    except Exception as exc:
        print(f"[beethoven-selfcheck] could not record alert ({exc})", flush=True)
    if os.environ.get("ORCH_BEETHOVEN_AUTOPAUSE", "true").lower() in (
            "1", "true", "yes", "on"):
        _repause(detail)
    return result


def _repause(detail):
    """Stop agents merging into the orchestrator until a person has looked.

    Reversible and cheap: it costs a queue. The alternative -- agents continuing to
    merge into machinery whose own tests just went red -- is not reversible in the
    same cheap way, because the thing that would catch the next mistake is the thing
    that just broke.
    """
    try:
        import db
        db.update("controls", {"scope": "project", "project": "beethoven"},
                  {"paused": True, "updated_by": "beethoven-selfcheck",
                   "reason": ("AUTO-PAUSED by beethoven_selfcheck: " + detail +
                              " — REVERSIBLE: set paused=false once the regression is "
                              "understood or fixed.")[:2000]})
        print("[beethoven-selfcheck] beethoven re-paused pending review", flush=True)
    except Exception as exc:
        print(f"[beethoven-selfcheck] could not re-pause ({exc})", flush=True)


if __name__ == "__main__":
    repo = os.path.dirname(RUNNER_DIR)
    before, after = (sys.argv[1], sys.argv[2]) if len(sys.argv) > 2 else ("HEAD~1", "HEAD")
    print(json.dumps(verify_merge(repo, before, after), indent=2))
