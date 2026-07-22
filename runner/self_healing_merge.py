#!/usr/bin/env python3
"""
self_healing_merge.py — auto-decompose conflicting branches into non-conflicting sub-branches.

When a branch has been stuck in CONFLICT state after both auto_conflict_resolver
and ast_merger fail, this module decomposes the branch's changes into smaller,
file-level sub-branches that can each merge cleanly.

Strategy:
    1. Identify all files modified by the conflicting branch
    2. Group files into "conflict clusters" (files that conflict with base)
       and "clean files" (files that merge cleanly)
    3. Create sub-branches, each containing only one cluster of changes
    4. Merge the clean sub-branches immediately
    5. Re-queue conflict clusters as new tasks with narrower scope

This converts a single unmergeable N-file branch into M clean merges +
K focused repair tasks, recovering all non-conflicting work.

Integration:
    merge_train.py or continuous_merger.py calls self_healing_merge.heal(repo, branch, base)
    after auto_conflict_resolver returns manual_files.

Environment:
    ORCH_SELF_HEALING_ENABLED     Kill switch (default: true)
    ORCH_SELF_HEALING_MIN_FILES   Min modified files to trigger decomposition (default: 2)
"""
import os
import sys
import subprocess
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import db
except Exception:
    db = None

try:
    import log as _log_mod
    _log = _log_mod.get("self_healing_merge")
except Exception:
    import logging
    _log = logging.getLogger("self_healing_merge")

ENABLED = os.environ.get("ORCH_SELF_HEALING_ENABLED", "true").lower() in (
    "true", "1", "yes", "on"
)
MIN_FILES = int(os.environ.get("ORCH_SELF_HEALING_MIN_FILES", "2"))
GIT_TIMEOUT = int(os.environ.get("ORCH_GIT_TIMEOUT", "90"))


def _git(args, repo, timeout=GIT_TIMEOUT):
    try:
        return subprocess.run(
            args, cwd=repo, capture_output=True, text=True,
            timeout=timeout, errors="replace"
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(args, 124, "", "timeout")
    except Exception as e:
        return subprocess.CompletedProcess(args, 1, "", str(e))


def _modified_files(repo: str, base: str, branch: str) -> list[str]:
    """List files modified by a branch relative to base."""
    r = _git(["git", "diff", "--name-only", base, branch], repo)
    if r.returncode != 0:
        return []
    return [f.strip() for f in r.stdout.splitlines() if f.strip()]


def _file_conflicts(repo: str, base: str, branch: str, filepath: str) -> bool:
    """Check if a single file would conflict when merging branch into base."""
    # Create a temporary merge to test this specific file
    # Use git merge-tree (plumbing) to check without touching the worktree
    r = _git(["git", "merge-tree", base, base, branch, "--", filepath], repo)
    if r.returncode != 0:
        # merge-tree might not support -- syntax; fall back to checking if
        # a full merge shows this file as conflicting
        return True  # assume conflict for safety

    # merge-tree outputs conflict markers if there are conflicts
    return "<<<<<<" in r.stdout or "changed in both" in r.stdout.lower()


def _classify_files(repo: str, base: str, branch: str, files: list[str]) -> tuple[list[str], list[str]]:
    """Split files into clean (mergeable) and conflicting sets.

    Uses git merge-base and per-file diff comparison rather than full merge
    to avoid touching the worktree.
    """
    # Find merge base
    mb = _git(["git", "merge-base", base, branch], repo)
    merge_base = mb.stdout.strip() if mb.returncode == 0 else base

    clean = []
    conflicting = []

    for filepath in files:
        # Get the file content at merge_base, base HEAD, and branch HEAD
        base_content = _git(["git", "show", f"{base}:{filepath}"], repo)
        branch_content = _git(["git", "show", f"{branch}:{filepath}"], repo)
        ancestor_content = _git(["git", "show", f"{merge_base}:{filepath}"], repo)

        # If file only exists in branch (new file), it's clean
        if base_content.returncode != 0 and branch_content.returncode == 0:
            clean.append(filepath)
            continue

        # If file wasn't changed on base since merge-base, it's clean
        if base_content.stdout == ancestor_content.stdout:
            clean.append(filepath)
            continue

        # If file wasn't changed on branch since merge-base, it's clean
        if branch_content.stdout == ancestor_content.stdout:
            clean.append(filepath)
            continue

        # Both sides changed — likely conflict
        conflicting.append(filepath)

    return clean, conflicting


def _create_sub_branch(repo: str, base: str, source_branch: str,
                       files: list[str], suffix: str) -> str | None:
    """Create a sub-branch from base containing only specified files from source_branch.

    Returns the sub-branch name, or None on failure.
    """
    sub_branch = f"{source_branch}-heal-{suffix}"

    # Create sub-branch from base
    r = _git(["git", "checkout", "-b", sub_branch, base], repo)
    if r.returncode != 0:
        return None

    # Cherry-pick individual file changes from the source branch
    for filepath in files:
        content = _git(["git", "show", f"{source_branch}:{filepath}"], repo)
        if content.returncode == 0:
            # Ensure parent directory exists
            dirpath = os.path.join(repo, os.path.dirname(filepath))
            if dirpath and not os.path.isdir(dirpath):
                os.makedirs(dirpath, exist_ok=True)
            # Write the file
            fullpath = os.path.join(repo, filepath)
            try:
                with open(fullpath, "w") as f:
                    f.write(content.stdout)
                _git(["git", "add", filepath], repo)
            except Exception as e:
                _log.debug("self_healing: failed to write %s: %s", filepath, e)

    # Commit
    r = _git(["git", "commit", "-m",
              f"heal: {len(files)} files from {source_branch} ({suffix})"], repo)
    if r.returncode != 0:
        _git(["git", "checkout", base], repo)
        _git(["git", "branch", "-D", sub_branch], repo)
        return None

    _git(["git", "checkout", base], repo)
    return sub_branch


def heal(repo: str, branch: str, base: str, *, project_id: str = "",
         dry_run: bool = False) -> dict:
    """Decompose a conflicting branch into mergeable sub-branches.

    Returns:
        {
            "healed": bool,
            "clean_files": list[str],
            "conflicting_files": list[str],
            "sub_branches": list[str],  # created sub-branches
            "merged": int,              # sub-branches merged immediately
            "requeued": int,            # conflict tasks created
            "reason": str,
        }
    """
    result = {
        "healed": False, "clean_files": [], "conflicting_files": [],
        "sub_branches": [], "merged": 0, "requeued": 0, "reason": "",
    }

    if not ENABLED:
        result["reason"] = "disabled"
        return result

    # Get modified files
    files = _modified_files(repo, base, branch)
    if len(files) < MIN_FILES:
        result["reason"] = f"too few files ({len(files)} < {MIN_FILES})"
        return result

    # Classify into clean vs conflicting
    clean, conflicting = _classify_files(repo, base, branch, files)
    result["clean_files"] = clean
    result["conflicting_files"] = conflicting

    if not clean and not conflicting:
        result["reason"] = "no files to process"
        return result

    if not conflicting:
        result["reason"] = "no conflicts — full merge should work"
        return result

    if dry_run:
        result["healed"] = bool(clean)
        result["reason"] = f"dry-run: {len(clean)} clean, {len(conflicting)} conflicting"
        return result

    # Set git identity
    _git(["git", "config", "user.name", "kalepasch1"], repo)
    _git(["git", "config", "user.email", "kalepasch@gmail.com"], repo)
    _git(["git", "checkout", base], repo)

    # Create sub-branch for clean files and merge immediately
    if clean:
        sub = _create_sub_branch(repo, base, branch, clean, "clean")
        if sub:
            result["sub_branches"].append(sub)
            _git(["git", "checkout", base], repo)
            merge_r = _git(["git", "merge", "--no-ff", sub, "-m",
                           f"Merge healed clean files from {branch}"], repo)
            if merge_r.returncode == 0:
                result["merged"] += 1
                _git(["git", "branch", "-d", sub], repo)
            else:
                _git(["git", "merge", "--abort"], repo)

    # Create sub-branches for each conflicting file (or small clusters)
    # Group related files by directory
    dir_groups: dict[str, list[str]] = {}
    for f in conflicting:
        d = os.path.dirname(f) or "root"
        dir_groups.setdefault(d, []).append(f)

    for i, (dir_name, group_files) in enumerate(dir_groups.items()):
        suffix = f"conflict-{i}"
        if not dry_run and db and project_id:
            # Create a focused repair task
            slug_base = branch.replace("agent/", "").replace("/", "-")
            repair_slug = f"heal-{slug_base}-{suffix}"
            file_scope = ",".join(group_files)
            try:
                db.insert("tasks", {
                    "slug": repair_slug,
                    "project_id": project_id,
                    "state": "QUEUED",
                    "prompt": (
                        f"Resolve merge conflict in {', '.join(group_files)}. "
                        f"The original branch '{branch}' conflicted with '{base}'. "
                        f"Apply the intended changes from the branch while preserving "
                        f"the base version's structure. Ensure tests pass."
                    ),
                    "file_scope": file_scope,
                    "kind": "bugfix",
                    "note": f"self-healing decomposition from {branch}",
                })
                result["requeued"] += 1
            except Exception as e:
                _log.debug("self_healing: failed to create repair task: %s", e)

    result["healed"] = result["merged"] > 0 or result["requeued"] > 0
    result["reason"] = (f"decomposed: {result['merged']} merged, "
                       f"{result['requeued']} requeued from {len(files)} files")

    _log.info("self_healing: %s → %s", branch, result["reason"])
    return result


def stats() -> dict:
    """Module status."""
    return {"enabled": ENABLED, "min_files": MIN_FILES}


# ── Standalone mode ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    import json
    if len(sys.argv) < 3:
        print("Usage: self_healing_merge.py <repo> <branch> [base]")
        sys.exit(1)
    repo_path = sys.argv[1]
    branch_name = sys.argv[2]
    base_branch = sys.argv[3] if len(sys.argv) > 3 else "main"
    r = heal(repo_path, branch_name, base_branch, dry_run="--dry-run" in sys.argv)
    print(json.dumps(r, indent=2))
