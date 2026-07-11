#!/usr/bin/env python3
"""
merge_validator.py - Speculative merge validation: test drafts before the agent
finishes to fast-track or constrain the agent.

Applies a draft diff in an isolated git worktree, runs the project's test
command, and returns pass/fail plus extracted failure messages.  If the draft
passes, the runner can skip the expensive agent call entirely (fast-track).

Env vars:
    ORCH_MERGE_VALIDATOR_ENABLED   – "true" (default) / "false"
    ORCH_MERGE_VALIDATOR_TIMEOUT   – subprocess timeout in seconds (default 120)
"""
import sys, os, subprocess, threading, time, tempfile, shutil
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import log as _log_mod
_log = _log_mod.get("merge_validator")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
_ENABLED = os.environ.get("ORCH_MERGE_VALIDATOR_ENABLED", "true").lower() == "true"
_TIMEOUT = int(os.environ.get("ORCH_MERGE_VALIDATOR_TIMEOUT", "120"))

# ---------------------------------------------------------------------------
# Thread-safe state
# ---------------------------------------------------------------------------
_lock = threading.Lock()
_validated: dict[str, dict] = {}   # task_id -> validation result
_stats = {
    "validations_run": 0,
    "drafts_passed": 0,
    "drafts_failed": 0,
    "fast_tracks": 0,
    "time_saved_estimate_s": 0.0,
}

_FAIL_SOFT = {
    "valid": False,
    "test_results": "validation unavailable",
    "failures": [],
    "can_fast_track": False,
}


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

def validate_draft(task, draft_diff, repo_path, base_branch, test_cmd):
    """Apply *draft_diff* on a temp worktree of *repo_path*, run *test_cmd*.

    Returns dict with keys: valid, test_results, failures, can_fast_track.
    Never raises -- returns fail-soft result on any error.
    """
    if not _ENABLED:
        return dict(_FAIL_SOFT, test_results="merge_validator disabled")

    task_id = task.get("id") or task.get("slug") or ""
    wt_dir = None
    tmp_branch = f"_mv_{task_id}_{int(time.time())}"
    t0 = time.time()
    try:
        # --- create worktree ---
        wt_dir = tempfile.mkdtemp(prefix="merge_validator_")
        _run_git(repo_path, ["worktree", "add", "-b", tmp_branch, wt_dir, base_branch])

        # --- apply diff ---
        proc = subprocess.run(
            ["git", "apply", "--3way", "-"],
            input=draft_diff,
            cwd=wt_dir,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if proc.returncode != 0:
            _log.warning("diff apply failed for %s: %s", task_id, proc.stderr[:500])
            result = {
                "valid": False,
                "test_results": f"diff apply failed: {proc.stderr[:500]}",
                "failures": [f"Could not apply draft diff: {proc.stderr[:200]}"],
                "can_fast_track": False,
            }
            _record(task_id, result, t0)
            return result

        # --- run tests ---
        proc = subprocess.run(
            test_cmd,
            cwd=wt_dir,
            shell=True,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT,
        )
        test_output = (proc.stdout or "") + "\n" + (proc.stderr or "")

        if proc.returncode == 0:
            result = {
                "valid": True,
                "test_results": test_output[-2000:],
                "failures": [],
                "can_fast_track": True,
            }
        else:
            failures = _extract_failures(test_output)
            result = {
                "valid": False,
                "test_results": test_output[-2000:],
                "failures": failures,
                "can_fast_track": False,
            }

        _record(task_id, result, t0)
        return result

    except subprocess.TimeoutExpired:
        _log.warning("timeout validating draft for %s", task_id)
        result = {
            "valid": False,
            "test_results": f"test timed out after {_TIMEOUT}s",
            "failures": [f"Test command timed out after {_TIMEOUT}s"],
            "can_fast_track": False,
        }
        _record(task_id, result, t0)
        return result
    except Exception as exc:
        _log.error("merge_validator error for %s: %s", task_id, exc)
        return dict(_FAIL_SOFT)
    finally:
        _cleanup(repo_path, wt_dir, tmp_branch)


def constraint_prompt(failures):
    """Convert test failures into a prompt section for the agent."""
    if not failures:
        return ""
    lines = ["## Known Test Failures (from pre-validation)",
             "The following tests failed on a preliminary draft. "
             "Your implementation MUST pass these:", ""]
    for f in failures:
        lines.append(f"- {f}")
    return "\n".join(lines)


def fast_track_check(task_id):
    """Return True if a pre-validated draft exists and passed all tests."""
    with _lock:
        entry = _validated.get(str(task_id))
        if entry and entry.get("can_fast_track"):
            _stats["fast_tracks"] += 1
            return True
    return False


def stats():
    """Return a snapshot of validation statistics."""
    with _lock:
        return dict(_stats)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _run_git(repo, args):
    """Run a git command in *repo*. Raises on failure."""
    cmd = ["git"] + args
    proc = subprocess.run(cmd, cwd=repo, capture_output=True, text=True, timeout=30)
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {proc.stderr[:300]}")
    return proc.stdout


def _extract_failures(test_output):
    """Best-effort extraction of failure lines from test output."""
    failures = []
    for line in test_output.splitlines():
        low = line.lower()
        if any(kw in low for kw in ("fail", "error", "assert")):
            stripped = line.strip()
            if stripped and len(stripped) < 500:
                failures.append(stripped)
    # Deduplicate while preserving order, cap at 20
    seen = set()
    unique = []
    for f in failures:
        if f not in seen:
            seen.add(f)
            unique.append(f)
    return unique[:20]


def _record(task_id, result, t0):
    """Record result in validated cache and update stats."""
    elapsed = time.time() - t0
    with _lock:
        _validated[str(task_id)] = result
        _stats["validations_run"] += 1
        if result.get("valid"):
            _stats["drafts_passed"] += 1
            # Rough estimate: agent call we might skip costs ~90s
            _stats["time_saved_estimate_s"] += 90.0
        else:
            _stats["drafts_failed"] += 1
    _log.info("validated %s valid=%s in %.1fs", task_id, result.get("valid"), elapsed)


def _cleanup(repo_path, wt_dir, tmp_branch):
    """Remove worktree and temp branch. Best-effort, never raises."""
    try:
        if wt_dir and os.path.isdir(wt_dir):
            subprocess.run(["git", "worktree", "remove", "--force", wt_dir],
                           cwd=repo_path, capture_output=True, timeout=15)
            if os.path.isdir(wt_dir):
                shutil.rmtree(wt_dir, ignore_errors=True)
    except Exception:
        pass
    try:
        subprocess.run(["git", "branch", "-D", tmp_branch],
                       cwd=repo_path, capture_output=True, timeout=10)
    except Exception:
        pass
