#!/usr/bin/env python3
"""Reconcile orch-rescue / stash evidence refs against current branch history.

Every rescue ref is treated as READ-ONLY. Nothing is deleted, reset, cleaned,
popped or moved. The script only reads git objects and emits a classification
ledger.

Classification vocabulary (matches the orchestrator recovery-ledger contract):

  ALREADY_PRESENT            content is reachable from, or patch-identical to,
                             something already in the base branch
  SUPERSEDED_BY_NEWER        every file the ref touches has been modified in the
                             base branch *after* the ref was created
  ACTIVE_IN_ANOTHER_TASK     the ref's commit is contained in a live agent/*
                             branch, so another task already owns it
  RECOVERABLE_VALUE          not present anywhere and its diff still applies
  CONFLICTED_NEEDS_FOCUSED_TASK
                             not present anywhere and its diff no longer applies

Usage:
    python3 tools/reconcile_rescue_refs.py --base origin/main \
        --newest master \
        --fingerprint <audit-sha> --out .orch/recovery-ledger.json

Pass --newest whenever the merge train is holding unpushed commits, which is
most of the time. Without it the scan can only see decisions that have already
reached --base, and a ref that applies cleanly *because* the base still holds a
file a newer commit deleted gets recovered by undoing that deletion. See
`deletion_supersedes` for the run where that was 39% of the recoverable set.
"""

from __future__ import annotations

import argparse
import functools
import json
import os
import subprocess
import sys
from dataclasses import dataclass, asdict, field

# Strict apply verdict lives in one module so every reconciler agrees on what
# "still applies" means. See tools/recovery_apply_check.py for why
# `git apply --check --3way` is not a usable answer.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from recovery_apply_check import apply_verdict, deletes_live_paths, LANDABLE  # noqa: E402


RESCUE_NAMESPACES = ("refs/orch-rescue/", "refs/stash", "refs/orch-evidence/")


def git(*args: str, check: bool = True) -> str:
    proc = subprocess.run(
        ("git",) + args, capture_output=True, text=True, errors="replace"
    )
    if check and proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout


def git_ok(*args: str) -> bool:
    return subprocess.run(
        ("git",) + args, capture_output=True, text=True
    ).returncode == 0


@dataclass
class Item:
    ref: str
    sha: str
    subject: str
    created_at: int
    classification: str = "UNKNOWN"
    disposition: str = ""
    files: list = field(default_factory=list)
    evidence: str = ""


def enumerate_refs() -> "list[Item]":
    """Enumerate every rescue ref. The source is never mutated."""
    fmt = "%(refname)%09%(objectname)%09%(creatordate:unix)%09%(contents:subject)"
    items = []
    for ns in RESCUE_NAMESPACES:
        out = git("for-each-ref", "--format=" + fmt, ns + "*", check=False)
        for line in out.splitlines():
            parts = line.split("\t")
            if len(parts) < 4:
                continue
            ref, sha, created, subject = parts[0], parts[1], parts[2], parts[3]
            items.append(
                Item(
                    ref=ref,
                    sha=sha,
                    subject=subject,
                    created_at=int(created) if created.isdigit() else 0,
                )
            )
    return items


def _patch_id_of(diff_text: str) -> "str | None":
    if not diff_text.strip():
        return None
    out = subprocess.run(
        ["git", "patch-id", "--stable"],
        input=diff_text,
        capture_output=True,
        text=True,
        errors="replace",
    ).stdout
    return out.split()[0] if out.strip() else None


def base_patch_ids(base: str, depth: int) -> "set[str]":
    """Stable patch-ids for the last `depth` commits of the base branch."""
    shas = git(
        "log", "--no-merges", "--pretty=format:%H", "-n", str(depth), base,
        check=False,
    ).split()
    ids = set()
    for start in range(0, len(shas), 150):
        chunk = shas[start : start + 150]
        diff = subprocess.run(
            ["git", "show", "--no-color", "--patch", "--first-parent"] + chunk,
            capture_output=True,
            text=True,
            errors="replace",
        ).stdout
        out = subprocess.run(
            ["git", "patch-id", "--stable"],
            input=diff,
            capture_output=True,
            text=True,
            errors="replace",
        ).stdout
        for line in out.splitlines():
            if line.strip():
                ids.add(line.split()[0])
    return ids


def ref_diff(sha: str) -> str:
    return subprocess.run(
        ["git", "show", "--no-color", "--patch", "--first-parent", sha],
        capture_output=True,
        text=True,
        errors="replace",
    ).stdout


def changed_files(sha: str) -> "list[str]":
    out = git(
        "show", "--pretty=format:", "--name-only", "--first-parent", sha,
        check=False,
    )
    return [f for f in out.splitlines() if f.strip()]


def newest_touch(base: str, path: str) -> int:
    out = git("log", "-1", "--format=%ct", base, "--", path, check=False).strip()
    return int(out) if out.isdigit() else 0


@functools.lru_cache(maxsize=None)
def path_in_tree(ref: str, path: str) -> bool:
    """Whether `path` exists in `ref`'s tree. Cached: the answer cannot change mid-run."""
    return bool(git("ls-tree", "-r", "--name-only", ref, "--", path, check=False).strip())


@functools.lru_cache(maxsize=None)
def deleting_commit(ref: str, path: str) -> str:
    """The most recent commit on `ref` that DELETED `path`, as `sha date subject`."""
    return git(
        "log", "-1", "--format=%h %ad %s", "--date=short", "--diff-filter=D",
        ref, "--", path, check=False,
    ).strip()


def deletion_supersedes(files, present_in_base, present_in_newest) -> bool:
    """True when every touched path is still in the base but GONE from the newer lineage.

    WHY THIS IS NOT COVERED BY `newest_touch`.
    Step 5 asks whether the base has rewritten every touched path since the ref was
    cut. It cannot see a decision that has not reached the base yet — and the base is
    usually behind, because the merge train holds unpushed commits for hours at a
    time. A ref then "applies cleanly" for the worst possible reason: the base still
    contains the very files a newer commit deleted on purpose.

    That is not hypothetical. Reconciling beethoven under fingerprint 169a0a07fa18,
    59 of 151 RECOVERABLE_VALUE verdicts — 39% — were refs touching only
    web/types/log.js and web/utils/cookie-compat.js. Both were removed by d63e93da1
    ("finish fbd49cff8: drop the last 2 compiled .js files shadowing their .ts
    sources") the day before the scan. d63e93da1 is on local master and on
    orchestrator/dev; it had not reached origin/master, which was the scan base.
    Recovering those 59 would have re-added compiled .js files shadowing their
    TypeScript sources — reintroducing the exact bug fbd49cff8 was written to fix.

    Pure and injectable so the rule can be tested without a git fixture: the two
    predicates are the only things that touch the repository.
    """
    files = list(files or [])
    if not files:
        return False
    return all(present_in_base(f) and not present_in_newest(f) for f in files)


def agent_branches_containing(sha: str) -> "list[str]":
    out = git(
        "branch", "-r", "--contains", sha, "--list", "origin/agent/*", check=False
    )
    return [b.strip() for b in out.splitlines() if b.strip()]


def diff_applies(diff_text: str, base: str = "HEAD", cwd: str = ".") -> bool:
    """True only when the diff lands WITHOUT conflicts (see recovery_apply_check)."""
    return apply_verdict(diff_text, base, cwd) in LANDABLE


def classify(item: Item, base: str, known_patch_ids: "set[str]", newest: str = "") -> None:
    # 1. Reachable from base -> already merged.
    if git_ok("merge-base", "--is-ancestor", item.sha, base):
        item.classification = "ALREADY_PRESENT"
        item.disposition = "reachable from " + base + "; no action"
        item.evidence = "merge-base --is-ancestor"
        return

    item.files = changed_files(item.sha)
    diff_text = ref_diff(item.sha)

    # 2. Patch-identical to something already in base.
    pid = _patch_id_of(diff_text)
    if pid and pid in known_patch_ids:
        item.classification = "ALREADY_PRESENT"
        item.disposition = "patch-id " + pid[:12] + " already in " + base
        item.evidence = "patch-id=" + pid
        return

    # 3. Empty sweep commits carry no recoverable content.
    if not item.files:
        item.classification = "ALREADY_PRESENT"
        item.disposition = "no file changes relative to first parent; no action"
        item.evidence = "empty diff"
        return

    # 4. Owned by a live agent branch.
    owners = agent_branches_containing(item.sha)
    if owners:
        item.classification = "ACTIVE_IN_ANOTHER_TASK"
        item.disposition = "contained in " + owners[0] + "; leave to that task"
        item.evidence = ",".join(owners[:5])
        return

    # 5. Every touched file rewritten in base after the ref was cut.
    if item.created_at and all(
        newest_touch(base, f) > item.created_at for f in item.files
    ):
        item.classification = "SUPERSEDED_BY_NEWER"
        item.disposition = (
            "all %d touched file(s) modified in %s after ref creation; "
            "newest implementation wins" % (len(item.files), base)
        )
        item.evidence = "base newer on every touched path"
        return

    # 5b. Every touched file was DELETED on a newer lineage the base has not caught
    #     up to. See deletion_supersedes: the base is usually behind the merge train,
    #     and a ref that applies cleanly only because the base still holds files a
    #     newer commit deliberately removed is the most dangerous false positive this
    #     tool can produce — it recovers by undoing.
    if newest and deletion_supersedes(
        item.files,
        lambda f: path_in_tree(base, f),
        lambda f: path_in_tree(newest, f),
    ):
        who = deleting_commit(newest, item.files[0])
        item.classification = "SUPERSEDED_BY_NEWER"
        item.disposition = (
            "all %d touched file(s) deleted on %s, which %s has not caught up to; "
            "recovering would undo that deletion" % (len(item.files), newest, base)
        )
        item.evidence = "deleted on %s by %s" % (newest, who or "an unnamed commit")
        return

    # 6. Still has value. Does it still apply?
    if diff_applies(diff_text, base):
        item.classification = "RECOVERABLE_VALUE"
        item.disposition = (
            "diff applies cleanly to base; recover via isolated worktree + "
            "agent branch through the merge train"
        )
        item.evidence = "git apply --check --3way clean"
    else:
        item.classification = "CONFLICTED_NEEDS_FOCUSED_TASK"
        item.disposition = (
            "diff no longer applies; queue a focused follow-up rather than "
            "forcing an overwrite"
        )
        item.evidence = "git apply --check --3way rejected"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="origin/main")
    ap.add_argument("--fingerprint", required=True)
    ap.add_argument("--out", default=".orch/recovery-ledger.json")
    ap.add_argument("--depth", type=int, default=1500,
                    help="how many base commits to fingerprint for patch-id match")
    ap.add_argument("--limit", type=int, default=0, help="0 = all refs")
    ap.add_argument("--newest", default="",
                    help="a ref AHEAD of --base (the local integration tip, e.g. "
                         "master or orchestrator/dev). Used to catch refs that only "
                         "apply because the base has not received a deletion yet. "
                         "Empty disables the check; supply it whenever the merge "
                         "train is holding unpushed commits, which is most of the time.")
    args = ap.parse_args()

    items = enumerate_refs()
    if args.limit:
        items = items[: args.limit]
    if not items:
        print("no rescue refs found", file=sys.stderr)

    known = base_patch_ids(args.base, args.depth) if items else set()

    for it in items:
        try:
            classify(it, args.base, known, args.newest)
        except Exception as exc:  # never leave an item UNKNOWN silently
            it.classification = "CONFLICTED_NEEDS_FOCUSED_TASK"
            it.disposition = "classification error, needs focused task: %s" % exc
            it.evidence = "exception"

    counts = {}
    for it in items:
        counts[it.classification] = counts.get(it.classification, 0) + 1

    ledger = {
        "audit_fingerprint": args.fingerprint,
        "base": args.base,
        "total": len(items),
        "counts": counts,
        "unknown": counts.get("UNKNOWN", 0),
        "items": [asdict(it) for it in items],
    }

    out_dir = os.path.dirname(args.out)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(args.out, "w") as fh:
        json.dump(ledger, fh, indent=2, sort_keys=True)

    print(json.dumps({"total": len(items), "counts": counts}, indent=2))
    return 1 if counts.get("UNKNOWN") else 0


if __name__ == "__main__":
    raise SystemExit(main())
