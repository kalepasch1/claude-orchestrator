#!/usr/bin/env python3
"""branch_creator.py — create missing agent branches on approval.

Creates agent/<slug> branches from a base branch when the merge train or
task executor discovers a branch is missing. Uses environment-variable
credentials (never hardcoded). All git operations use subprocess with
timeouts to prevent hangs.

Env vars:
    GITHUB_PAT              Personal access token (optional — see below)
    ORCH_GIT_TIMEOUT        Git command timeout in seconds (default 60)

Push credentials:
    A PAT in the environment is NOT the only way this host can push. After the
    2026-08-02 plaintext-credential purge, fleet machines authenticate through
    git's own credential helper (osxkeychain on the Macs) or an SSH remote, and
    GITHUB_PAT is simply unset. The old hard gate on GITHUB_PAT turned that into
    "repo not found / PAT lacks access" and blocked every missing-branch
    auto-recovery on those hosts even though `git push` would have worked.

    `push_credentials()` therefore probes, in order:
        1. GITHUB_PAT / GITHUB_TOKEN in the environment
        2. gh_auth.gh_token() (GitHub App → PAT → `gh auth token`)
        3. an SSH remote (git@…), which authenticates with the agent's keys
        4. a configured git credential helper (e.g. osxkeychain)
    and only reports "no credentials" when all four are absent.

Security:
    - No secrets in code — tokens come from the environment or gh_auth only
    - The token value is never logged or included in a returned reason
    - Only the *name* of the credential source is ever surfaced
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import log as _log_mod
import branch_lifecycle as bl

_log = _log_mod.get("branch_creator")
GIT_TIMEOUT = int(os.environ.get("ORCH_GIT_TIMEOUT", "60"))


def _git(args, repo):
    """Run a git command. Returns (stdout, success_bool)."""
    try:
        r = subprocess.run(
            ["git"] + args, cwd=repo,
            capture_output=True, text=True, timeout=GIT_TIMEOUT,
        )
        return r.stdout.strip(), r.returncode == 0
    except subprocess.TimeoutExpired:
        _log.warning("git timeout: %s", " ".join(args[:3]))
        return "", False
    except Exception as exc:
        _log.warning("git error: %s", exc)
        return "", False


def push_credentials(repo_path):
    """Return the name of the credential source this host can push with.

    Returns a short source identifier ("env", "gh_auth", "ssh-remote",
    "credential-helper") or "" when no push credential can be found. Never
    returns, logs, or raises with the credential value itself.

    Fail-soft: any probe that errors is treated as "this source unavailable"
    rather than propagating — a broken `gh` binary must not wedge recovery.
    """
    # 1. Explicit token in the environment.
    if os.environ.get("GITHUB_PAT") or os.environ.get("GITHUB_TOKEN"):
        return "env"

    # 2. gh_auth's own chain (GitHub App install token → PAT → gh CLI).
    try:
        import gh_auth
        if gh_auth.gh_token():
            return "gh_auth"
    except Exception as exc:  # noqa: BLE001 - fail-soft, diagnostic logged
        _log.debug("gh_auth probe unavailable: %s", exc)

    if not repo_path or not os.path.isdir(repo_path):
        return ""

    # 3. SSH remote — authenticates with the agent's keys, no token needed.
    url, ok = _git(["remote", "get-url", "origin"], repo_path)
    if ok and url and (url.startswith("git@") or url.startswith("ssh://")):
        return "ssh-remote"

    # 4. A configured credential helper (osxkeychain on the fleet Macs).
    helper, ok = _git(["config", "--get-all", "credential.helper"], repo_path)
    if ok and helper.strip():
        return "credential-helper"

    return ""


def create_branch(project_id, branch_name, base_branch="main", repo_path=None):
    """Create an agent branch from *base_branch* and push to origin.

    Args:
        project_id:  project identifier (used for logging, not git ops)
        branch_name: full branch name, e.g. "agent/my-task-slug"
        base_branch: branch to fork from (default "main")
        repo_path:   absolute path to local repo clone

    Returns:
        dict with keys: success (bool), reason (str)
    """
    # ── Validate inputs ──
    if not repo_path or not os.path.isdir(repo_path):
        return {"success": False, "reason": f"repo path not found: {repo_path}"}

    ok, err = bl.validate_branch_name(branch_name)
    if not ok:
        return {"success": False, "reason": f"invalid branch name: {err}"}

    # ── Check push credentials (never log the value, only the source) ──
    cred_source = push_credentials(repo_path)
    if not cred_source:
        return {"success": False,
                "reason": "no push credentials — GITHUB_PAT unset, gh auth "
                          "unavailable, origin is not SSH and no git "
                          "credential.helper is configured for this repo."}
    _log.debug("push credential source for %s: %s", project_id, cred_source)

    # ── Fetch latest ──
    _, fetched = _git(["fetch", "origin", "--quiet"], repo_path)
    if not fetched:
        _log.warning("fetch failed for %s (continuing with local state)", project_id)

    # ── Check if branch already exists ──
    existing = bl.branch_exists(repo_path, branch_name)
    if existing:
        return {"success": True, "reason": "branch already exists"}

    # ── Create branch from base ──
    _, created = _git(
        ["branch", branch_name, f"origin/{base_branch}"],
        repo_path,
    )
    if not created:
        # Fallback: try local base branch
        _, created = _git(["branch", branch_name, base_branch], repo_path)
    if not created:
        return {"success": False,
                "reason": f"failed to create branch from {base_branch}"}

    # ── Push to origin ──
    _, pushed = _git(
        ["push", "origin", f"{branch_name}:{branch_name}"],
        repo_path,
    )
    if not pushed:
        return {"success": False,
                "reason": "branch created locally but push failed "
                          f"(credential source: {cred_source} — check its "
                          "push scope for this repo)"}

    _log.info("created branch %s from %s in %s", branch_name, base_branch, project_id)
    return {"success": True, "reason": "created and pushed"}
