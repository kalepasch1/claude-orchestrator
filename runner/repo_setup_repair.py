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
    """Verify essential git config is set."""
    issues = []
    for key in ["user.name", "user.email"]:
        out, _, rc = _run(["git", "config", key], cwd=repo)
        if rc != 0 or not out:
            issues.append(key)
    return issues


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
    """Set missing git config with safe defaults."""
    repaired = []
    for key, default in [("user.name", "orchestrator-bot"), ("user.email", "bot@orchestrator.local")]:
        out, _, rc = _run(["git", "config", key], cwd=repo)
        if rc != 0 or not out:
            _run(["git", "config", key, default], cwd=repo)
            repaired.append(key)
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