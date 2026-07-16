#!/usr/bin/env python3
"""Materialize an exact Git commit without registering a Git worktree.

QA/build consumers need immutable files, not a writable Git checkout. Streaming
``git archive`` into a disposable directory avoids index locks, worktree
registry contention, cleanup hangs, and interference from Git maintenance.
"""
from __future__ import annotations
import contextlib
import os
import shutil
import subprocess
import tarfile
import tempfile
import time


def _git(repo, *args, timeout=60):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True,
                          text=True, timeout=timeout)


def _safe_member(member, destination):
    target = os.path.realpath(os.path.join(destination, member.name))
    root = os.path.realpath(destination) + os.sep
    if not target.startswith(root) or member.isdev():
        return False
    if member.issym() or member.islnk():
        link_target = os.path.realpath(os.path.join(os.path.dirname(target), member.linkname))
        return link_target.startswith(root)
    return True


def _omittable_runtime_link(member):
    normalized = member.name.strip("/")
    return (normalized in {"node_modules", ".env", ".env.local"}
            or normalized.endswith("/node_modules"))


def materialize(repo, ref, destination=None):
    started = time.monotonic()
    resolved = _git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}")
    if resolved.returncode:
        raise RuntimeError((resolved.stderr or "candidate commit missing")[-500:])
    commit = resolved.stdout.strip()
    destination = destination or tempfile.mkdtemp(prefix="orch-overlay-")
    os.makedirs(destination, exist_ok=True)
    archive = subprocess.Popen(["git", "archive", "--format=tar", commit], cwd=repo,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    files = []
    omitted_runtime_links = []
    try:
        with tarfile.open(fileobj=archive.stdout, mode="r|") as stream:
            for member in stream:
                if not _safe_member(member, destination) and _omittable_runtime_link(member):
                    omitted_runtime_links.append(member.name)
                    continue
                if not _safe_member(member, destination):
                    raise RuntimeError(f"unsafe archive member: {member.name}")
                stream.extract(member, destination, set_attrs=True)
                if member.isfile() or member.issym():
                    files.append(member.name.rstrip("/"))
        stderr = archive.stderr.read().decode(errors="replace") if archive.stderr else ""
        if archive.wait(timeout=60) != 0:
            raise RuntimeError((stderr or "git archive failed")[-500:])
    except Exception:
        archive.kill()
        shutil.rmtree(destination, ignore_errors=True)
        raise
    return {"path": destination, "commit": commit, "files": sorted(files),
            "omitted_runtime_links": sorted(omitted_runtime_links),
            "duration_ms": int((time.monotonic() - started) * 1000),
            "registered_worktree": False}


@contextlib.contextmanager
def checkout(repo, ref, prefix="orch-overlay-"):
    root = tempfile.mkdtemp(prefix=prefix)
    try:
        yield materialize(repo, ref, root)
    finally:
        shutil.rmtree(root, ignore_errors=True)
