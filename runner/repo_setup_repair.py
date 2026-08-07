#!/usr/bin/env python3
"""
repo_setup_repair.py - detect and repair missing repo setup for task execution.

When a runner claims a task but the repo checkout is missing critical setup
(git config, required CLI tools, broken worktree state), this module diagnoses
and minimally repairs the environment so the task can proceed.

Fail-soft: returns status dict on any error, never raises.
"""
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import repo_setup_check

CLONE_TIMEOUT = int(os.environ.get("ORCH_REPO_CLONE_TIMEOUT", "300"))
FETCH_TIMEOUT = int(os.environ.get("ORCH_REPO_FETCH_TIMEOUT", "120"))

# Repo-owner identity: Vercel blocks production deploys whose commit author is
# anyone else (see CLAUDE.md "Git identity"), so repairs must never install a
# bot identity. Env-overridable, ORCH_ prefix per fleet config convention.
GIT_IDENTITY_NAME = os.environ.get("ORCH_GIT_USER_NAME", "kalepasch1")
GIT_IDENTITY_EMAIL = os.environ.get("ORCH_GIT_USER_EMAIL", "kalepasch@gmail.com")


def _run(cmd, cwd=None, timeout=30):
    """Run a command, return (stdout, stderr, returncode)."""
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip(), r.stderr.strip(), r.returncode
    except FileNotFoundError:
        return "", f"command not found: {cmd[0]}", 127
    except Exception as e:
        return "", str(e), 1

def check_git(repo):
    """Verify git is available and the repo is valid."""
    out, err, rc = _run(["git", "status", "--porcelain"], cwd=repo)
    return rc == 0, err


def check_git_config(repo):
    """Verify essential git config is set (presence only)."""
    issues = []
    for key in ["user.name", "user.email"]:
        out, _, rc = _run(["git", "config", key], cwd=repo)
        if rc != 0 or not out:
            issues.append(key)
    return issues


def check_git_identity(repo):
    """Verify git config carries the OWNER identity, not merely *some* identity.

    Presence is not health. A checkout configured with a platform/bot account
    (e.g. mandyjustinepasch@gmail.com, kale@heretomorrow.us) passes
    check_git_config and then produces commits Vercel puts in BLOCKED state,
    which never deploy -- the failure the 2026-08-02 two-session audit addendum
    recorded. Compared case-insensitively; email is the field Vercel keys on.

    Returns a list of "<key>:<found-or-unset>" mismatch strings; empty == owner.
    Fail-soft: an unreadable repo yields [] rather than raising.
    """
    mismatches = []
    for key, expected in [("user.name", GIT_IDENTITY_NAME),
                          ("user.email", GIT_IDENTITY_EMAIL)]:
        out, _, rc = _run(["git", "config", key], cwd=repo)
        if rc != 0 or not out:
            continue  # absence is check_git_config's finding, not a mismatch
        if out.strip().lower() != str(expected).strip().lower():
            mismatches.append(f"{key}:{out.strip()}")
    return mismatches


def check_tool(name):
    """Check if a CLI tool is available on PATH."""
    return shutil.which(name) is not None


def check_worktree_health(repo):
    """Check for broken worktree state (stale locks, missing refs)."""
    issues = []
    git_dir = os.path.join(repo, ".git")
    lock = os.path.join(git_dir if os.path.isdir(git_dir) else repo, "index.lock")
    if os.path.exists(lock):
        issues.append("index.lock")
    wt_dir = os.path.join(git_dir, "worktrees") if os.path.isdir(git_dir) else None
    if wt_dir and os.path.isdir(wt_dir):
        for entry in os.listdir(wt_dir):
            gitdir_file = os.path.join(wt_dir, entry, "gitdir")
            if os.path.exists(gitdir_file):
                try:
                    with open(gitdir_file) as fh:
                        target = fh.read().strip()
                    if not os.path.exists(target):
                        issues.append(f"worktree:{entry}:orphaned")
                except Exception:
                    pass
    return issues


def repair_git_config(repo):
    """Install the repo-owner identity (deploy-safe author) into repo-LOCAL config.

    Repairs BOTH shapes: unset, and set-but-wrong. Only repairing "unset" left a
    checkout carrying a bot identity looking healthy forever, because the first
    (wrong) value it saw satisfied the presence check permanently.

    Writes local config only -- never --global -- so a repair is scoped to the
    checkout that is about to produce commits.
    """
    repaired = []
    for key, default in [("user.name", GIT_IDENTITY_NAME), ("user.email", GIT_IDENTITY_EMAIL)]:
        out, _, rc = _run(["git", "config", key], cwd=repo)
        current = out.strip() if rc == 0 else ""
        if not current:
            _run(["git", "config", key, default], cwd=repo)
            repaired.append(key)
        elif current.lower() != str(default).strip().lower():
            _run(["git", "config", key, default], cwd=repo)
            repaired.append(f"{key} (was {current})")
    return repaired


def repair_index_lock(repo):
    """Remove stale index.lock if no git process is running."""
    git_dir = os.path.join(repo, ".git")
    lock = os.path.join(git_dir if os.path.isdir(git_dir) else repo, "index.lock")
    if not os.path.exists(lock):
        return False
    _, ps_out, _ = _run(["pgrep", "-f", f"git.*{os.path.basename(repo)}"])
    if ps_out:
        return False
    try:
        os.remove(lock)
        return True
    except OSError:
        return False


def repair_orphaned_worktrees(repo):
    """Prune orphaned worktree entries."""
    _, err, rc = _run(["git", "worktree", "prune"], cwd=repo)
    return rc == 0


def diagnose(repo):
    """Run all checks on a repo and return a diagnostic report."""
    if not repo or not os.path.isdir(repo):
        return {"valid": False, "error": "repo path does not exist", "repairs": []}
    report = {"valid": True, "repo": repo, "issues": [], "repairs": []}
    git_ok, git_err = check_git(repo)
    if not git_ok:
        report["valid"] = False
        report["issues"].append(f"git status failed: {git_err}")
    config_issues = check_git_config(repo)
    if config_issues:
        report["issues"].append(f"missing git config: {', '.join(config_issues)}")
    identity_issues = check_git_identity(repo)
    if identity_issues:
        # Reported separately from "missing": a wrong author is a DEPLOY blocker,
        # not merely unconfigured setup.
        report["issues"].append(
            f"non-owner git identity (Vercel will BLOCK): {', '.join(identity_issues)}")
    report["identity_ok"] = not identity_issues
    for tool in ["git", "python3", "node"]:
        if not check_tool(tool):
            report["issues"].append(f"tool not found: {tool}")
    wt_issues = check_worktree_health(repo)
    if wt_issues:
        report["issues"].append(f"worktree issues: {', '.join(wt_issues)}")
    return report


def repair(repo):
    """Diagnose and auto-repair what we can. Returns report with repairs applied."""
    report = diagnose(repo)
    if not report.get("valid", True) and "repo path does not exist" in report.get("error", ""):
        return report
    config_fixed = repair_git_config(repo)
    if config_fixed:
        report["repairs"].append(f"set git config: {', '.join(config_fixed)}")
    if repair_index_lock(repo):
        report["repairs"].append("removed stale index.lock")
    if repair_orphaned_worktrees(repo):
        report["repairs"].append("pruned orphaned worktrees")
    post = diagnose(repo)
    report["post_repair_issues"] = post.get("issues", [])
    report["healthy"] = len(post.get("issues", [])) == 0
    return report


def repair_repo(path, remote_url=None, remote="origin"):
    """Bring a local repo to a ready state without switching branches.

    Clones when the path is absent (requires remote_url), fetches the remote,
    and fast-forwards the default branch (main, or develop if that is the
    default). A checked-out default branch is only fast-forwarded when the
    working tree is clean; a non-checked-out one is updated in place via
    ``git fetch <remote> <branch>:<branch>``, which never touches the tree.

    Fail-soft: returns a status dict with an ``error`` field, never raises.
    """
    result = {
        "cloned": False, "fetched": False, "fast_forwarded": False,
        "actions": [], "error": "",
    }
    try:
        is_repo = bool(path) and os.path.isdir(path) and \
            _run(["git", "rev-parse", "--is-inside-work-tree"], cwd=path)[2] == 0
        if not is_repo:
            if not remote_url:
                result["error"] = f"repo missing and no remote_url to clone: {path}"
                result.update(_final_state(path, remote))
                return result
            _, err, rc = _run(["git", "clone", remote_url, path], timeout=CLONE_TIMEOUT)
            if rc != 0:
                result["error"] = f"clone failed: {err}"
                result.update(_final_state(path, remote))
                return result
            result["cloned"] = True
            result["actions"].append(f"cloned {remote_url}")

        _, err, rc = _run(["git", "fetch", remote, "--prune"], cwd=path, timeout=FETCH_TIMEOUT)
        if rc == 0:
            result["fetched"] = True
        else:
            result["error"] = f"fetch failed: {err}"

        branch = repo_setup_check.detect_default_branch(path, remote)
        if branch and _run(["git", "rev-parse", "--verify", "--quiet",
                            f"refs/remotes/{remote}/{branch}"], cwd=path)[2] == 0:
            behind, _, rc = _run(
                ["git", "rev-list", "--count", f"{branch}..{remote}/{branch}"], cwd=path)
            if rc == 0 and behind.isdigit() and int(behind) > 0:
                current, _, _ = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=path)
                if current == branch:
                    dirty, _, _ = _run(["git", "status", "--porcelain"], cwd=path)
                    if dirty:
                        result["actions"].append(
                            f"skipped fast-forward of {branch}: dirty working tree")
                    else:
                        _, err, rc = _run(
                            ["git", "merge", "--ff-only", f"{remote}/{branch}"], cwd=path)
                        if rc == 0:
                            result["fast_forwarded"] = True
                            result["actions"].append(f"fast-forwarded {branch}")
                        elif not result["error"]:
                            result["error"] = f"fast-forward of {branch} failed: {err}"
                else:
                    _, err, rc = _run(
                        ["git", "fetch", remote, f"{branch}:{branch}"],
                        cwd=path, timeout=FETCH_TIMEOUT)
                    if rc == 0:
                        result["fast_forwarded"] = True
                        result["actions"].append(f"fast-forwarded {branch} (not checked out)")
                    elif not result["error"]:
                        result["error"] = f"fast-forward of {branch} failed: {err}"

        result.update(_final_state(path, remote))
    except Exception as e:
        result["error"] = result["error"] or str(e)
    return result


def _final_state(path, remote):
    state = repo_setup_check.check_repo_ready(path, remote=remote)
    return {"ready": state["ready"], "default_branch": state["default_branch"],
            "clean": state["clean"], "current": state["current"]}


def repair_for_task(task):
    """Repair repo setup for a specific task's project. Returns report."""
    try:
        pid = task.get("project_id")
        proj = db.select("projects", {"select": "repo_path", "id": f"eq.{pid}"})
        if not proj:
            return {"valid": False, "error": "project not found"}
        raw = proj[0].get("repo_path", "")
        repo = db.localize_repo_path(raw)
        return repair(repo)
    except Exception as e:
        return {"valid": False, "error": str(e), "repairs": []}


if __name__ == "__main__":
    import json
    repo_arg = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    mode = sys.argv[2] if len(sys.argv) > 2 else "diagnose"
    if mode == "repair":
        result = repair(repo_arg)
    else:
        result = diagnose(repo_arg)
    print(json.dumps(result, indent=2, default=str))