#!/usr/bin/env python3
"""
bundle_handoff.py - PURE helpers for durable bundle handoff.

When a session on a flaky filesystem loses repo-tree writes between turns, a durable
outputs/bundle folder can persist. This module lets the intake format specify a per-task
`bundle: <path>` field pointing at a verified directory of files at repo-relative subpaths.
The task runner copies the bundle into the task's worktree BEFORE the agent runs, so a task
can be "land this verified bundle" with no re-implementation needed.

Fail-safe: a missing/empty bundle just no-ops (task proceeds normally).
"""
import os
import re

# Only allow copies into these known repo subtrees (security: prevent writes to .git, etc.)
_ALLOWED_REPO_PREFIXES = (
    "runner/", "web/", "scripts/", "deploy/", "docs/", "growth-os/",
    "intake/", "packages/", "supabase/", "tasks/", "cowork-backlog/",
    "memory/", "reports/",
)


def parse_bundle_field(task_block: str) -> str:
    """Extract the bundle path from a task block string.

    Looks for a line like `bundle: <path>` in the task block.
    Returns the path string (stripped), or empty string if not found.
    """
    if not task_block:
        return ""
    for line in task_block.splitlines():
        m = re.match(r"^\s*bundle:\s*(.+)$", line.strip())
        if m:
            return m.group(1).strip()
    return ""


def plan_bundle_apply(bundle_dir: str) -> list:
    """Plan copy operations from a bundle directory to repo-relative destinations.

    Args:
        bundle_dir: Absolute path to the bundle directory containing files at
                    repo-relative subpaths (e.g., bundle_dir/runner/foo.py -> runner/foo.py).

    Returns:
        List of (src_abs, repo_relative_dest) tuples. Empty list if bundle_dir is
        missing, empty, or contains only path-traversal attempts.

    Security:
        - Rejects any path containing '..' components (path traversal).
        - Only allows destinations under known repo subtrees.
        - Rejects paths starting with '.' (no .git, .env, etc.).
    """
    if not bundle_dir or not os.path.isdir(bundle_dir):
        return []

    ops = []
    for root, _dirs, files in os.walk(bundle_dir):
        for fname in files:
            src = os.path.join(root, fname)
            rel = os.path.relpath(src, bundle_dir)

            # Reject path traversal
            parts = rel.replace("\\", "/").split("/")
            if ".." in parts:
                continue

            # Reject hidden top-level dirs (e.g., .git/)
            if parts[0].startswith("."):
                continue

            # Normalize to forward slashes
            rel_norm = "/".join(parts)

            # Only allow known repo subtrees
            if not any(rel_norm.startswith(prefix) for prefix in _ALLOWED_REPO_PREFIXES):
                continue

            ops.append((src, rel_norm))

    return sorted(ops, key=lambda x: x[1])


def apply_bundle(bundle_dir: str, worktree_path: str) -> int:
    """Copy bundle files into a worktree. Returns count of files copied.

    Fail-safe: returns 0 on any error (missing bundle, empty, etc.).
    """
    try:
        ops = plan_bundle_apply(bundle_dir)
        if not ops:
            return 0
        import shutil
        copied = 0
        for src, rel_dest in ops:
            dest = os.path.join(worktree_path, rel_dest)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copy2(src, dest)
            copied += 1
        return copied
    except Exception:
        return 0
