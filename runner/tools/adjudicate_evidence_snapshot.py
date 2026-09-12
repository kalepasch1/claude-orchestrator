#!/usr/bin/env python3
"""Adjudicate a preserved evidence snapshot commit against the default branch.

Abandoned agent worktrees are swept into a commit before the directory goes
away. Later a focused task is queued to decide what, if anything, in that
snapshot is still worth recovering. Doing that by hand is where the expensive
mistake lives: a worktree left mid-merge (git status UU) looks like lost work,
so someone replays it, and reverts whatever the default branch fixed in the
meantime.

The decision is almost always mechanical, because a snapshot is a *point in
time*. Per file there are only three interesting answers:

    IDENTICAL            snapshot blob == base blob; the conflict was already
                         settled in the base's favour before the sweep
    SUPERSEDED_BY_NEWER  base strictly extends the snapshot — every line the
                         snapshot would restore is a line the base added later
    DIVERGED             both sides changed; genuine per-hunk review, and the
                         only case a human needs to look at

"Strictly extends" is decided by diff direction, not by timestamps: a snapshot
whose diff to base is pure-addition contributes nothing the base lacks.

Read-only. Never deletes, resets, cleans, pops or moves anything.
"""

import argparse
import json
import os
import subprocess
import sys
from collections import Counter
from typing import Dict, List, Optional, Sequence

DEFAULT_BASE = "origin/master"

EVIDENCE_ABSENT = "EVIDENCE_ABSENT"
IDENTICAL = "IDENTICAL"
SUPERSEDED_BY_NEWER = "SUPERSEDED_BY_NEWER"
DIVERGED = "DIVERGED"

CONFLICT_MARKERS = ("<<<<<<< ", ">>>>>>> ")

# Per-invocation bound on any git call. A packed-refs walk on a repo with a
# large rescue namespace can hang; this adjudicator must never be the thing
# that outlives its lease.
GIT_TIMEOUT_S = int(os.environ.get("ORCH_ADJUDICATE_GIT_TIMEOUT_S", "120"))


def _git(args: Sequence[str], repo: str) -> str:
    """Run git read-only and return stdout, or '' on any failure.

    Fail-soft: a missing rev or a corrupt object degrades to "no information",
    it does not raise into a caller that is mid-adjudication.
    """
    try:
        out = subprocess.run(
            ["git", "-C", repo] + list(args),
            capture_output=True,
            text=True,
            check=False,
            timeout=GIT_TIMEOUT_S,
        )
    except Exception as exc:  # noqa: BLE001 - fail-soft, but never silent
        print(f"adjudicate-snapshot: git {list(args)[:2]} failed: {exc}", file=sys.stderr)
        return ""
    return out.stdout.strip() if out.returncode == 0 else ""


def blob_at(repo: str, rev: str, path: str) -> str:
    """Blob sha of `path` at `rev`, or '' when absent there."""
    return _git(["rev-parse", f"{rev}:{path}"], repo)


def numstat(repo: str, old: str, new: str, path: str) -> tuple:
    """(added, deleted) going from `old` to `new` for one path; (0, 0) on failure."""
    fields = _git(["diff", "--numstat", old, new, "--", path], repo).split()
    if len(fields) < 2:
        return (0, 0)
    try:
        return (int(fields[0]), int(fields[1]))
    except ValueError:
        # Binary files report "-\t-". Treat as diverged-but-unmeasurable.
        return (-1, -1)


def has_conflict_markers(repo: str, rev: str, path: str) -> bool:
    """True when the snapshot blob still carries unresolved merge markers."""
    content = _git(["show", f"{rev}:{path}"], repo)
    return any(marker in content for marker in CONFLICT_MARKERS)


def adjudicate_path(repo: str, snapshot: str, base: str, path: str) -> Dict[str, object]:
    """Decide one path. Never raises."""
    snap_blob = blob_at(repo, snapshot, path)
    if not snap_blob:
        return {
            "path": path,
            "verdict": EVIDENCE_ABSENT,
            "disposition": "path not present in the preserved snapshot",
        }

    base_blob = blob_at(repo, base, path)
    entry = {"path": path, "snapshot_blob": snap_blob, "base_blob": base_blob}

    if snap_blob == base_blob:
        entry["verdict"] = IDENTICAL
        entry["disposition"] = "snapshot blob equals base blob; nothing was lost"
        return entry

    added, deleted = numstat(repo, snapshot, base, path)
    entry["snapshot_to_base"] = {"added": added, "deleted": deleted}
    entry["conflict_markers"] = has_conflict_markers(repo, snapshot, path)

    if added >= 0 and deleted == 0:
        entry["verdict"] = SUPERSEDED_BY_NEWER
        entry["disposition"] = (
            f"base strictly extends the snapshot (+{added}/-0); every line the "
            f"snapshot would restore is a line the base added later"
        )
        return entry

    entry["verdict"] = DIVERGED
    entry["disposition"] = (
        f"both sides changed (+{added}/-{deleted} snapshot->base); needs per-hunk "
        f"review — do not take either side wholesale"
    )
    return entry


def adjudicate(
    repo: str, snapshot: str, base: str, paths: Sequence[str]
) -> Dict[str, object]:
    """Adjudicate every path and roll the verdicts up."""
    items: List[dict] = [adjudicate_path(repo, snapshot, base, p) for p in paths]
    counts = dict(Counter(item["verdict"] for item in items))
    needs_human = [i["path"] for i in items if i["verdict"] == DIVERGED]
    return {
        "snapshot": snapshot,
        "snapshot_sha": _git(["rev-parse", snapshot], repo),
        "base": base,
        "base_sha": _git(["rev-parse", base], repo),
        "items": items,
        "counts": counts,
        "needs_human_review": needs_human,
        "nothing_recoverable": not needs_human,
    }


def changed_paths(repo: str, snapshot: str, base: str) -> List[str]:
    """Every path differing between the snapshot and the base."""
    out = _git(["diff", "--name-only", snapshot, base], repo)
    return [line for line in out.splitlines() if line]


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".")
    parser.add_argument("--snapshot", required=True, help="preserved snapshot commit")
    parser.add_argument("--base", default=DEFAULT_BASE)
    parser.add_argument(
        "--path",
        action="append",
        default=[],
        help="path to adjudicate; repeatable. Omit to adjudicate every differing path.",
    )
    parser.add_argument("--out", default="", help="write the verdict ledger here")
    args = parser.parse_args(argv)

    paths = args.path or changed_paths(args.repo, args.snapshot, args.base)
    if not paths:
        print("adjudicate-snapshot: snapshot does not differ from base", file=sys.stderr)
        return 0

    report = adjudicate(args.repo, args.snapshot, args.base, paths)

    if args.out:
        try:
            with open(args.out, "w", encoding="utf-8") as handle:
                json.dump(report, handle, indent=2, sort_keys=True)
        except Exception as exc:  # noqa: BLE001 - fail-soft, but never silent
            print(f"adjudicate-snapshot: could not write report: {exc}", file=sys.stderr)

    print(json.dumps({"counts": report["counts"],
                      "needs_human_review": report["needs_human_review"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
