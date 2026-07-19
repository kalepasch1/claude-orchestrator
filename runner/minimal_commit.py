#!/usr/bin/env python3
"""Extract an exact task patch from a noisy branch/artifact commit onto a fresh base."""
import os
import subprocess
import tempfile


def _git(repo, *args, input_bytes=None, timeout=120):
    return subprocess.run(["git", *args], cwd=repo, input=input_bytes, capture_output=True,
                          text=input_bytes is None, timeout=timeout)


def _exists(repo, ref):
    return _git(repo, "cat-file", "-e", str(ref)).returncode == 0


def extract(repo, branch, base, task, *, max_files=40):
    artifact = str(task.get("artifact_commit") or "")
    source = artifact if artifact and _exists(repo, artifact) else branch
    if not _exists(repo, source) or not _exists(repo, base):
        return {"ok": False, "reason": "missing source or base"}
    mb = _git(repo, "merge-base", base, source)
    if mb.returncode != 0:
        return {"ok": False, "reason": "no merge base"}
    merge_base = mb.stdout.strip()
    if source == artifact:
        branch_tip = _git(repo, "rev-parse", branch)
        artifact_is_tip = branch_tip.returncode == 0 and branch_tip.stdout.strip() == source
        count = _git(repo, "rev-list", "--count", f"{merge_base}..{source}")
        commits = int(count.stdout.strip() or "0") if count.returncode == 0 else 0
        # A tip artifact may represent a multi-commit implementation. Selecting
        # only tip^..tip silently drops all earlier task commits.
        start = merge_base if artifact_is_tip and commits > 1 else f"{source}^"
    else:
        start = merge_base
    names = _git(repo, "diff", "--name-only", start, source)
    files = [x for x in names.stdout.splitlines() if x] if names.returncode == 0 else []
    if not files or len(files) > max_files:
        return {"ok": False, "reason": f"unsafe file count: {len(files)}", "files": files}
    noisy = [f for f in files if f.startswith(("node_modules/", ".nuxt/", ".output/", "dist/"))]
    if noisy:
        return {"ok": False, "reason": "generated files in candidate", "files": files}
    diff = _git(repo, "diff", "--binary", start, source, "--", *files)
    if diff.returncode != 0 or not diff.stdout:
        return {"ok": False, "reason": "empty patch", "files": files}
    tmp = tempfile.mkdtemp(prefix="minimal-task-")
    try:
        if _git(repo, "worktree", "add", "--detach", tmp, base).returncode != 0:
            return {"ok": False, "reason": "worktree creation failed"}
        applied = _git(tmp, "apply", "--3way", "-", input_bytes=diff.stdout.encode())
        if applied.returncode != 0:
            return {"ok": False, "reason": "minimal patch does not apply", "files": files}
        _git(tmp, "add", "--", *files)
        message = f"task: {task.get('slug') or task.get('id') or 'minimal-extract'}"
        committed = _git(tmp, "-c", "user.name=orchestrator", "-c", "user.email=orchestrator@local",
                         "commit", "-m", message)
        if committed.returncode != 0:
            return {"ok": False, "reason": "minimal commit failed", "files": files}
        sha = _git(tmp, "rev-parse", "HEAD").stdout.strip()
    finally:
        _git(repo, "worktree", "remove", "--force", tmp)
    if not sha:
        return {"ok": False, "reason": "missing extracted commit", "files": files}
    if _git(repo, "branch", "-f", branch, sha).returncode != 0:
        return {"ok": False, "reason": "could not update branch", "files": files}
    return {"ok": True, "commit": sha, "files": files, "source": source}
