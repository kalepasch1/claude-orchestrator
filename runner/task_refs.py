#!/usr/bin/env python3
"""Immutable, cross-host Git identities for task artifacts.

Mutable ``agent/<slug>`` branches remain a compatibility pointer for the merge
train.  Correctness and attribution use create-only refs: a later worker may
rebase the patch, but it can never overwrite the source artifact identity.
"""
from __future__ import annotations
import hashlib
import re
import subprocess


def _git(repo, *args, input_text=None, timeout=180):
    """Run a git command in the given repo, returning a CompletedProcess."""
    return subprocess.run(["git", *args], cwd=repo, input=input_text,
                          capture_output=True, text=True, timeout=timeout)


def _git_authed(repo, *args, timeout=180):
    """Run a git command with PAT authentication via git_auth.

    Falls back to unauthenticated _git if git_auth is unavailable or
    PAT is not configured.
    """
    try:
        import git_auth
        if git_auth.pat_available():
            rc, out, err = git_auth.run_git(list(args), repo, timeout=timeout)
            # Return a subprocess.CompletedProcess-like object for compatibility
            result = subprocess.CompletedProcess(
                args=["git"] + list(args), returncode=rc,
                stdout=out or "", stderr=err or "")
            return result
    except ImportError:
        pass
    return _git(repo, *args, timeout=timeout)


def _safe(value):
    return re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "task")).strip("-.")[:120] or "task"
    """Sanitize a value for use in git ref paths. Replaces non-alnum chars, strips dots, truncates to 120."""


def patch_id(repo, commit):
    """Stable patch identity, preserved by ordinary rebases."""
    shown = _git(repo, "show", "--pretty=format:", "--binary", str(commit))
    if shown.returncode:
        return ""
    identified = _git(repo, "patch-id", "--stable", input_text=shown.stdout)
    return identified.stdout.split()[0] if identified.returncode == 0 and identified.stdout.split() else ""


def _push_ref(repo, ref, timeout=240):
    """Push a ref to origin using authenticated git if available."""
    return _git_authed(repo, "push", "origin", f"{ref}:{ref}", timeout=timeout)


def publish(repo, task_id, attempt, commit, *, push=True, namespace="tasks"):
    """Create an immutable ref for a task artifact and optionally push it.

    Returns a dict with keys: ok, ref, commit, patch_id, pushed, reason.
    Possible reason values: commit-missing, remote-publish-failed,
    immutable-ref-collision, exists, create-failed.
    """
    resolved = _git(repo, "rev-parse", str(commit))
    if resolved.returncode:
        return {"ok": False, "reason": "commit-missing", "detail": resolved.stderr[-300:]}
    sha = resolved.stdout.strip()
    digest = patch_id(repo, sha) or hashlib.sha256(sha.encode()).hexdigest()
    ref = f"refs/orchestrator/{_safe(namespace)}/{_safe(task_id)}/{int(attempt or 1):04d}/{digest[:20]}"
    has_origin = _git(repo, "remote", "get-url", "origin").returncode == 0
    current = _git(repo, "rev-parse", "--verify", ref)
    if current.returncode == 0:
        ok = current.stdout.strip() == sha
        pushed = False
        if ok and push and has_origin:
            sent = _push_ref(repo, ref)
            pushed = sent.returncode == 0
            if not pushed:
                return {"ok": False, "ref": ref, "commit": sha, "patch_id": digest,
                        "pushed": False, "reason": "remote-publish-failed", "detail": sent.stderr[-300:]}
        return {"ok": ok, "ref": ref, "commit": sha, "patch_id": digest,
                "pushed": pushed, "reason": "exists" if ok else "immutable-ref-collision"}
    created = _git(repo, "update-ref", ref, sha, "0" * 40)
    if created.returncode:
        return {"ok": False, "ref": ref, "commit": sha, "patch_id": digest,
                "reason": "create-failed", "detail": created.stderr[-300:]}
    pushed = False
    if push and has_origin:
        sent = _push_ref(repo, ref)
        pushed = sent.returncode == 0
        if not pushed:
            return {"ok": False, "ref": ref, "commit": sha, "patch_id": digest,
                    "pushed": False, "reason": "remote-publish-failed", "detail": sent.stderr[-300:]}
    return {"ok": True, "ref": ref, "commit": sha, "patch_id": digest, "pushed": pushed}


def resolve(repo, ref):
    result = _git(repo, "rev-parse", "--verify", str(ref))
    return result.stdout.strip() if result.returncode == 0 else ""
