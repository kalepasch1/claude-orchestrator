#!/usr/bin/env python3
"""Immutable, cross-host Git identities for task artifacts.

Mutable ``agent/<slug>`` branches remain a compatibility pointer for the merge
train.  Correctness and attribution use create-only refs: a later worker may
rebase the patch, but it can never overwrite the source artifact identity.
"""
from __future__ import annotations
import hashlib
import os
import re
import subprocess

_auth_applied: set[str] = set()   # repos whose origin URL already has the PAT


def _git(repo, *args, input_text=None, timeout=180):
    return subprocess.run(["git", *args], cwd=repo, input=input_text,
                          capture_output=True, text=True, timeout=timeout)


def _ensure_auth(repo):
    """Inject GITHUB_PAT into the origin URL if it lacks credentials.

    Idempotent: skips repos already patched this process and URLs that already
    contain an access token.  Does nothing when GITHUB_PAT is unset.
    """
    repo_key = os.path.realpath(repo)
    if repo_key in _auth_applied:
        return
    pat = os.environ.get("GITHUB_PAT", "").strip()
    if not pat:
        return
    result = _git(repo, "remote", "get-url", "origin")
    if result.returncode:
        return
    url = result.stdout.strip()
    # Already has a token or is SSH — leave it alone
    if "@github.com" in url and "x-access-token" in url:
        _auth_applied.add(repo_key)
        return
    if url.startswith("git@"):
        return
    # Convert https://github.com/... → https://x-access-token:PAT@github.com/...
    if url.startswith("https://github.com/"):
        authed = url.replace("https://github.com/", f"https://x-access-token:{pat}@github.com/", 1)
        _git(repo, "remote", "set-url", "origin", authed)
        _auth_applied.add(repo_key)
    elif "github.com" in url and "x-access-token" not in url:
        # Other https variants (e.g. https://user@github.com/...)
        authed = re.sub(r"https://[^@]*@?github\.com/", f"https://x-access-token:{pat}@github.com/", url, count=1)
        if authed != url:
            _git(repo, "remote", "set-url", "origin", authed)
            _auth_applied.add(repo_key)


def _safe(value):
    return re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "task")).strip("-.")[:120] or "task"


def patch_id(repo, commit):
    """Stable patch identity, preserved by ordinary rebases."""
    shown = _git(repo, "show", "--pretty=format:", "--binary", str(commit))
    if shown.returncode:
        return ""
    identified = _git(repo, "patch-id", "--stable", input_text=shown.stdout)
    return identified.stdout.split()[0] if identified.returncode == 0 and identified.stdout.split() else ""


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
    if has_origin and push:
        _ensure_auth(repo)
    current = _git(repo, "rev-parse", "--verify", ref)
    if current.returncode == 0:
        ok = current.stdout.strip() == sha
        pushed = False
        if ok and push and has_origin:
            sent = _git(repo, "push", "origin", f"{ref}:{ref}", timeout=240)
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
        sent = _git(repo, "push", "origin", f"{ref}:{ref}", timeout=240)
        pushed = sent.returncode == 0
        if not pushed:
            return {"ok": False, "ref": ref, "commit": sha, "patch_id": digest,
                    "pushed": False, "reason": "remote-publish-failed", "detail": sent.stderr[-300:]}
    return {"ok": True, "ref": ref, "commit": sha, "patch_id": digest, "pushed": pushed}


def resolve(repo, ref):
    result = _git(repo, "rev-parse", "--verify", str(ref))
    return result.stdout.strip() if result.returncode == 0 else ""
