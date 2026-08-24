#!/usr/bin/env python3
"""
merge_candidate.py — decide whether a merge is worth spending git subprocesses on.

WHY
---
`merged_diff_memory.run()` walks every merge on master in a 14-day window and calls
`_extract_patterns_from_commit` on each, which spawns three git subprocesses per commit
(`git log -1`, `git show --stat`, and `_changed_files`). Measured live on this repo:
448 merges in the window, 58 of which can be rejected from their commit message alone
before any process is spawned — 174 git subprocesses per run spent to reach a foregone
rejection.

This module is the predicate. It gates at the two points that can actually see the data
they need:

  * `is_candidate_message()` — at the top of `_get_merged_commits`, BEFORE any
    subprocess. Rejects reverts, WIP/fixup!/squash!/amend! merges, and merges that did
    not come from an `agent/*` branch (sync merges of origin/master into itself, merge
    commits into HEAD, and PR merges of human branches, none of which the distillation
    pipeline is scoped to).
  * `is_candidate_record()` — in the extraction loop, where the changed-file list
    finally exists. Rejects empty diffs and merges whose every path is ignorable
    (lockfiles, vendored trees, build output, coverage, minified assets, sourcemaps,
    binaries), honouring `MERGED_DIFF_IGNORED_GLOBS`.

WHY THE RULES ARE RE-STATED HERE RATHER THAN IMPORTED
-----------------------------------------------------
`tools/` holds similar path-ignoring logic, and importing it would be the obvious DRY
move. It does not work: `runner/` puts its own directory on `sys.path` and does
`import db` against it, so a sideways import into `tools/` from a module with five
production importers resolves on one machine and shadows `db` on another. Duplicating
~30 lines of glob rules is the cheaper mistake. If these ever need to be shared, the
right move is extracting a dependency-free package both trees import, not making
`runner/` reach into `tools/`.

Public API
----------
    is_candidate_message(message)            -> (bool, reason)
    is_candidate_record(paths)               -> (bool, reason)
    is_ignored_path(path)                    -> bool
    filter_candidate_messages(commits)       -> (kept, rejected)
    stats()                                  -> dict

Environment
-----------
    MERGE_CANDIDATE_ENABLED       Kill switch (default: true — false accepts everything)
    MERGED_DIFF_IGNORED_GLOBS     Comma-separated extra globs to treat as ignorable
    MERGE_CANDIDATE_REQUIRE_AGENT Require an agent/* source branch (default: true)
"""
from __future__ import annotations

import fnmatch
import os
import posixpath
import re

# ── Message-level rules ─────────────────────────────────────────────────────

# A revert undoes work; distilling "conventions" from it teaches the inverse of what
# landed. Matched at a word boundary so "Revert" in a sentence about reverts is caught
# but "reverted_at" in a path is not.
_REVERT = re.compile(r"\brevert(s|ed|ing)?\b", re.I)

# Work-in-progress markers. fixup!/squash!/amend! are git's own autosquash prefixes and
# always denote a commit that is not the final shape of the change.
_WIP = re.compile(r"(?:^|\s)(?:wip\b|fixup!|squash!|amend!)", re.I)

# The distillation pipeline is scoped to fleet-authored work, which always arrives on an
# agent/* branch. Everything else in the window is a sync merge (origin/master into
# itself, a bare SHA into HEAD) or a human PR branch.
_AGENT_BRANCH = re.compile(r"agent/", re.I)


# ── Path-level rules ────────────────────────────────────────────────────────

# Directory names that are never source. Matched as a path COMPONENT, so a legitimate
# file such as runner/distribution.py is not caught by the "dist" entry.
_IGNORED_DIRS = frozenset({
    "node_modules", "__pycache__", ".git", "dist", "build", "vendor",
    "coverage", ".nuxt", ".next", ".output", "target", ".venv", "venv",
    "site-packages", ".pytest_cache", ".mypy_cache", ".ruff_cache", "htmlcov",
})

# Exact filenames that are generated, not authored.
_IGNORED_NAMES = frozenset({
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock",
    "Cargo.lock", "Gemfile.lock", "composer.lock", "go.sum", "uv.lock",
    ".DS_Store",
})

# Suffixes: minified assets, sourcemaps, compiled artefacts and binaries.
_IGNORED_SUFFIXES = (
    ".min.js", ".min.css", ".map", ".lock",
    ".pyc", ".pyo", ".so", ".dylib", ".dll", ".a", ".o", ".class", ".jar",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf", ".svg",
    ".woff", ".woff2", ".ttf", ".eot", ".mp4", ".mov", ".zip", ".gz", ".tar",
    ".whl", ".bin", ".wasm",
)


def _enabled() -> bool:
    return os.environ.get("MERGE_CANDIDATE_ENABLED", "true").strip().lower() \
        not in ("0", "false", "no", "off")


def _require_agent() -> bool:
    return os.environ.get("MERGE_CANDIDATE_REQUIRE_AGENT", "true").strip().lower() \
        not in ("0", "false", "no", "off")


def _extra_globs() -> tuple:
    raw = os.environ.get("MERGED_DIFF_IGNORED_GLOBS", "") or ""
    return tuple(g.strip() for g in raw.split(",") if g.strip())


def is_ignored_path(path) -> bool:
    """True when `path` is generated, vendored or binary — never authored source."""
    if not path or not isinstance(path, str):
        return True
    normalized = path.strip().replace("\\", "/").lstrip("./")
    if not normalized:
        return True

    parts = [p for p in normalized.split("/") if p and p != "."]
    if any(part in _IGNORED_DIRS for part in parts):
        return True

    name = posixpath.basename(normalized)
    if name in _IGNORED_NAMES:
        return True
    lowered = name.lower()
    if any(lowered.endswith(suffix) for suffix in _IGNORED_SUFFIXES):
        return True

    for glob in _extra_globs():
        # Match against both the full path and the bare filename so operators can write
        # either "docs/*" or "*.snap" and have it mean what they expect.
        if fnmatch.fnmatch(normalized, glob) or fnmatch.fnmatch(name, glob):
            return True
    return False


# ── Gate 1: message level (before any subprocess) ───────────────────────────

def is_candidate_message(message):
    """Can this merge be rejected from its commit message alone?

    Returns `(ok, reason)`. `ok=True` means "spend the subprocesses"; the reason is
    always populated so a rejection can be logged rather than silently dropped.
    """
    if not _enabled():
        return True, "gate disabled by MERGE_CANDIDATE_ENABLED"
    if not message or not isinstance(message, str) or not message.strip():
        # An empty subject is not evidence of value, and costs three subprocesses to
        # find that out. Reject and say so.
        return False, "empty commit message"

    text = message.strip()
    if _REVERT.search(text):
        return False, "revert: distilling it would teach the inverse of what landed"
    if _WIP.search(text):
        return False, "work-in-progress marker (wip/fixup!/squash!/amend!)"
    if _require_agent() and not _AGENT_BRANCH.search(text):
        return False, "not an agent/* branch merge (sync merge or human PR)"
    return True, "candidate"


def filter_candidate_messages(commits):
    """Split `[(sha, message), ...]` into (kept, rejected).

    `rejected` carries the reason per commit, so the saving is auditable instead of
    being a number that appears in a summary with nothing behind it.
    """
    kept, rejected = [], []
    for entry in commits or []:
        try:
            sha, message = entry[0], entry[1]
        except (TypeError, IndexError, KeyError):
            rejected.append((entry, "malformed commit entry"))
            continue
        ok, reason = is_candidate_message(message)
        (kept if ok else rejected).append((sha, message) if ok else (sha, reason))
    return kept, rejected


# ── Gate 2: record level (where the changed-file list exists) ───────────────

def is_candidate_record(paths):
    """Is there any authored source in this merge's changed-file list?

    Returns `(ok, reason)`. Called in the extraction loop rather than at message time
    because the file list does not exist until the diff has been read.
    """
    if not _enabled():
        return True, "gate disabled by MERGE_CANDIDATE_ENABLED"
    if paths is None:
        return False, "no changed-file list available"
    try:
        materialized = [p for p in paths]
    except TypeError:
        return False, "changed-file list is not iterable"
    if not materialized:
        return False, "empty diff: no files changed"

    meaningful = [p for p in materialized if not is_ignored_path(p)]
    if not meaningful:
        return False, (f"all {len(materialized)} changed path(s) are ignorable "
                       f"(generated, vendored or binary)")
    return True, f"{len(meaningful)} source path(s) changed"


def stats() -> dict:
    """Current gate configuration, for logs and operator inspection."""
    return {
        "enabled": _enabled(),
        "require_agent_branch": _require_agent(),
        "extra_globs": list(_extra_globs()),
        "ignored_dirs": sorted(_IGNORED_DIRS),
        "ignored_names": sorted(_IGNORED_NAMES),
        "ignored_suffixes": list(_IGNORED_SUFFIXES),
    }
