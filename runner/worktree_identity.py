#!/usr/bin/env python3
"""Record which task a worktree serves, so ownership is read rather than guessed.

The worktree convention is `{repo}-wt/{slug}`, and the reconciler relies on it:
to decide whether a dirty worktree is abandoned work or work a live agent is
holding right now, it has to turn a directory path into a task slug.

On 2026-08-23 that failed silently. `tools/reconcile_worktree_evidence.py`
classified `madeus-group-3` as RECOVERABLE_VALUE while it was owned by a task in
state RUNNING under another executor. The task's slug is

    dropbox-beethoven-madeus-web-multi-tenant-claude-preneur-platform-bi-group-3

and the directory is `madeus-group-3`, which is not a prefix of it, not a suffix
of it, and shares no usable boundary with it. The convention says the directory
IS the slug; in practice slugs get shortened when they are long, and nothing
recorded what the shortening was.

The tempting repair is a fuzzy match — longest common substring, token overlap,
something that would have linked those two strings. That is the wrong direction.
A false positive here does not fail loudly: it marks genuinely recoverable work
as owned, and the work is quietly dropped. Guessing is what produced the bug.

So the slug is written down at creation time and read back later. Two functions,
no inference, and both fail soft: an unstamped worktree returns None (unknown,
decide by other means) rather than raising or asserting a guess.

Renaming every worktree to its full slug would also work and is arguably the
purer fix, but it changes paths that live processes are already sitting in, and
some slugs exceed comfortable path lengths. Stamping is additive: it makes new
worktrees provable without moving anything that exists.
"""
import json
import os
import time

# Dotfile, so it never collides with repo content and never shows up in a diff
# of the working tree — the reconciler reads dirty worktrees, and an identity
# marker that itself registered as uncommitted evidence would be self-defeating.
MARKER = ".orch-worktree.json"

SCHEMA_VERSION = 1


def marker_path(worktree_path):
    """Absolute path of the identity marker for a worktree. Never raises."""
    try:
        return os.path.join(str(worktree_path), MARKER)
    except Exception as exc:                      # noqa: BLE001
        # Only reachable for a path that cannot be stringified (a mock, a bad
        # __str__). Named rather than swallowed, per CLAUDE.md: a broad catch
        # that writes nothing destroys the only evidence it went wrong.
        print(f"[worktree-identity] bad worktree path {worktree_path!r}: {exc}")
        return ""


def stamp(worktree_path, slug, branch=None, repo=None):
    """Record that `worktree_path` serves `slug`. Returns True if written.

    Fail-soft by contract: a worktree that cannot be stamped is still a usable
    worktree, and refusing to create one because a marker could not be written
    would trade a diagnosability problem for an availability problem. Callers
    treat the return value as advisory.
    """
    if not worktree_path or not slug:
        return False
    path = marker_path(worktree_path)
    if not path:
        return False
    payload = {
        "schema": SCHEMA_VERSION,
        "slug": str(slug),
        "branch": branch or f"agent/{slug}",
        "created_at": int(time.time()),
    }
    if repo:
        payload["repo"] = str(repo)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, sort_keys=True)
        # Atomic: a reader must never see a half-written marker and conclude the
        # worktree is unowned, which is the exact failure this file exists to fix.
        os.replace(tmp, path)
        return True
    except Exception as exc:                      # noqa: BLE001 - see module docstring
        print(f"[worktree-identity] could not stamp {path}: {exc}; ownership will be unknown")
        return False


def read_slug(worktree_path):
    """The slug this worktree serves, or None if it is not recorded.

    None means "unknown", never "unowned". A caller deciding whether work may be
    discarded must treat None as a reason to defer, not as permission.
    """
    return (read_identity(worktree_path) or {}).get("slug")


def read_identity(worktree_path):
    """Full marker payload, or None. Never raises on missing or corrupt markers."""
    path = marker_path(worktree_path)
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception as exc:                      # noqa: BLE001
        print(f"[worktree-identity] unreadable marker at {path}: {exc}; treating as unknown")
        return None
    if not isinstance(data, dict) or not data.get("slug"):
        return None
    return data


def is_stamped(worktree_path):
    """True only if a well-formed marker exists."""
    return read_identity(worktree_path) is not None


def slug_for_path(worktree_path, fallback_to_basename=False):
    """Resolve a worktree path to a slug.

    With `fallback_to_basename=False` (the default) this returns the recorded
    slug or None — no inference at all. The flag exists for callers reconciling
    worktrees created before stamping, where the directory name is the only
    evidence available; even then the result is the basename verbatim, which the
    caller can confirm against real task state. It is never a fuzzy match.
    """
    slug = read_slug(worktree_path)
    if slug:
        return slug
    if fallback_to_basename and worktree_path:
        try:
            return os.path.basename(str(worktree_path).rstrip("/")) or None
        except Exception as exc:                  # noqa: BLE001
            print(f"[worktree-identity] cannot derive a basename from {worktree_path!r}: {exc}")
            return None
    return None
