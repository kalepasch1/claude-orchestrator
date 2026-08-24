#!/usr/bin/env python3
"""One actionable message for "we redid this N times and it still conflicts".

WHY THIS MODULE EXISTS
----------------------
Two places give up on a conflicting branch, and they gave up differently:

    merge_train.py    "train: still conflicts after 2 redos - needs manual rebase.
                       Conflicting files: runner/config_consumer.py."
    approval_merge.py "merge-handler: CONFLICT after 2 redo attempts — needs manual rebase"

Neither told the operator what to actually run, and the approval_merge path did not
even name the file. "needs manual rebase" is advice, not an instruction — the operator
still has to find the repo, work out which base, and reconstruct the command, at which
point the branch usually just sits there. `runner/config_consumer.py` sat in exactly
that state through six remediations.

`note()` builds the terminal note both call sites now use, and it always carries the
three things a human needs to act:

  1. how many redos were burned (and the cap, so "raise the cap" is visibly not the fix)
  2. the exact conflicting file(s)
  3. a copy-pasteable rebase command

Fail-soft throughout: every function returns a usable string on garbage input rather
than raising. This runs on the terminal path of the merge train — an exception here
would replace a diagnosable conflict with a traceback.
"""

from __future__ import annotations

import os
import subprocess
from typing import Iterable, List, Optional, Sequence

__all__ = ["NOTE_MAX_CHARS", "unmerged_files", "manual_rebase_hint", "note"]

#: Notes are stored in a bounded column; callers used to truncate ad hoc at 480.
NOTE_MAX_CHARS = 480

#: Files listed inline before the message switches to "... and N more".
MAX_LISTED_FILES = 6


def _as_file_list(files) -> List[str]:
    """Normalise a newline string / iterable / None into a clean list of paths."""
    if not files:
        return []
    try:
        if isinstance(files, str):
            candidates: Iterable = files.replace(",", "\n").split("\n")
        else:
            candidates = files
        seen: List[str] = []
        for item in candidates:
            text = str(item).strip()
            if text and text not in seen:
                seen.append(text)
        return seen
    except Exception:
        return []


def unmerged_files(repo: str, cwd: Optional[str] = None) -> List[str]:
    """Files git currently reports as unmerged in ``cwd`` (default ``repo``).

    Must be called BEFORE `git rebase --abort`; afterwards the index is clean and
    there is nothing left to name. Returns [] on any error.
    """
    target = cwd or repo
    if not target or not os.path.isdir(target):
        return []
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=U"],
            cwd=target, capture_output=True, text=True, errors="replace", timeout=30,
        )
    except Exception:
        return []
    if result.returncode != 0:
        return []
    return _as_file_list(result.stdout)


def manual_rebase_hint(repo: str, branch: str, base: str) -> str:
    """The command an operator can paste to take the conflict over by hand."""
    try:
        location = repo if repo else "<repo>"
        return (f"To finish it by hand: git -C {location} rebase {base or '<base>'} "
                f"{branch or '<branch>'}")
    except Exception:
        return "To finish it by hand: git rebase <base> <branch>"


def _files_clause(files: Sequence[str]) -> str:
    if not files:
        return " Conflicting files: unavailable (index was reset before capture)."
    shown = list(files[:MAX_LISTED_FILES])
    clause = " Conflicting files: " + ", ".join(shown)
    remaining = len(files) - len(shown)
    if remaining > 0:
        clause += f", and {remaining} more"
    return clause + "."


def note(prefix: str, redos: int, cap: int, branch: str, base: str,
         repo: str = "", files=None) -> str:
    """Build the terminal conflict note.

    ``prefix`` keeps each caller's existing leading text (``"train"`` /
    ``"merge-handler"``) so log greps and dashboards that match on it keep working —
    this adds detail, it does not rename the event.
    """
    try:
        redo_count = int(redos)
    except Exception:
        redo_count = 0
    try:
        redo_cap = int(cap)
    except Exception:
        redo_cap = redo_count

    parts = [
        f"{prefix or 'merge'}: still conflicts after {redo_count} of {redo_cap} redos "
        f"- needs manual rebase.",
        _files_clause(_as_file_list(files)),
        f" Rebuilding on fresh {base or '<base>'} did not clear it, so raising the redo "
        f"cap will not either.",
        " " + manual_rebase_hint(repo, branch, base),
    ]
    return "".join(parts)[:NOTE_MAX_CHARS]
