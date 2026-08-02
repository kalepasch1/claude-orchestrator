#!/usr/bin/env python3
"""
branch_recovery.py - detect and recover missing git branches.

Recovery strategies (tried in order):
  1. Fetch from origin/upstream remotes
  2. Restore from git reflog if the branch was recently active
  3. Mark as unrecoverable if the branch is >30 days stale

Pure git operations — no database writes, except recover_missing_branches()
which does best-effort task-state marking (MERGED/QUARANTINED) after a
recovery attempt; a DB failure there never aborts the loop.

Env vars:
    ORCH_BRANCH_RECOVERY_ENABLED              "true" (default) to enable
    ORCH_BRANCH_RECOVERY_STALE_DAYS           days before marking unrecoverable (default: 30)
    ORCH_BRANCH_RECOVERY_TIMEOUT              git command timeout in seconds (default: 60)
    ORCH_MISSING_BRANCH_RECOVERY_THRESHOLD    min library-hit similarity to apply (default: 0.8)
    ORCH_MISSING_BRANCH_LIBRARY_PATH          optional JSON file mapping slug -> diff
"""
import json
import os, re, subprocess, sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import log as _log_mod
_log = _log_mod.get("branch_recovery")

ENABLED = os.environ.get("ORCH_BRANCH_RECOVERY_ENABLED", "true").lower() in ("1", "true", "yes", "on")
STALE_DAYS = int(os.environ.get("ORCH_BRANCH_RECOVERY_STALE_DAYS", "30"))
TIMEOUT = int(os.environ.get("ORCH_BRANCH_RECOVERY_TIMEOUT", "60"))

# ── module-level counters ──────────────────────────────────────────
_stats = {
    "recover_attempts": 0,
    "recover_fetched": 0,
    "recover_reflog": 0,
    "recover_unrecoverable": 0,
    "recover_errors": 0,
    "detect_calls": 0,
    "detect_missing_found": 0,
    "batch_reviewed": 0,
    "batch_merged": 0,
    "batch_quarantined": 0,
    "batch_skipped": 0,
}


def stats():
    """Return a snapshot of module counters."""
    return dict(_stats)


# ── git helpers ────────────────────────────────────────────────────
def _git(repo, *args):
    """Run a git command; return (returncode, stdout, stderr)."""
    try:
        r = subprocess.run(
            ["git"] + list(args),
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
        )
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"
    except Exception as e:
        return -1, "", str(e)


def _is_git_repo(path):
    """Check whether *path* is inside a valid git working tree."""
    if not path or not os.path.isdir(path):
        return False
    rc, _, _ = _git(path, "rev-parse", "--is-inside-work-tree")
    return rc == 0


def _branch_exists_local(repo, branch):
    rc, _, _ = _git(repo, "rev-parse", "--verify", f"refs/heads/{branch}")
    return rc == 0


def _branch_on_remote(repo, branch, remote="origin"):
    """Return True when the branch exists on *remote*."""
    rc, out, _ = _git(repo, "ls-remote", "--heads", remote, branch)
    return rc == 0 and bool(out.strip())


def _fetch_branch(repo, branch, remote="origin"):
    """Attempt to fetch *branch* from *remote* and create a local ref."""
    rc, _, err = _git(repo, "fetch", remote,
                      f"refs/heads/{branch}:refs/heads/{branch}")
    return rc == 0, err


def _reflog_recover(repo, branch):
    """Try to find *branch* in the reflog and recreate it.

    Searches reflog for checkout/branch-create entries referencing this branch.
    Only succeeds if the reflog entry is within STALE_DAYS.
    """
    rc, out, _ = _git(repo, "reflog", "--format=%H %gd %gs", "--all")
    if rc != 0 or not out:
        return False, "no reflog data"

    pattern = re.compile(
        r"^([0-9a-f]{7,40})\s+\S+\s+.*(?:checkout|branch).*\b"
        + re.escape(branch) + r"\b",
        re.IGNORECASE,
    )
    candidate_sha = None
    for line in out.splitlines():
        m = pattern.match(line)
        if m:
            candidate_sha = m.group(1)
            break

    if not candidate_sha:
        return False, "branch not found in reflog"

    # Check staleness of the commit
    rc2, date_str, _ = _git(repo, "show", "-s", "--format=%ci", candidate_sha)
    if rc2 == 0 and date_str:
        try:
            commit_dt = datetime.strptime(date_str[:19], "%Y-%m-%d %H:%M:%S")
            if datetime.utcnow() - commit_dt > timedelta(days=STALE_DAYS):
                return False, f"reflog entry too old ({date_str[:10]})"
        except ValueError:
            pass  # can't parse — proceed anyway

    rc3, _, err = _git(repo, "branch", branch, candidate_sha)
    if rc3 == 0:
        return True, f"restored from reflog ({candidate_sha[:8]})"
    return False, f"branch create failed: {err}"


# ── public API ─────────────────────────────────────────────────────
def recover_branch(project_path, branch_name):
    """Attempt to recover a missing branch.

    Returns dict with keys:
        status:       'recovered' | 'unrecoverable'
        action_taken: str describing what happened
    """
    if not ENABLED:
        return {"status": "unrecoverable", "action_taken": "feature disabled"}

    _stats["recover_attempts"] += 1

    if not _is_git_repo(project_path):
        _stats["recover_errors"] += 1
        return {"status": "unrecoverable",
                "action_taken": f"invalid git path: {project_path}"}

    # Already exists locally — nothing to do
    if _branch_exists_local(project_path, branch_name):
        return {"status": "recovered",
                "action_taken": "branch already exists locally"}

    # Strategy 1: fetch from origin
    if _branch_on_remote(project_path, branch_name, "origin"):
        ok, detail = _fetch_branch(project_path, branch_name, "origin")
        if ok:
            _stats["recover_fetched"] += 1
            _log.info("recovered %s via origin fetch", branch_name)
            return {"status": "recovered",
                    "action_taken": "fetched from origin"}
        _log.warning("origin fetch failed for %s: %s", branch_name, detail)

    # Strategy 1b: try upstream remote
    if _branch_on_remote(project_path, branch_name, "upstream"):
        ok, detail = _fetch_branch(project_path, branch_name, "upstream")
        if ok:
            _stats["recover_fetched"] += 1
            _log.info("recovered %s via upstream fetch", branch_name)
            return {"status": "recovered",
                    "action_taken": "fetched from upstream"}
        _log.warning("upstream fetch failed for %s: %s", branch_name, detail)

    # Strategy 2: reflog recovery
    ok, detail = _reflog_recover(project_path, branch_name)
    if ok:
        _stats["recover_reflog"] += 1
        _log.info("recovered %s via reflog: %s", branch_name, detail)
        return {"status": "recovered",
                "action_taken": f"reflog recovery: {detail}"}

    # Strategy 3: unrecoverable
    _stats["recover_unrecoverable"] += 1
    _log.info("branch %s is unrecoverable: %s", branch_name, detail)
    return {"status": "unrecoverable",
            "action_taken": f"all strategies exhausted: {detail}"}


def detect_missing_branches(project_path, expected_branches):
    """Return a list of branch names from *expected_branches* that are missing locally.

    Args:
        project_path:      path to git repo
        expected_branches: iterable of branch name strings

    Returns:
        list of missing branch names (empty list if all present or on error)
    """
    _stats["detect_calls"] += 1

    if not ENABLED:
        return []

    if not _is_git_repo(project_path):
        _stats["recover_errors"] += 1
        return []

    missing = []
    for branch in expected_branches:
        if not _branch_exists_local(project_path, branch):
            missing.append(branch)
    _stats["detect_missing_found"] += len(missing)
    return missing


# ── batch recovery of missing merge-train branches ─────────────────
def _recovery_threshold(threshold):
    """Resolve the library-similarity threshold (arg > ORCH_ env > 0.8)."""
    if threshold is not None:
        try:
            return float(threshold)
        except (TypeError, ValueError):
            pass
    try:
        return float(os.environ.get("ORCH_MISSING_BRANCH_RECOVERY_THRESHOLD", "0.8"))
    except ValueError:
        return 0.8


def _load_library_from_path():
    """Load slug->diff mapping from ORCH_MISSING_BRANCH_LIBRARY_PATH, or None."""
    path = os.environ.get("ORCH_MISSING_BRANCH_LIBRARY_PATH", "").strip()
    if not path:
        return None
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except Exception as exc:
        _log.debug("library path %s unreadable: %s", path, exc)
        return None


def _library_patch(library, slug, threshold):
    """Best library diff for *slug*, or "" when none clears *threshold*.

    Accepts a callable slug -> entry or a mapping slug -> entry, where entry
    is a diff string or a dict {"diff"|"patch_diff": str, "similarity": float}.
    """
    if library is None:
        return ""
    try:
        entry = library(slug) if callable(library) else library.get(slug)
    except Exception as exc:
        _log.debug("library lookup failed for %s: %s", slug, exc)
        return ""
    if not entry:
        return ""
    if isinstance(entry, str):
        return entry
    if isinstance(entry, dict):
        try:
            sim = float(entry.get("similarity", 1.0))
        except (TypeError, ValueError):
            sim = 0.0
        if sim >= threshold:
            return entry.get("diff") or entry.get("patch_diff") or ""
    return ""


def _run_focused_tests(repo, test_cmd):
    """Run the entry's focused test command in *repo*. Returns (ok, output)."""
    if not test_cmd:
        return True, ""
    cmd = test_cmd if isinstance(test_cmd, (list, tuple)) else str(test_cmd).split()
    try:
        r = subprocess.run(list(cmd), cwd=repo, capture_output=True,
                           text=True, timeout=max(TIMEOUT, 300))
        return r.returncode == 0, (r.stdout + "\n" + r.stderr)[-2000:]
    except Exception as exc:
        return False, str(exc)[:500]


def _mark_task_state(slug, state):
    """Best-effort task-state marking; DB/RPC failure never propagates."""
    try:
        import db
        db.update("tasks", {"slug": f"eq.{slug}"}, {"state": state})
        return True
    except Exception as exc:
        _log.debug("state mark %s=%s failed: %s", slug, state, exc)
        return False


def recover_missing_branches(missing, library=None, threshold=None, project=None):
    """Batch-recover missing merge-train branches from the merged-diff library.

    Args:
        missing:   iterable of entries, each a dict:
                     {"slug": str, "repo": str, "base": str (default "master"),
                      "project": str (optional), "test_cmd": list|str (optional)}
                   Entries without slug or repo are counted as skipped.
        library:   callable slug -> entry, or mapping slug -> entry (see
                   _library_patch); defaults to ORCH_MISSING_BRANCH_LIBRARY_PATH.
        threshold: min library-hit similarity to apply
                   (default ORCH_MISSING_BRANCH_RECOVERY_THRESHOLD, 0.8).
        project:   when set, entries carrying a different "project" are skipped
                   so recovery never touches another project's branches.

    Per entry: skip if the branch already exists locally; else apply the
    library patch (or fall back to patch_recovery.recover) into a fresh
    worktree, run the focused tests, and mark MERGED on pass or QUARANTINED
    on any failure. Fail-soft: git/DB/RPC errors are logged, counted as
    QUARANTINED, and never abort the loop.

    Returns:
        {"reviewed": int, "merged": int, "quarantined": int, "skipped": int,
         "details": [{"slug", "status", "reason"}, ...]}
    """
    out = {"reviewed": 0, "merged": 0, "quarantined": 0, "skipped": 0, "details": []}
    if not ENABLED or not missing:
        return out

    threshold = _recovery_threshold(threshold)
    if library is None:
        library = _load_library_from_path()

    def _done(slug, status, reason=""):
        key = {"MERGED": "merged", "QUARANTINED": "quarantined"}.get(status, "skipped")
        out[key] += 1
        _stats["batch_" + key] += 1
        out["details"].append({"slug": slug, "status": status, "reason": reason[:500]})
        if status in ("MERGED", "QUARANTINED"):
            _mark_task_state(slug, status)

    for entry in missing:
        out["reviewed"] += 1
        _stats["batch_reviewed"] += 1
        try:
            if not isinstance(entry, dict):
                _done(str(entry), "SKIPPED", "malformed entry")
                continue
            slug = (entry.get("slug") or "").strip()
            repo = (entry.get("repo") or "").strip()
            if not slug or not repo:
                _done(slug or "?", "SKIPPED", "missing slug or repo")
                continue
            if project and entry.get("project") and entry["project"] != project:
                _done(slug, "SKIPPED",
                      f"project isolation: {entry['project']} != {project}")
                continue
            if not _is_git_repo(repo):
                _done(slug, "QUARANTINED", f"invalid git path: {repo}")
                continue

            branch = entry.get("branch") or f"agent/{slug}"
            base = entry.get("base") or "master"
            if _branch_exists_local(repo, branch):
                _done(slug, "SKIPPED", "branch already exists locally")
                continue

            import patch_recovery
            diff = _library_patch(library, slug, threshold)
            if diff:
                result = patch_recovery._apply_diff_to_branch(
                    repo, slug, branch, base, diff, "library")
            else:
                result = patch_recovery.recover(repo, slug, base,
                                                project=entry.get("project") or project)
            if not result.get("ok"):
                _done(slug, "QUARANTINED",
                      result.get("reason") or "recovery failed")
                continue

            ok, test_out = _run_focused_tests(repo, entry.get("test_cmd"))
            if ok:
                _done(slug, "MERGED", f"recovered via {result.get('method', 'library')}")
            else:
                _done(slug, "QUARANTINED", f"focused tests failed: {test_out}")
        except Exception as exc:
            _stats["recover_errors"] += 1
            _log.warning("batch recovery error: %s", exc)
            slug = entry.get("slug", "?") if isinstance(entry, dict) else str(entry)
            _done(slug, "QUARANTINED", str(exc)[:200])
    return out
