#!/usr/bin/env python3
"""A scratch root that is still there when you come back to it.

WHY THIS EXISTS.

TMPDIR is empty on this fleet's machines, so Python's tempfile falls back to
/tmp — and macOS purges /tmp. Not only at boot: it ran mid-session on 2026-09-01
and destroyed two live git worktrees and one commit that had not been pushed.

That is not a tidiness problem, it is a correctness one, because of WHAT the
fleet puts there. build_gate materializes an exact commit into
tempfile.mkdtemp(prefix="build-overlay-") and then runs a Nuxt production build
inside it. On a loaded Mac that build takes twenty-five minutes. For all
twenty-five it lives in a directory the operating system is entitled to delete
underneath it, and the failure would arrive as an unreproducible mid-build
error with no indication that the cause was the filesystem rather than the code.

The staging checkouts merge_train makes ('stg-*'), the QA overlays, the
dependency prewarm trees — same story, same directory.

WHAT THIS DOES.

One durable root, default ~/.orch-scratch, overridable with ORCH_SCRATCH_ROOT.
mkdtemp() here behaves exactly like tempfile.mkdtemp() except that what it
returns survives a purge.

It REFUSES a purgeable root rather than accepting one and hoping. If someone
points ORCH_SCRATCH_ROOT at /tmp, that is the bug this module exists to prevent,
and silently obeying would reintroduce it while looking configured.
"""
from __future__ import annotations

import os
import tempfile

#: Roots macOS (or a distro's tmpfiles) may delete out from under a running job.
#: /var/folders is the per-user TMPDIR macOS normally sets; it is purged too,
#: just less eagerly, and "less eagerly" is not a guarantee a 25-minute build
#: can rely on.
PURGEABLE_PREFIXES = ("/tmp", "/private/tmp", "/var/tmp", "/private/var/tmp",
                      "/var/folders", "/private/var/folders", "/dev/shm")

#: The `.noindex` suffix is the point, not decoration.
#:
#: 8a6c0305 wrote `.metadata_never_index` markers into the scratch root and said, in
#: as many words, that this is best-effort and not guaranteed. It was not guaranteed.
#: Measured across the following hour on the same machine:
#:
#:     mds_stores   76.6%  ->  8.8%  ->  132.7%
#:
#: It oscillates; the marker is honoured at a volume root and not dependably for an
#: arbitrary directory. macOS DOES skip any directory whose NAME ends in `.noindex`,
#: and that is a mechanism this fleet owns outright -- no admin password, no System
#: Settings, no per-machine setup a new Mac would silently miss.
#:
#: What lives here is build overlays and staging checkouts holding cloned
#: node_modules -- 76,928 files per clone, cloned again per merge candidate, then
#: deleted. Indexing them is an FSEvents storm and an index update for files that
#: exist for minutes, and LOAD is what resource_governor clamps lanes on, so it is
#: paid in merge throughput.
#:
#: Changing the default abandons whatever is in the old root. That is safe precisely
#: because this directory is disposable by definition -- and in-flight builds hold
#: absolute paths they resolved at start, so nothing moves under a running build.
DEFAULT_ROOT = os.path.join(os.path.expanduser("~"), ".orch-scratch.noindex")

#: The pre-2026-09-03 root. Still recognised by tooling that classifies a process as
#: fleet-owned (see resource_medic._GATE_OWNED_PATHS) so an overlay left there by a
#: process started before this change is still reaped rather than orphaned forever.
LEGACY_ROOT = os.path.join(os.path.expanduser("~"), ".orch-scratch")


class PurgeableScratchRoot(RuntimeError):
    """Raised when the configured scratch root is a directory the OS may clear."""


def is_purgeable(path) -> bool:
    """Would the OS be entitled to delete things under `path`?"""
    try:
        real = os.path.realpath(str(path))
    except (TypeError, ValueError):
        return True
    return any(real == p or real.startswith(p + os.sep) for p in PURGEABLE_PREFIXES)


def root() -> str:
    """The durable scratch root, created if absent.

    Raises PurgeableScratchRoot if configured somewhere the OS may clear. A
    scratch root that quietly falls back to /tmp is the defect, not the fix.
    """
    configured = os.environ.get("ORCH_SCRATCH_ROOT", "").strip() or DEFAULT_ROOT
    path = os.path.abspath(os.path.expanduser(configured))
    if is_purgeable(path):
        raise PurgeableScratchRoot(
            f"ORCH_SCRATCH_ROOT={configured!r} resolves under a purgeable directory. "
            "Build overlays and staging checkouts live here for the length of a build; "
            "macOS clears these paths mid-session. Point it at a durable path such as "
            f"{DEFAULT_ROOT}."
        )
    os.makedirs(path, exist_ok=True)
    exclude_from_spotlight(path)
    return path


#: macOS honours this marker file as "do not index anything under here".
NEVER_INDEX_MARKER = ".metadata_never_index"


def exclude_from_spotlight(path) -> bool:
    """Ask Spotlight not to index a directory of pure build churn. Best-effort.

    MEASURED 2026-09-03 on this Mac:

        mds_stores  76.6% CPU, continuously, for 1 day 2 hours
        mds         33.4% CPU
        mdfind      a simple query under ~/.orch-scratch did not return in 3 minutes

    That is roughly a permanent core and a bit, and it is spent indexing content
    that nobody will ever search for: build overlays, staging checkouts, and
    node_modules clones -- 76,928 files per clone, cloned again per merge
    candidate, then deleted. Every one of those is an FSEvents storm and an index
    update for files that exist for minutes.

    It matters beyond the wasted core because LOAD is what resource_governor
    clamps lanes on. With the box at load/core 2.5 the fleet runs one task lane
    and one merge worker, so Spotlight indexing throwaway trees directly costs
    throughput -- the same argument reap_orphaned_builds and the CPU clamp make.

    Best-effort and reversible: deleting the marker file restores indexing. This
    is NOT a guaranteed exclusion -- the reliable mechanism is adding the path
    under System Settings -> Spotlight -> Privacy, which needs a person -- so
    nothing here depends on it having worked.
    """
    try:
        marker = os.path.join(path, NEVER_INDEX_MARKER)
        if os.path.exists(marker):
            return True
        with open(marker, "a"):
            pass
        return True
    except OSError:
        return False


def mkdtemp(prefix="orch-", suffix=None) -> str:
    """tempfile.mkdtemp(), but under a root the OS will not clear."""
    return tempfile.mkdtemp(prefix=prefix, suffix=suffix, dir=root())


def install_tmpdir() -> str:
    """Point this process's TMPDIR at the durable root.

    Belt and braces for the modules that call tempfile directly and have not
    been converted. Called once at runner start; every mkdtemp in the process
    inherits it, including ones in libraries this repo does not own.
    """
    path = root()
    os.environ.setdefault("TMPDIR", path)
    tempfile.tempdir = None  # force tempfile to re-read TMPDIR on next use
    return path
