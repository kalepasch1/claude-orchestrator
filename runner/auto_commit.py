#!/usr/bin/env python3
"""
auto_commit.py - automated commit helper for branch management.

Provides utilities to detect uncommitted changes in task worktrees,
stage them, and create well-formatted commits automatically. Integrates
with branch_inspector to ensure branches are in a clean state before
merge cycles begin.

Fail-soft: returns status dict on any error, never raises.
Env: ORCH_AUTO_COMMIT_ENABLED (default "true").
"""
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import log as _log_mod

_log = _log_mod.get("auto_commit")
_ENABLED = os.environ.get("ORCH_AUTO_COMMIT_ENABLED", "true").lower() in ("true", "1", "yes")


def _git(repo, *args, timeout=30):
    """Run a git command, return (stdout, stderr, returncode)."""
    try:
        r = subprocess.run(["git"] + list(args), cwd=repo,
                           capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip(), r.stderr.strip(), r.returncode
    except FileNotFoundError:
        return "", "git not found", 127
    except Exception as e:
        return "", str(e), 1


def has_uncommitted_changes(repo):
    """Check if there are uncommitted changes (staged or unstaged)."""
    if not repo or not os.path.isdir(repo):
        return False
    out, _, rc = _git(repo, "status", "--porcelain")
    return rc == 0 and len(out.strip()) > 0


def get_changed_files(repo):
    """List files with uncommitted changes."""
    if not repo or not os.path.isdir(repo):
        return []
    out, _, rc = _git(repo, "status", "--porcelain")
    if rc != 0:
        return []
    files = []
    for line in out.strip().split("\n"):
        line = line.strip()
        if line:
            # Status is first 2 chars, then space, then filename
            fname = line[3:].strip() if len(line) > 3 else line
            files.append(fname)
    return files


def generate_commit_message(changed_files, slug="", prefix="auto"):
    """Generate a descriptive commit message from changed files."""
    if not changed_files:
        return f"{prefix}: no changes detected"

    # Categorize by file type
    py_files = [f for f in changed_files if f.endswith(".py")]
    test_files = [f for f in py_files if "test" in f.lower()]
    config_files = [f for f in changed_files if f.endswith((".yml", ".yaml", ".json", ".toml", ".cfg"))]

    parts = []
    if test_files:
        parts.append(f"add {len(test_files)} test file(s)")
    if len(py_files) - len(test_files) > 0:
        parts.append(f"update {len(py_files) - len(test_files)} module(s)")
    if config_files:
        parts.append(f"update {len(config_files)} config file(s)")

    remaining = len(changed_files) - len(py_files) - len(config_files)
    if remaining > 0:
        parts.append(f"{remaining} other file(s)")

    summary = ", ".join(parts) if parts else f"{len(changed_files)} file(s)"
    slug_part = f" [{slug}]" if slug else ""
    return f"{prefix}{slug_part}: {summary}"


def stage_and_commit(repo, slug="", message=None, dry_run=False):
    """Stage all changes and commit with an auto-generated message.

    Args:
        repo: Path to the git repository.
        slug: Task slug for the commit message.
        message: Custom commit message (auto-generated if None).
        dry_run: If True, report what would be committed without committing.

    Returns:
        dict with status, commit_hash, files_committed, message.
    """
    if not _ENABLED:
        return {"status": "disabled", "committed": False}

    if not repo or not os.path.isdir(repo):
        return {"status": "error", "committed": False, "error": "invalid repo path"}

    try:
        if not has_uncommitted_changes(repo):
            return {"status": "clean", "committed": False, "message": "no changes to commit"}

        changed = get_changed_files(repo)
        if not message:
            message = generate_commit_message(changed, slug)

        if dry_run:
            return {
                "status": "dry_run",
                "committed": False,
                "files": changed,
                "message": message,
            }

        # Stage all changes
        _, err, rc = _git(repo, "add", "-A")
        if rc != 0:
            return {"status": "error", "committed": False, "error": f"git add failed: {err}"}

        # Commit
        _, err, rc = _git(repo, "commit", "-m", message, "--no-verify")
        if rc != 0:
            return {"status": "error", "committed": False, "error": f"git commit failed: {err}"}

        # Get commit hash
        out, _, _ = _git(repo, "rev-parse", "HEAD")

        _log.info("auto-committed %d files: %s", len(changed), message)
        return {
            "status": "committed",
            "committed": True,
            "commit_hash": out,
            "files_committed": len(changed),
            "files": changed,
            "message": message,
        }
    except Exception as exc:
        _log.debug("stage_and_commit error: %s", exc)
        return {"status": "error", "committed": False, "error": str(exc)}


def auto_commit_worktrees(repo, slug_filter=None):
    """Find worktrees with uncommitted changes and commit them.

    Returns list of commit results.
    """
    if not _ENABLED or not repo or not os.path.isdir(repo):
        return []

    results = []
    try:
        out, _, rc = _git(repo, "worktree", "list", "--porcelain")
        if rc != 0:
            return []

        worktrees = []
        current_wt = {}
        for line in out.split("\n"):
            line = line.strip()
            if line.startswith("worktree "):
                if current_wt:
                    worktrees.append(current_wt)
                current_wt = {"path": line[9:]}
            elif line.startswith("branch "):
                current_wt["branch"] = line[7:]
            elif line == "":
                if current_wt:
                    worktrees.append(current_wt)
                current_wt = {}
        if current_wt:
            worktrees.append(current_wt)

        for wt in worktrees:
            path = wt.get("path", "")
            branch = wt.get("branch", "")
            # Extract slug from branch name (agent/slug-name)
            slug = branch.replace("refs/heads/agent/", "") if "agent/" in branch else ""

            if slug_filter and slug_filter not in slug:
                continue

            if has_uncommitted_changes(path):
                result = stage_and_commit(path, slug=slug)
                result["worktree"] = path
                result["branch"] = branch
                results.append(result)

    except Exception as exc:
        _log.debug("auto_commit_worktrees error: %s", exc)

    return results


if __name__ == "__main__":
    import json
    repo_arg = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    mode = sys.argv[2] if len(sys.argv) > 2 else "check"
    if mode == "commit":
        result = stage_and_commit(repo_arg)
    elif mode == "worktrees":
        result = auto_commit_worktrees(repo_arg)
    else:
        result = {
            "has_changes": has_uncommitted_changes(repo_arg),
            "changed_files": get_changed_files(repo_arg),
        }
    print(json.dumps(result, indent=2, default=str))
