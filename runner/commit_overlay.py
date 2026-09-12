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

try:
    import scratch
except ImportError:  # module imported from outside runner/ (tests, tooling)
    import sys as _sys, os as _os
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
    import scratch


def _mkdtemp(prefix):
    """Durable scratch, not /tmp.

    A build overlay holds an exact commit for the length of a production build —
    twenty-five minutes on a loaded Mac. TMPDIR is empty on these machines, so
    tempfile.mkdtemp() was putting that in /tmp, which macOS purges MID-SESSION:
    on 2026-09-01 it deleted two live worktrees and an unpushed commit. A build
    losing its own source tree half way through surfaces as an unreproducible
    error that looks like a code fault.

    Falls back to tempfile only if the durable root cannot be created, because a
    build that runs in a risky directory still beats a fleet that cannot build.
    """
    try:
        return scratch.mkdtemp(prefix=prefix)
    except Exception:
        return tempfile.mkdtemp(prefix=prefix)


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


#: Runtime links the overlay never needs, matched on the LAST path segment.
#:
#: A per-branch install is linked as ``node_modules~<slug>`` (e.g.
#: ``node_modules~agent_cade-tribunal-counterparty-implement-login-step``) so
#: two branches can hold separate installs side by side. The original rule
#: matched only the bare name or a ``/node_modules`` suffix, so a suffixed link
#: was neither safe (it points outside the overlay) nor omittable, and
#: ``materialize`` raised "unsafe archive member" — killing an entire QA overlay
#: over a directory whose contents QA does not read. Fail-soft is the convention
#: here: skip the link, record it, keep going.
_RUNTIME_LINK_PREFIXES = ("node_modules",)
_RUNTIME_LINK_EXACT = frozenset({"node_modules", ".env", ".env.local"})


def _omittable_runtime_link(member):
    normalized = (member.name or "").strip("/")
    if not normalized:
        return False
    segment = normalized.rsplit("/", 1)[-1]
    if segment in _RUNTIME_LINK_EXACT:
        return True
    # `node_modules~<slug>`: a per-branch install, not a repository directory.
    return any(segment.startswith(prefix + "~") for prefix in _RUNTIME_LINK_PREFIXES)


def _attach_gitdir(repo, destination, commit):
    """Give the overlay a real `.git`, so a suite that asks git about itself works.

    `git archive` gives files and nothing else. A project whose tests shell out
    to git -- and this fleet's projects do, that is the whole
    enumerate-live-evidence / reconcile-local-evidence family -- then fails in
    the overlay and only in the overlay:

        [gate:qa] staging QA failed -- fatal: not a git repository
        Error: Command failed: git ls-files -z

    The suite is green in a clean checkout. The gate reports it red. That is the
    gate being wrong about the project, which is the expensive direction to be
    wrong in.

    This does NOT register a worktree, which is what the module docstring is
    about: no entry under the source repo's .git/worktrees, so no index locks,
    no registry contention, no cleanup hang, and rmtree is still the whole
    teardown. It is an independent gitdir that borrows the source repo's object
    database through `objects/info/alternates` and points a detached HEAD at the
    same commit the files came from. No objects are copied; the index is built
    with read-tree.

    Fail-open on purpose: any step that does not work leaves the overlay exactly
    as it is today, plain files. A repo-aware suite is no worse off than before
    the fix, and a suite that never touches git is unaffected either way.
    """
    dot_git = os.path.join(destination, ".git")
    try:
        ok = _build_gitdir(repo, destination, commit, dot_git)
    except Exception:
        ok = False
    if not ok:
        # A half-built gitdir is worse than none: `git ls-files` in it answers
        # "no files" instead of failing, and a suite would read that as an empty
        # repository rather than as a broken overlay.
        shutil.rmtree(dot_git, ignore_errors=True)
    return ok


def _build_gitdir(repo, destination, commit, dot_git):
    objects = _git(repo, "rev-parse", "--path-format=absolute",
                   "--git-path", "objects")
    objects_dir = objects.stdout.strip() if not objects.returncode else ""
    if not objects_dir or not os.path.isdir(objects_dir):
        return False
    if _git(destination, "init", "--quiet").returncode:
        return False
    info = os.path.join(dot_git, "objects", "info")
    os.makedirs(info, exist_ok=True)
    with open(os.path.join(info, "alternates"), "w") as handle:
        handle.write(objects_dir + "\n")
    # Detached HEAD written directly: `git init` leaves HEAD pointing at a
    # branch that does not exist, and the overlay should report the same commit
    # the archive came from rather than invent a branch name.
    with open(os.path.join(dot_git, "HEAD"), "w") as handle:
        handle.write(commit + "\n")
    if _git(destination, "read-tree", commit).returncode:
        return False
    seen = _git(destination, "rev-parse", "HEAD")
    if seen.returncode or seen.stdout.strip() != commit:
        return False
    listed = _git(destination, "ls-files")
    return not listed.returncode and bool(listed.stdout.strip())


def materialize(repo, ref, destination=None):
    started = time.monotonic()
    resolved = _git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}")
    if resolved.returncode:
        raise RuntimeError((resolved.stderr or "candidate commit missing")[-500:])
    commit = resolved.stdout.strip()
    destination = destination or _mkdtemp("orch-overlay-")
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
    git_attached = _attach_gitdir(repo, destination, commit)
    return {"path": destination, "commit": commit, "files": sorted(files),
            "omitted_runtime_links": sorted(omitted_runtime_links),
            "duration_ms": int((time.monotonic() - started) * 1000),
            "registered_worktree": False, "git_attached": git_attached}


@contextlib.contextmanager
def checkout(repo, ref, prefix="orch-overlay-"):
    root = _mkdtemp(prefix)
    try:
        yield materialize(repo, ref, root)
    finally:
        shutil.rmtree(root, ignore_errors=True)
