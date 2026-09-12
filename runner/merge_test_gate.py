#!/usr/bin/env python3
"""
merge_test_gate.py — CI/CD pipeline integration to run tests as part of the merge process.

Before a task branch merges into its base, this gate:
1. Discovers applicable tests (from runner/tests/ matching the changed modules)
2. Runs them in-process or dispatches to CI
3. Blocks the merge if tests fail

Integrates with merge_validator, ci_dispatch, and the existing test framework.
Fail-soft: on import/config errors, degrades to pass-through.

Branch preflight (added 2026-08-24)
-----------------------------------
Step 1 used to be the *only* step, and it could not tell "this branch changed
nothing" apart from "this branch does not exist". `_find_changed_modules` runs
`git diff base...branch` and returns [] on every failure path — bad repo path,
non-zero exit, timeout, exception — and `check_merge` reads [] as
`{"passed": True, "reason": "no changed modules"}`. So a task whose agent/
branch was never pushed, or whose base ref is gone, produced a *green* merge
gate. A missing branch is the one thing this gate is supposed to catch before a
merge into a main branch, and it was the one thing it waved through.

`_preflight()` now answers three questions before any test is discovered:
does the base ref resolve, does the task branch resolve, and do the two merge
cleanly. Each answer is tri-state. Only a *positive* "no" blocks the merge;
"could not determine" (no git, no repo checkout, timeout) still degrades to
pass-through, so a broken toolchain on one host does not stall the fleet.
"""
import os
import sys
import subprocess
import time
import json
import logging

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

log = logging.getLogger("merge_test_gate")

ENABLED = os.environ.get("ORCH_MERGE_TEST_GATE", "true").lower() == "true"
PREFLIGHT_ENABLED = os.environ.get(
    "ORCH_MERGE_GATE_BRANCH_PREFLIGHT", "true").lower() == "true"
TEST_TIMEOUT_S = int(os.environ.get("ORCH_MERGE_TEST_TIMEOUT_S", "120"))
GIT_TIMEOUT_S = int(os.environ.get("ORCH_MERGE_GATE_GIT_TIMEOUT_S", "30"))
HOME = os.environ.get("CLAUDE_ORCH_HOME", os.path.expanduser("~/.claude-orchestrator"))
RESULTS_DIR = os.path.join(HOME, "merge-test-results")

_stats = {"runs": 0, "passed": 0, "failed": 0, "skipped": 0,
          "blocked_missing_branch": 0, "blocked_conflict": 0,
          "preflight_undetermined": 0}


def stats():
    return dict(_stats)


# ---------------------------------------------------------------------------
# Branch preflight
#
# Every helper below is tri-state on purpose: True / False / None.
#   True  — verified good
#   False — verified bad, block the merge
#   None  — could not determine, keep the historical pass-through behaviour
# Collapsing None into either extreme is what produced the original defect
# (everything collapsed to "fine"), so resist the urge to tidy it away.
# ---------------------------------------------------------------------------

def _git(repo, args, timeout=None):
    """Run a git command. Returns CompletedProcess, or None if it could not run."""
    if not repo or not os.path.isdir(repo):
        return None
    try:
        return subprocess.run(["git"] + list(args), cwd=repo,
                              capture_output=True, text=True,
                              timeout=timeout or GIT_TIMEOUT_S)
    except Exception:
        return None


def _ref_exists(repo, ref):
    """Does `ref` resolve in this repo? True / False / None (undetermined).

    Prefers branch_availability_check, which already owns this question and
    caches the answer fleet-wide; falls back to a direct rev-parse so the gate
    keeps working if that module is unavailable.
    """
    if not ref:
        return None
    try:
        import branch_availability_check as bac
        got = bac.branch_exists_local(repo, ref)
        if got is not None:
            return bool(got)
    except Exception:
        pass
    r = _git(repo, ["rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"])
    if r is None:
        return None
    return r.returncode == 0


def _resolve_ref(repo, ref):
    """First form of `ref` that resolves: itself, then origin/<ref>. None if neither."""
    for cand in (ref, f"origin/{ref}"):
        if _ref_exists(repo, cand):
            return cand
    return None


def _merges_cleanly(repo, base, branch):
    """Would merging `branch` into `base` conflict? True / False / None.

    `git merge-tree --write-tree` (git >= 2.38) does this without touching the
    working tree, which matters because this gate runs on hosts that have live
    worktrees checked out. Exit 0 = clean, 1 = conflicts, anything else (or an
    older git that rejects the flag) = undetermined.
    """
    r = _git(repo, ["merge-tree", "--write-tree", "--name-only", base, branch])
    if r is None:
        return None
    if r.returncode == 0:
        return True
    if r.returncode == 1:
        return False
    return None


def _preflight(repo_path, branch, base):
    """Verify the merge is even possible. Returns a failure dict, or None if OK."""
    if not PREFLIGHT_ENABLED:
        return None

    def _fail(reason, detail):
        return {"passed": False, "tests_run": 0, "tests_passed": 0,
                "tests_failed": 0, "details": [], "reason": reason,
                "preflight": detail}

    if not repo_path or not os.path.isdir(repo_path):
        # No checkout on this host — genuinely undetermined, not a bad branch.
        _stats["preflight_undetermined"] += 1
        return None

    base_ref = _resolve_ref(repo_path, base)
    if base_ref is None and _ref_exists(repo_path, base) is False:
        _stats["blocked_missing_branch"] += 1
        return _fail("base branch missing",
                     f"base ref {base!r} does not resolve in {repo_path}")
    if base_ref is None:
        _stats["preflight_undetermined"] += 1
        return None

    if _ref_exists(repo_path, branch) is False:
        _stats["blocked_missing_branch"] += 1
        return _fail("task branch missing",
                     f"branch {branch!r} does not exist in {repo_path}; "
                     "there is nothing to merge and no diff to test")

    if _merges_cleanly(repo_path, base_ref, branch) is False:
        _stats["blocked_conflict"] += 1
        return _fail("merge conflict",
                     f"{branch!r} does not merge cleanly into {base_ref!r}")

    return None


def _find_changed_modules(repo_path, branch, base):
    """Find Python modules changed between branch and base."""
    if not repo_path or not os.path.isdir(repo_path):
        return []
    try:
        r = subprocess.run(
            ["git", "diff", "--name-only", f"{base}...{branch}"],
            cwd=repo_path, capture_output=True, text=True, timeout=30
        )
        if r.returncode != 0:
            return []
        return [f for f in r.stdout.strip().split("\n")
                if f.endswith(".py") and not f.startswith("tests/")]
    except Exception:
        return []


def _find_matching_tests(changed_modules, repo_path):
    """Find test files that correspond to changed modules."""
    test_dir = os.path.join(repo_path, "runner", "tests")
    if not os.path.isdir(test_dir):
        return []

    tests = []
    for mod in changed_modules:
        base_name = os.path.basename(mod).replace(".py", "")
        candidates = [
            os.path.join(test_dir, f"test_{base_name}.py"),
            os.path.join(repo_path, "runner", f"test_{base_name}.py"),
        ]
        for c in candidates:
            if os.path.isfile(c):
                tests.append(c)
    return list(set(tests))


def _run_test_file(test_path, timeout=None):
    """Run a single test file with pytest or unittest. Returns (passed, output)."""
    timeout = timeout or TEST_TIMEOUT_S
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pytest", test_path, "-x", "--tb=short", "-q"],
            capture_output=True, text=True, timeout=timeout,
            cwd=os.path.dirname(test_path)
        )
        passed = r.returncode == 0
        output = (r.stdout + r.stderr)[-2000:]  # truncate
        return passed, output
    except subprocess.TimeoutExpired:
        return False, f"timeout after {timeout}s"
    except Exception as e:
        # Fall back to direct execution
        try:
            r = subprocess.run(
                [sys.executable, test_path],
                capture_output=True, text=True, timeout=timeout,
                cwd=os.path.dirname(test_path)
            )
            return r.returncode == 0, (r.stdout + r.stderr)[-2000:]
        except Exception as e2:
            return False, str(e2)


def check_merge(task, repo_path=""):
    """Run the merge test gate for a task.

    Returns dict with:
        'passed': bool — True if all tests pass or no tests found
        'tests_run': int
        'tests_passed': int
        'tests_failed': int
        'details': list of {file, passed, output}
    """
    if not ENABLED:
        _stats["skipped"] += 1
        return {"passed": True, "tests_run": 0, "tests_passed": 0,
                "tests_failed": 0, "details": [], "skipped": True}

    slug = (task or {}).get("slug", "unknown")
    branch = f"agent/{slug}"
    base = (task or {}).get("base_branch") or "master"
    _stats["runs"] += 1

    if not repo_path:
        try:
            import db
            proj = db.select("projects", {
                "id": f"eq.{task.get('project_id')}",
                "select": "repo_path", "limit": "1"
            })
            if proj:
                repo_path = proj[0].get("repo_path", "")
                repo_path = db.localize_repo_path(repo_path)
        except Exception:
            pass

    # Preflight BEFORE diffing. `_find_changed_modules` cannot distinguish an
    # empty diff from a failed one, so if the branch is missing this is the
    # only place the difference is still visible.
    blocked = _preflight(repo_path, branch, base)
    if blocked is not None:
        _stats["failed"] += 1
        log.warning("merge gate blocked %s: %s (%s)", slug,
                    blocked.get("reason"), blocked.get("preflight"))
        _persist_result(slug, blocked)
        return blocked

    changed = _find_changed_modules(repo_path, branch, base)
    if not changed:
        return {"passed": True, "tests_run": 0, "tests_passed": 0,
                "tests_failed": 0, "details": [], "reason": "no changed modules"}

    test_files = _find_matching_tests(changed, repo_path)
    if not test_files:
        return {"passed": True, "tests_run": 0, "tests_passed": 0,
                "tests_failed": 0, "details": [], "reason": "no matching tests"}

    details = []
    tests_passed = 0
    tests_failed = 0

    for tf in test_files:
        passed, output = _run_test_file(tf)
        details.append({"file": os.path.basename(tf), "passed": passed, "output": output[:500]})
        if passed:
            tests_passed += 1
        else:
            tests_failed += 1

    all_passed = tests_failed == 0

    if all_passed:
        _stats["passed"] += 1
    else:
        _stats["failed"] += 1

    result = {
        "passed": all_passed,
        "tests_run": len(test_files),
        "tests_passed": tests_passed,
        "tests_failed": tests_failed,
        "details": details,
    }

    _persist_result(slug, result)
    return result


def _persist_result(slug, result):
    """Save test result for audit."""
    try:
        os.makedirs(RESULTS_DIR, exist_ok=True)
        path = os.path.join(RESULTS_DIR, f"{slug}-{int(time.time())}.json")
        with open(path, "w") as f:
            json.dump(result, f, indent=2)
    except Exception:
        pass


def run():
    """Periodic entry — check recently DONE tasks that haven't been test-gated."""
    if not ENABLED:
        return
    try:
        import db
        candidates = db.select("tasks", {
            "select": "id,slug,project_id,base_branch",
            "state": "eq.DONE",
            "order": "updated_at.desc",
            "limit": "3",
        }) or []

        projects = {p["id"]: p for p in (db.select("projects", {"select": "id,repo_path"}) or [])}

        for task in candidates:
            marker_key = f"merge_test_{task.get('slug')}"
            existing = db.select("fleet_config", {"key": f"eq.{marker_key}", "limit": "1"})
            if existing:
                continue

            proj = projects.get(task.get("project_id"), {})
            repo_path = proj.get("repo_path", "")
            try:
                repo_path = db.localize_repo_path(repo_path)
            except Exception:
                pass

            result = check_merge(task, repo_path)
            try:
                db.upsert("fleet_config", {"key": marker_key,
                                            "value": json.dumps({"passed": result.get("passed"),
                                                                  "tests_run": result.get("tests_run")})})
            except Exception:
                pass
    except Exception as e:
        log.warning("merge_test_gate periodic run error: %s", e)
