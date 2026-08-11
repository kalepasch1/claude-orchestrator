"""
patch_template_apply.py — apply a patch template (an arbitrary similar diff) to
a fresh branch off base.

Completes the template-adaptation recovery path (patch_recovery method 3):
after the merged-diff search finds a similar template, this module applies THAT
diff to a fresh branch — instead of re-looking-up the missing task's own stored
patch, which is always absent by the time method 3 runs (gap #1 in
runner/docs/patch_template_branch_analysis.md).

Fail-soft: every entry point returns a recover-style dict
({ok, method, branch, reason?}) and never raises, so the runner cannot wedge on
bad input, a missing repo path, or a malformed diff.
"""
import os
import re
import subprocess
import threading

DEFAULT_METHOD = "template"
BRANCH_PREFIX = "agent/"
WORKTREE_DIR_SUFFIX = "-wt"
WORKTREE_NAME_PREFIX = "template-apply-"
MIN_PATCH_CHARS = int(os.environ.get("ORCH_PATCH_TEMPLATE_MIN_CHARS", "10"))
GIT_TIMEOUT_SECONDS = int(os.environ.get("ORCH_PATCH_TEMPLATE_GIT_TIMEOUT", "120"))
REASON_MAX_CHARS = 200

_DIFF_MARKERS = ("diff --git ", "--- ", "+++ ", "@@ ")

_stats_lock = threading.Lock()
_stats = {"attempted": 0, "applied": 0, "failed": 0}


def looks_like_diff(patch):
    """Cheap structural check that a string is plausibly a unified diff."""
    if not patch or not isinstance(patch, str):
        return False
    if len(patch.strip()) < MIN_PATCH_CHARS:
        return False
    return any(marker in patch for marker in _DIFF_MARKERS)


def stats():
    """Snapshot of apply counters, for operators and tests."""
    with _stats_lock:
        return dict(_stats)


def reset_stats():
    with _stats_lock:
        for key in _stats:
            _stats[key] = 0


def apply_patch_template(repo, slug, base, patch, branch=None, method=DEFAULT_METHOD):
    """Apply an arbitrary diff to a fresh branch off base. Returns dict with:
    - ok: bool — whether the template applied and committed
    - method: str — label carried into the recover-style result
    - branch: str — target branch name (agent/<slug> unless overridden)
    - reason: str — failure detail (absent on success)
    """
    slug = slug if isinstance(slug, str) else ""
    branch = branch if isinstance(branch, str) else ""
    branch_name = branch or (BRANCH_PREFIX + slug if slug else "")
    with _stats_lock:
        _stats["attempted"] += 1

    def _fail(reason):
        with _stats_lock:
            _stats["failed"] += 1
        return {"ok": False, "method": method, "branch": branch_name,
                "reason": str(reason)[:REASON_MAX_CHARS]}

    try:
        if not branch_name:
            return _fail("no slug or branch given")
        if not base or not isinstance(base, str):
            return _fail("no base branch given")
        if not repo or not isinstance(repo, str) or not os.path.isdir(repo):
            return _fail(f"repo path unavailable: {repo!r}")
        if not looks_like_diff(patch):
            return _fail("patch is empty or not a unified diff")

        repo = os.path.normpath(repo)
        wt_name = WORKTREE_NAME_PREFIX + re.sub(r"[^\w.-]", "-", slug or branch_name)
        wt = os.path.join(os.path.dirname(repo),
                          os.path.basename(repo) + WORKTREE_DIR_SUFFIX, wt_name)
        try:
            wt_parent = os.path.dirname(wt)
            if wt_parent:
                os.makedirs(wt_parent, exist_ok=True)
            _free_branch(repo, branch_name)
            _git(repo, "branch", "-D", branch_name)
            created = _git(repo, "branch", branch_name, base)
            if created.returncode != 0:
                return _fail(f"branch create failed: {created.stderr[:150]}")

            r = _git(repo, "worktree", "add", "-f", wt, branch_name)
            if r.returncode != 0:
                return _fail(f"worktree setup failed: {r.stderr[:150]}")

            proc = subprocess.run(["git", "apply", "--3way", "-"], cwd=wt,
                                  input=patch, capture_output=True, text=True,
                                  timeout=GIT_TIMEOUT_SECONDS)
            if proc.returncode != 0:
                proc = subprocess.run(["git", "apply", "--3way", "--reject", "-"],
                                      cwd=wt, input=patch, capture_output=True,
                                      text=True, timeout=GIT_TIMEOUT_SECONDS)
                if proc.returncode != 0:
                    return _fail(f"template apply failed: {proc.stderr[:150]}")

            env = _git_commit_env()
            subprocess.run(["git", "add", "-A"], cwd=wt, env=env,
                           capture_output=True, timeout=GIT_TIMEOUT_SECONDS)
            committed = subprocess.run(
                ["git", "commit", "--no-verify", "-m",
                 f"patch-template-apply: {slug or branch_name}"],
                cwd=wt, env=env, capture_output=True, text=True,
                timeout=GIT_TIMEOUT_SECONDS)
            if committed.returncode != 0:
                return _fail(f"commit failed: {committed.stderr[:150]}")

            ahead = subprocess.run(["git", "rev-list", "--count", f"{base}..HEAD"],
                                   cwd=wt, capture_output=True, text=True,
                                   timeout=GIT_TIMEOUT_SECONDS)
            if int((ahead.stdout or "0").strip() or "0") > 0:
                with _stats_lock:
                    _stats["applied"] += 1
                return {"ok": True, "method": method, "branch": branch_name}
            return _fail("template produced no commits")
        finally:
            subprocess.run(["git", "worktree", "remove", "--force", wt],
                           cwd=repo, capture_output=True,
                           timeout=GIT_TIMEOUT_SECONDS)
    except Exception as exc:
        return _fail(exc)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _git_commit_env():
    """Minimal env for git commit operations (identity only, no secrets)."""
    _name = os.environ.get("FLEET_GIT_AUTHOR_NAME", "kalepasch1")
    _email = os.environ.get("FLEET_GIT_AUTHOR_EMAIL", "kalepasch@gmail.com")
    return {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", ""),
        "GIT_AUTHOR_NAME": _name,
        "GIT_AUTHOR_EMAIL": _email,
        "GIT_COMMITTER_NAME": _name,
        "GIT_COMMITTER_EMAIL": _email,
    }


def _git(repo, *args, timeout=GIT_TIMEOUT_SECONDS):
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", ""),
    }
    return subprocess.run(["git", *args], cwd=repo, env=env,
                          capture_output=True, text=True, timeout=timeout)


def _free_branch(repo, branch):
    """Remove any worktree that has this branch checked out."""
    try:
        import approval_merge
        approval_merge._free_branch(repo, branch)
    except Exception:
        pass
