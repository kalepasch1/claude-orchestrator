#!/usr/bin/env python3
"""Which merge commits are worth learning from.

`runner/merged_diff_memory.py::_get_merged_commits()` fed EVERY merge commit in the
lookback window into `_extract_patterns_from_commit()` — reverts, WIP, merges of
non-agent branches, merges whose only changed files are lockfiles. Each one costs
three git subprocesses plus a quality-gate pass, and none of them can yield a
reusable convention, so the work was spent to reach a guaranteed rejection.

The same rules already exist in `tools/merged_diff_memory.py` (added by ccba41d8 as
`is_merge_candidate` / `is_merge_candidate_commit`). They are re-stated here rather
than imported because `runner/` puts its own directory on `sys.path` and does
`import db` against it; reaching sideways into `tools/` from a module with five
production importers is the kind of import that works on one machine and fails in
the runner. `runner/tests/test_merge_candidate_parity.py` holds the two
implementations to the same answers so the duplication cannot drift silently.

Every predicate is fail-soft: malformed input is rejected, never raised on. A scan
that crashes on one bad record loses the whole window.
"""
import fnmatch
import os
import re

AGENT_BRANCH_PATTERN = re.compile(r"^agent/")
MERGE_COMMIT_PATTERN = re.compile(r"^Merge branch ['\"]agent/([^'\"]+)['\"]")

# Message prefixes that never carry reusable signal, even on an agent/* merge.
EXCLUDED_MESSAGE_PATTERN = re.compile(r"^(revert|wip|fixup!|squash!|amend!)\b", re.IGNORECASE)

# Changed paths with no reusable signal: lockfiles, vendored deps, build output, binaries.
IGNORED_PATH_GLOBS = (
    "*.lock",
    "*.min.js",
    "*.min.css",
    "*.map",
    "*.snap",
    "*.png",
    "*.jpg",
    "*.jpeg",
    "*.gif",
    "*.ico",
    "*.pdf",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    ".DS_Store",
)
IGNORED_PATH_SEGMENTS = (
    "node_modules",
    "__pycache__",
    ".git",
    ".venv",
    "vendor",
    "dist",
    "build",
    "coverage",
)


def _extra_ignored_globs():
    """Operator-supplied extra ignore globs (comma-separated) from MERGED_DIFF_IGNORED_GLOBS."""
    raw = os.environ.get("MERGED_DIFF_IGNORED_GLOBS", "")
    return tuple(g.strip() for g in raw.split(",") if g.strip())


def is_ignored_path(path):
    """True when a changed file carries no reusable signal. Unusable input counts as ignored."""
    if not path or not isinstance(path, str):
        return True
    normalized = path.strip().replace("\\", "/").lstrip("./")
    if not normalized:
        return True
    segments = [s for s in normalized.split("/") if s]
    if any(seg in IGNORED_PATH_SEGMENTS for seg in segments):
        return True
    name = segments[-1] if segments else normalized
    for pattern in IGNORED_PATH_GLOBS + _extra_ignored_globs():
        if fnmatch.fnmatch(name, pattern) or fnmatch.fnmatch(normalized, pattern):
            return True
    return False


def merge_candidate_branch(commit_message):
    """The agent branch a merge commit refers to, or None when it is not a candidate."""
    if not commit_message or not isinstance(commit_message, str):
        return None
    first_line = commit_message.strip().split("\n", 1)[0].strip()
    if not first_line:
        return None
    if EXCLUDED_MESSAGE_PATTERN.match(first_line):
        return None
    m = MERGE_COMMIT_PATTERN.match(first_line)
    if not m:
        return None
    branch = m.group(1).strip()
    return branch or None


def is_merge_candidate(commit_message):
    """True when `commit_message` identifies a merged agent/* branch worth learning from.

    Rejects, fail-soft and never raising: non-strings, blank messages, ordinary
    (non-merge) commits, merges of non-agent branches, reverts, and WIP/fixup/squash
    noise.
    """
    return merge_candidate_branch(commit_message) is not None


def is_merge_candidate_commit(commit):
    """True when an extracted merge-commit record is worth writing into merged-diff memory.

    Needs a commit hash, a message `is_merge_candidate` accepts, a non-empty diff, and
    at least one changed file that is not an ignored path. Malformed records are
    rejected rather than raising.
    """
    if not isinstance(commit, dict):
        return False
    if not str(commit.get("commit_hash") or "").strip():
        return False
    if not is_merge_candidate(str(commit.get("merge_message") or "")):
        return False
    if not str(commit.get("diff") or "").strip():
        return False
    files = commit.get("files")
    if not isinstance(files, (list, tuple)):
        return False
    return any(not is_ignored_path(f) for f in files)


def filter_merge_candidates(commits):
    """Keep only (hash, message) pairs worth extracting from.

    Takes the shape `_get_merged_commits()` already returns, so gating a scan is one
    call rather than a rewrite of its loop.
    """
    out = []
    for entry in commits or ():
        try:
            commit_hash, message = entry[0], entry[1]
        except (TypeError, IndexError, KeyError):
            continue
        if not str(commit_hash or "").strip():
            continue
        if is_merge_candidate(str(message or "")):
            out.append((commit_hash, message))
    return out
