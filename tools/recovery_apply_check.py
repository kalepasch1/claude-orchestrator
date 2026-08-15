#!/usr/bin/env python3
"""Decide, honestly, whether a recovered diff can still be landed.

WHY THIS EXISTS
---------------
Every reconciler in this family used to answer that question with:

    git apply --check --3way -

That check is wrong, and wrong in the dangerous direction. `--check --3way`
exits 0 when a three-way merge is POSSIBLE, not when it is CONFLICT-FREE. Git
will happily print

    Applied patch to 'runner/slo_controller.py' with conflicts.

and still exit 0. So a diff that produces conflict markers in six files was
being classified RECOVERABLE_VALUE ("applies cleanly to base") and handed to a
recovery task as ready to land. Observed live on
agent/dropbox-hisanta-mastery-engine-grandma-rail-family-slice-2-clean-129448:
`--check --3way` reported clean, the real apply produced 6 conflicted paths.

This module answers the question properly, without touching the working tree.
It stages the merge into a THROWAWAY index file (GIT_INDEX_FILE), so nothing in
the caller's worktree, index or HEAD is modified — which matters because every
source in this pipeline is read-only evidence.

Verdicts:
    "empty"       nothing to apply
    "clean"       applies exactly, no merge needed
    "three_way"   needs a three-way merge but resolves without conflicts
    "conflicted"  produces conflicts; needs a focused follow-up, never a
                  forced overwrite

`is_landable()` collapses that to a bool for the RECOVERABLE_VALUE decision:
"clean" and "three_way" are landable, "conflicted" is not.
"""

from __future__ import annotations

import os
import subprocess
import tempfile

VERDICT_EMPTY = "empty"
VERDICT_CLEAN = "clean"
VERDICT_THREE_WAY = "three_way"
VERDICT_CONFLICTED = "conflicted"

LANDABLE = (VERDICT_CLEAN, VERDICT_THREE_WAY)


def _run(args, cwd, env=None, stdin=None):
    return subprocess.run(
        args, cwd=cwd, env=env, input=stdin,
        capture_output=True, text=True, errors="replace",
    )


def apply_verdict(diff_text: str, base: str = "HEAD", cwd: str = ".") -> str:
    """Classify how `diff_text` would land on `base`. Never mutates anything."""
    if not diff_text.strip():
        return VERDICT_EMPTY

    # 1. Strict check: does it apply exactly, with no merge at all?
    if _run(["git", "apply", "--check", "-"], cwd, stdin=diff_text).returncode == 0:
        return VERDICT_CLEAN

    # 2. Otherwise try the three-way merge for real, but into a scratch index so
    #    the caller's worktree and index are untouched.
    fd, idx = tempfile.mkstemp(prefix="recovery-idx-")
    os.close(fd)
    os.unlink(idx)  # git wants to create it itself
    env = dict(os.environ, GIT_INDEX_FILE=idx)
    try:
        if _run(["git", "read-tree", base], cwd, env=env).returncode != 0:
            # Cannot even materialise the base tree; refuse to guess.
            return VERDICT_CONFLICTED

        proc = _run(["git", "apply", "--cached", "--3way", "-"], cwd, env=env,
                    stdin=diff_text)

        # Unmerged entries in the scratch index are the ground truth for
        # "this conflicts". Git's exit code is not.
        unmerged = _run(["git", "ls-files", "-u"], cwd, env=env).stdout.strip()
        if unmerged:
            return VERDICT_CONFLICTED

        # Belt and braces: git announces conflicts on stderr even when it
        # exits 0, and a failed apply with an empty index must not read as clean.
        if "with conflicts" in (proc.stderr or ""):
            return VERDICT_CONFLICTED
        if proc.returncode != 0:
            return VERDICT_CONFLICTED

        return VERDICT_THREE_WAY
    finally:
        try:
            os.unlink(idx)
        except OSError:
            pass


def is_landable(diff_text: str, base: str = "HEAD", cwd: str = ".") -> bool:
    """True when the diff can be landed without hand-resolving conflicts."""
    return apply_verdict(diff_text, base, cwd) in LANDABLE


def deletes_live_paths(diff_text: str, base: str, cwd: str = ".") -> "list[str]":
    """Paths this diff DELETES that still exist on `base`.

    A stale branch can delete a module the default branch still ships and still
    "apply". Landing it would be a silent revert, not a recovery, so callers
    treat a non-empty result as a reason to downgrade RECOVERABLE_VALUE.
    """
    deleted: list[str] = []
    path = None
    for line in diff_text.splitlines():
        if line.startswith("diff --git ") and " b/" in line:
            path = line.split(" b/", 1)[1].strip()
        elif line.startswith("deleted file mode") and path:
            deleted.append(path)
    live = []
    for p in deleted:
        if _run(["git", "cat-file", "-e", f"{base}:{p}"], cwd).returncode == 0:
            live.append(p)
    return live
