#!/usr/bin/env python3
"""Fail-closed runtime shared by Git merge and release trains."""
from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import time


class IntegrationRuntimeError(RuntimeError):
    pass


class CanonicalCheckoutMutationError(IntegrationRuntimeError):
    pass


# Generated dependency/build artifacts can make an otherwise clean persistent
# integration slot consume gigabytes.  They are removed only after a successful
# integration pass; failures retain their full worktree for forensic recovery.
_RUNTIME_ARTIFACT_DIRS = (
    "node_modules", ".nuxt", ".output", ".next", "dist", "coverage",
    ".pytest_cache", "__pycache__",
)


def _home():
    return os.environ.get(
        "CLAUDE_ORCH_HOME",
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".runtime"),
    )


def _git(repo, *args, timeout=120):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, timeout=timeout)


def canonical_snapshot(repo):
    top = _git(repo, "rev-parse", "--show-toplevel")
    branch = _git(repo, "symbolic-ref", "-q", "HEAD")
    head = _git(repo, "rev-parse", "HEAD")
    status = _git(repo, "status", "--porcelain=v1", "--untracked-files=all")
    if top.returncode or head.returncode or status.returncode:
        raise IntegrationRuntimeError(f"cannot snapshot canonical Git checkout: {repo}")
    return {
        "top": os.path.realpath(top.stdout.strip()),
        "branch": branch.stdout.strip() if branch.returncode == 0 else "DETACHED",
        "head": head.stdout.strip(),
        "status": status.stdout,
    }


def _worktree_path(repo):
    key = hashlib.sha256(os.path.realpath(repo).encode()).hexdigest()[:20]
    return os.path.join(_home(), "integration-worktrees", key)


def _temporary_worktree_path(repo):
    """A one-run worktree used when the persistent slot contains evidence.

    The persistent slot is deliberately retained for forensic recovery rather
    than force-cleaned.  A unique sibling lets the next train pass continue
    safely instead of repeatedly blocking an entire project's queue.
    """
    return f"{_worktree_path(repo)}-run-{os.getpid()}-{time.time_ns()}"


def _registered_worktrees(repo):
    result = _git(repo, "worktree", "list", "--porcelain")
    if result.returncode:
        return set()
    return {
        os.path.realpath(line.removeprefix("worktree ").strip())
        for line in result.stdout.splitlines()
        if line.startswith("worktree ")
    }


def _purge_runtime_artifacts(path):
    """Remove only known rebuildable artifacts from a successful worktree."""
    for root, dirs, _ in os.walk(path):
        # Do not descend into directories that we will delete.  This is both
        # faster for node_modules and avoids following any directory symlinks.
        for name in list(dirs):
            if name not in _RUNTIME_ARTIFACT_DIRS:
                continue
            candidate = os.path.join(root, name)
            if os.path.islink(candidate):
                continue
            shutil.rmtree(candidate, ignore_errors=True)
            dirs.remove(name)


@contextlib.contextmanager
def global_lease(owner, timeout=0):
    """One machine-wide lease for both merge_train and release_train."""
    path = os.path.join(_home(), "integration-trains.single.lock")
    handle = None
    acquired = False
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        handle = open(path, "a+")
        deadline = time.monotonic() + max(0.0, float(timeout or 0))
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except (BlockingIOError, OSError):
                if not timeout or time.monotonic() >= deadline:
                    break
                time.sleep(0.1)
        if acquired:
            handle.seek(0)
            handle.truncate()
            handle.write(json.dumps({"pid": os.getpid(), "owner": owner, "at": time.time()}))
            handle.flush()
    except OSError:
        # Only acquisition failures are fail-closed.  Do not catch exceptions
        # raised *inside* the with-body: contextlib would otherwise attempt a
        # second yield and mask the real database/network failure with
        # "generator didn't stop after throw()".
        if handle:
            handle.close()
            handle = None
        yield False
        return
    try:
        yield acquired
    finally:
        if acquired and handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_UN)
            except OSError:
                pass
        if handle:
            handle.close()


def _rmtree_if_orphaned(canonical_repo, path):
    """Delete `path` when git no longer knows about it as a worktree.

    `git worktree remove` refuses with "is not a working tree" once the registration has been
    pruned, which is exactly the state a leaked temporary ends up in: the removal never ran, a
    later `worktree prune` deregistered it, and the directory became invisible to every git
    command while still occupying disk. Ten of them were sitting here at 1.5GB.
    """
    if not os.path.isdir(path):
        return
    try:
        if os.path.realpath(path) in _registered_worktrees(canonical_repo):
            return  # git still owns it; removing the directory behind git's back is not ours to do
        import shutil
        shutil.rmtree(path, ignore_errors=True)
        if not os.path.isdir(path):
            print(f"integration_runtime: removed orphaned temporary worktree {path}")
    except Exception as exc:
        print(f"integration_runtime: could not remove orphaned {path}: {exc}")


def _temp_owner_alive(path):
    """Is the process that created this temporary slot still running?

    The name is `<slot>-run-<pid>-<ns>`, so the creator is recoverable from the path. A slot
    whose creator is gone can never be cleaned up by that creator, which is the whole problem.
    Unparseable name -> assume alive, because guessing wrong in that direction only costs disk.
    """
    m = re.search(r"-run-(\d+)-\d+$", os.path.basename(path))
    if not m:
        return True
    try:
        os.kill(int(m.group(1)), 0)
        return True
    except ProcessLookupError:
        return False
    except OSError:
        return True          # exists but not ours to signal


def sweep_orphaned_temporaries(canonical_repo):
    """Reclaim -run-<pid>-<ns> slots nobody can finish. Cheap, idempotent, conservative.

    Two states, both created by a pass that did not reach its own cleanup:

      * git no longer tracks the directory. `git worktree remove` refuses these with "is not a
        working tree", so they were invisible to every git command while still holding disk —
        10 of them, 1.5GB.
      * git still tracks it, but the creating process is gone. Observed after killing a wedged
        train: a registered, clean, 83MB temporary that nothing would ever collect, because the
        only code that removes a temporary runs in the `finally` of the pass that made it.

    Only ever touches a slot that is a temporary BY NAME, has no uncommitted content, and whose
    creator is dead. A live pass's worktree is never eligible.
    """
    import glob
    removed = 0
    for d in sorted(glob.glob(f"{_worktree_path(canonical_repo)}-run-*")):
        if not os.path.isdir(d):
            continue
        if os.path.realpath(d) not in _registered_worktrees(canonical_repo):
            _rmtree_if_orphaned(canonical_repo, d)
            removed += int(not os.path.isdir(d))
            continue
        if _temp_owner_alive(d):
            continue
        status = _git(d, "status", "--porcelain=v1", "--untracked-files=all")
        if status.returncode or status.stdout:
            continue          # holds something; leave it for a human
        _git(canonical_repo, "worktree", "remove", "--force", d)
        _rmtree_if_orphaned(canonical_repo, d)
        if not os.path.isdir(d):
            removed += 1
            print(f"integration_runtime: collected abandoned temporary worktree {d} "
                  f"(creating process is gone, nothing uncommitted)")
    return removed


def _canonical_mutation(before, after):
    """Describe how the canonical checkout changed, or "" when nothing that matters did.

    The old test was `before != after` on a snapshot whose `status` came from
    `--untracked-files=all`. The fleet drops untracked files into the canonical checkout
    constantly — ADR notes, reports, scratch scripts — so this fired on ordinary noise:
    57 times in merge-train.log. An untracked file APPEARING cannot destroy anyone's work,
    and treating it as a mutation is the same over-literal reading of "dirty" that once
    deadlocked the merge train for five hours.

    What the guard exists to catch is a pass that moves HEAD, switches branch, changes repo,
    or edits/deletes TRACKED files in the canonical checkout. Those are still absolute.
    Regenerable tracked dirt is exempt on the same terms as everywhere else.
    """
    for key in ("top", "branch", "head"):
        if before.get(key) != after.get(key):
            return f"{key}: {before.get(key)} -> {after.get(key)}"

    def tracked_blocking(status):
        lines = [l for l in (status or "").splitlines() if l.strip() and not l.startswith("??")]
        try:
            import regenerable_artifacts
            return regenerable_artifacts.partition_dirt("\n".join(lines))[0]
        except Exception:
            return lines

    b, a = tracked_blocking(before.get("status")), tracked_blocking(after.get("status"))
    if b != a:
        appeared = [l for l in a if l not in b]
        vanished = [l for l in b if l not in a]
        bits = []
        if appeared:
            bits.append("tracked dirt appeared: " + ", ".join(x[3:].strip() for x in appeared[:5]))
        if vanished:
            bits.append("tracked dirt vanished: " + ", ".join(x[3:].strip() for x in vanished[:5]))
        return "; ".join(bits)
    return ""


@contextlib.contextmanager
def isolated_repo(canonical_repo, owner):
    """Yield a clean detached integration worktree; never the canonical path."""
    canonical_repo = os.path.realpath(canonical_repo)
    before = canonical_snapshot(canonical_repo)
    path = _worktree_path(canonical_repo)
    temporary = False
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # 2026-07-31: a killed/crashed pass leaves registrations pointing at removed
    # directories; the next pass then hit FileNotFoundError mid-flight. Prune
    # stale registrations up front so state on disk and in git agree.
    try:
        _git(canonical_repo, "worktree", "prune")
    except Exception:
        pass
    try:
        # Prune deregisters leaked temporaries but leaves the directories on disk, where no
        # git command can see them again. Collect them here so the tree cannot grow without
        # bound the way it did today (24 slots / 2.4GB, 1.5GB of it abandoned -run- dirs).
        sweep_orphaned_temporaries(canonical_repo)
    except Exception:
        pass
    registered = _registered_worktrees(canonical_repo)
    # Never delete uncommitted integration work automatically.  It may contain
    # a partially completed merge that needs review.  Instead preserve that
    # evidence in the persistent slot and run this pass in a fresh, disposable
    # detached worktree.  Previously the refusal below retried forever and
    # starved every approved card for the affected project.
    if os.path.exists(path) and os.path.realpath(path) in registered:
        existing_dirty = _git(path, "status", "--porcelain=v1", "--untracked-files=all")
        if existing_dirty.returncode or existing_dirty.stdout:
            # RECLAIM WHEN THE DIRT IS ONLY MACHINE OUTPUT (2026-08-06).
            #
            # "Dirty" was any byte of difference, including untracked build caches, so a slot
            # that once ran a test suite was condemned for life: every pass logged "preserving
            # dirty worktree" and built a fresh temporary one instead. Measured today — 21 slots,
            # 2.2GB, and a release-train log consisting of nothing but that line. Three slots
            # were stuck; one on a vitest cache and a __pycache__ .pyc.
            #
            # regenerable_artifacts already draws the only line that matters here: would a reset
            # destroy something nobody can get back? If every dirty path is machine output, the
            # slot is safe to reset and reuse. If ANY path is real work it is preserved exactly
            # as before — including a checkout with deleted source files, which is not work but
            # is not ours to judge either.
            blocking, regen = ([], [])
            try:
                import regenerable_artifacts
                blocking, regen = regenerable_artifacts.partition_dirt(existing_dirty.stdout or "")
            except Exception as exc:
                blocking = [l for l in (existing_dirty.stdout or "").splitlines() if l.strip()]
                print(f"integration_runtime: dirt classification unavailable ({exc}); "
                      f"treating all of it as blocking")
            if not existing_dirty.returncode and regen and not blocking:
                names = ", ".join(l[3:].strip() for l in regen[:5])
                more = "" if len(regen) <= 5 else f" (+{len(regen) - 5} more)"
                print(f"integration_runtime: reclaiming {path} — {len(regen)} regenerable "
                      f"artifact(s) discarded, no real work present: {names}{more}")
                _git(path, "reset", "--hard")
                _git(path, "clean", "-fdq")
            else:
                print(f"integration_runtime: preserving dirty worktree {path}; using a fresh "
                      f"temporary slot ({len(blocking)} path(s) are real work, not artifacts)")
                path = _temporary_worktree_path(canonical_repo)
                temporary = True
    if os.path.exists(path) and os.path.realpath(path) not in registered:
        # Stale worktree from a crashed previous run — clean up and recreate
        # rather than permanently blocking all merges for this project.
        import shutil
        try:
            _git(canonical_repo, "worktree", "remove", "--force", path)
        except Exception:
            pass
        shutil.rmtree(path, ignore_errors=True)
        if os.path.exists(path):
            raise IntegrationRuntimeError(f"unregistered integration path exists and cannot be removed: {path}")
    if not os.path.exists(path):
        added = _git(canonical_repo, "worktree", "add", "--detach", path, before["head"])
        if added.returncode or not os.path.isdir(path):
            raise IntegrationRuntimeError((added.stderr or added.stdout or "worktree add failed")[-1000:])
    actual = _git(path, "rev-parse", "--show-toplevel")
    branch = _git(path, "symbolic-ref", "-q", "HEAD")
    dirty = _git(path, "status", "--porcelain=v1", "--untracked-files=all")
    if actual.returncode or os.path.realpath(actual.stdout.strip()) != os.path.realpath(path):
        raise IntegrationRuntimeError("integration path is not the expected Git worktree")
    # 2026-07-31: these two used to be HARD errors with no recovery — a single
    # branch-attached or late-detected-dirty slot blocked EVERY merge for its
    # project forever (581 skipped/0 merged; no prod promotion since Jul 28).
    # Recovery now mirrors the documented strategy above: a clean-but-attached
    # slot is simply re-detached; anything else is PRESERVED and the pass runs
    # in a fresh temporary detached slot.
    if branch.returncode == 0 and not temporary:
        if not (dirty.returncode or dirty.stdout):
            det = _git(path, "checkout", "--detach", before["head"])
            if det.returncode:
                print(f"integration_runtime: cannot detach {path}; preserving + using temp slot")
                path = _temporary_worktree_path(canonical_repo)
                temporary = True
            else:
                branch = _git(path, "symbolic-ref", "-q", "HEAD")
        else:
            print(f"integration_runtime: preserving branch-attached dirty worktree {path}; using temp slot")
            path = _temporary_worktree_path(canonical_repo)
            temporary = True
    elif (dirty.returncode or dirty.stdout) and not temporary:
        print(f"integration_runtime: preserving late-detected dirty worktree {path}; using temp slot")
        path = _temporary_worktree_path(canonical_repo)
        temporary = True
    if temporary and not os.path.exists(path):
        added = _git(canonical_repo, "worktree", "add", "--detach", path, before["head"])
        if added.returncode or not os.path.isdir(path):
            raise IntegrationRuntimeError((added.stderr or added.stdout or "temp worktree add failed")[-1000:])
        branch = _git(path, "symbolic-ref", "-q", "HEAD")
        dirty = _git(path, "status", "--porcelain=v1", "--untracked-files=all")
    if branch.returncode == 0:
        raise IntegrationRuntimeError("integration worktree must remain detached")
    if dirty.returncode or dirty.stdout:
        raise IntegrationRuntimeError("integration worktree is dirty; refusing cleanup")
    positioned = _git(path, "checkout", "--detach", before["head"])
    if positioned.returncode:
        raise IntegrationRuntimeError((positioned.stderr or positioned.stdout)[-1000:])
    completed = False
    try:
        yield path
        completed = True
    finally:
        after = canonical_snapshot(canonical_repo)
        mutation = _canonical_mutation(before, after)
        # CLEANUP BEFORE THE VERDICT (2026-08-06). The mutation check used to raise from here,
        # BEFORE the removal below, so any canonical drift during a pass leaked the temporary
        # worktree permanently. Measured: 57 CanonicalCheckoutMutationError in merge-train.log
        # and 10 abandoned -run-<pid>-<ns> slots totalling 1.5GB of the 2.4GB tree — 8 of them
        # spawned by one blocked slot that gets bypassed on every single pass.
        #
        # Releasing the disk is never the wrong thing to do on the way out, and the error still
        # propagates immediately afterwards, so the guard keeps its teeth.
        try:
            # This path was created solely to bypass a preserved dirty slot.  Remove
            # it only after confirming it is clean; never force-clean a worktree
            # that has acquired new integration evidence.
            if temporary:
                clean = _git(path, "status", "--porcelain=v1", "--untracked-files=all")
                if clean.returncode == 0 and not clean.stdout:
                    _git(canonical_repo, "worktree", "remove", "--force", path)
                    _rmtree_if_orphaned(canonical_repo, path)
            elif completed:
                # The worktree completed normally, so generated dependencies and
                # build output are safe to rebuild on the next integration pass.
                _purge_runtime_artifacts(path)
        finally:
            if mutation:
                raise CanonicalCheckoutMutationError(
                    f"{owner} changed canonical checkout {canonical_repo}: {mutation}"
                )
