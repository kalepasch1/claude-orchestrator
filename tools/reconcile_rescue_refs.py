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
        --fingerprint <audit-sha> --out .orch/recovery-ledger.json
"""

from __future__ import annotations

import argparse
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


RESCUE_NAMESPACES = ("refs/orch-rescue/", "refs/orch-evidence/")

# Stashes are deliberately NOT in RESCUE_NAMESPACES, and removing them is a bug
# fix rather than a coverage cut.
#
# A stash commit has up to three parents: ^1 the commit it was taken from, ^2
# the index, ^3 the untracked files stashed with -u/-a. Every probe in this
# module reads a commit with `--first-parent`, which sees only the tracked
# delta -- so a stash carrying untracked files was enumerated here, classified
# with an incomplete file list, and written into the ledger as fully handled.
# Verified on a throwaway repo: a stash of `app.py` (modified) plus
# `brand_new.py` (untracked) reports exactly one path, and a recovery driven
# off that ledger entry loses the new file without anything reporting a gap.
#
# `git for-each-ref refs/stash` also reports only the TIP of the stash stack, so
# a repo with thirteen stashes looked like it had one.
#
# tools/reconcile_stashes.py already owns this evidence class correctly: it
# enumerates the full reflog via `git stash list` and diffs `stash^1..stash`
# including the untracked parent. Two reconcilers claiming the same item with
# different methods produced two contradictory ledger rows for it.
STASH_NAMESPACE = "refs/stash"
STASH_OWNER = "tools/reconcile_stashes.py"


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


def count_stashes() -> int:
    """How many stash entries exist, read from the reflog. Never mutates the stack."""
    out = git("stash", "list", check=False)
    return len([ln for ln in out.splitlines() if ln.strip()])


def stash_deferral() -> "dict | None":
    """Provenance record for stash evidence this reconciler deliberately skips.

    Returns None when there are no stashes. Dropping a namespace silently would
    trade one bug (wrong classification) for a worse one (missing item), so the
    skip is recorded in the ledger and announced on stderr instead.
    """
    count = count_stashes()
    if not count:
        return None
    return {
        "namespace": STASH_NAMESPACE,
        "count": count,
        "owner": STASH_OWNER,
        "reason": (
            "stash commits carry untracked content on their third parent, which "
            "this module's --first-parent probes cannot see; %s enumerates the "
            "full reflog and diffs stash^1..stash including that parent"
            % STASH_OWNER
        ),
    }


def enumerate_refs() -> "list[Item]":
    """Enumerate every rescue ref. The source is never mutated.

    Stash refs are excluded on purpose -- see STASH_NAMESPACE above. Callers
    that need stash coverage run tools/reconcile_stashes.py, and main() records
    the deferral in the ledger so the gap is visible rather than assumed.
    """
    fmt = "%(refname)%09%(objectname)%09%(creatordate:unix)%09%(contents:subject)"
    items = []
    for ns in RESCUE_NAMESPACES:
        out = git("for-each-ref", "--format=" + fmt, ns + "*", check=False)
        for line in out.splitlines():
            parts = line.split("\t")
            if len(parts) < 4:
                continue
            ref, sha, created, subject = parts[0], parts[1], parts[2], parts[3]
            # Belt and braces: a stash must never reach classify() even if the
            # namespace tuple is edited back, because every probe here would
            # under-report its content rather than fail.
            if ref == STASH_NAMESPACE or ref.startswith(STASH_NAMESPACE + "@"):
                continue
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


def agent_branches_containing(sha: str) -> "list[str]":
    out = git(
        "branch", "-r", "--contains", sha, "--list", "origin/agent/*", check=False
    )
    return [b.strip() for b in out.splitlines() if b.strip()]


def diff_applies(diff_text: str, base: str = "HEAD", cwd: str = ".") -> bool:
    """True only when the diff lands WITHOUT conflicts (see recovery_apply_check)."""
    return apply_verdict(diff_text, base, cwd) in LANDABLE


def classify(item: Item, base: str, known_patch_ids: "set[str]") -> None:
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
    args = ap.parse_args()

    items = enumerate_refs()
    if args.limit:
        items = items[: args.limit]
    if not items:
        print("no rescue refs found", file=sys.stderr)

    deferred = stash_deferral()
    if deferred:
        print(
            "NOTE: %d stash entr%s not classified here; run %s for that evidence "
            "class (stash untracked content lives on the third parent and is "
            "invisible to this module's --first-parent probes)."
            % (deferred["count"],
               "y is" if deferred["count"] == 1 else "ies are",
               STASH_OWNER),
            file=sys.stderr,
        )

    known = base_patch_ids(args.base, args.depth) if items else set()

    for it in items:
        try:
            classify(it, args.base, known)
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
        # Evidence this pass deliberately did not classify, and who owns it.
        # Present so a reader can tell "no stashes" from "stashes handled
        # elsewhere" -- an absent key used to mean both.
        "deferred": [deferred] if deferred else [],
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
