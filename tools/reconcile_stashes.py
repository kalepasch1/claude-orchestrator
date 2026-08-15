#!/usr/bin/env python3
"""Reconcile git stash entries against the current default branch.

Stashes are the most easily-lost evidence class on this machine. They are
invisible to `git log`, invisible to the merge train, and a single careless
`git stash pop`/`git stash clear` destroys them. They are also NOT covered by
the rescue-ref reconciler: `git for-each-ref refs/stash` reports only the tip of
the stash reflog, so a repo with N stashes looks like it has exactly one. This
script enumerates the full reflog (`git stash list`) so every entry is seen.

READ-ONLY, and deliberately so: nothing here pops, applies, drops, clears or
otherwise mutates the stash stack. Each entry is inspected via its commit
objects only.

A stash commit has up to three parents:
    ^1  the HEAD it was taken from
    ^2  the index state
    ^3  the untracked files (only when stashed with -u/-a)
The recoverable content is `git diff stash^1 stash`, which is what would land if
the stash were applied.

Classification vocabulary matches tools/reconcile_rescue_refs.py.

Usage:
    python3 tools/reconcile_stashes.py --base origin/master \
        --fingerprint <audit-sha> --out .orch/recovery-ledger-<short>-stashes.json
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass, field

# Strict apply verdict lives in one module so every reconciler agrees on what
# "still applies" means. See tools/recovery_apply_check.py for why
# `git apply --check --3way` is not a usable answer.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from recovery_apply_check import apply_verdict, LANDABLE  # noqa: E402


GENERATED_HINTS = (
    "/node_modules/", "/__pycache__/", ".pyc", "/dist/", "/.next/", "/.nuxt/",
    "/build/", "package-lock.json", "pnpm-lock.yaml", "/.DS_Store",
)


def git(*args: str, check: bool = False) -> str:
    proc = subprocess.run(
        ("git",) + args, capture_output=True, text=True, errors="replace"
    )
    if check and proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {proc.stderr.strip()}")
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
    kind: str = "stashes"
    classification: str = "UNKNOWN"
    disposition: str = ""
    files: list = field(default_factory=list)
    evidence: str = ""
    branch_of_origin: str = ""
    has_untracked: bool = False


def enumerate_stashes() -> "list[Item]":
    """Every entry in the stash reflog. The stack is never mutated."""
    # NOTE: use --pretty=format: with %x09, not --format= with a literal %09.
    # The latter is accepted by git but leaves "%09" unexpanded, so the split
    # below finds no tabs and the repo silently looks stash-free.
    fmt = "%gd%x09%H%x09%ct%x09%gs"
    out = git("stash", "list", "--pretty=format:" + fmt)
    items: list[Item] = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) < 4:
            continue
        ref, sha, created, subject = parts[0], parts[1], parts[2], parts[3]
        it = Item(
            ref=ref,
            sha=sha,
            subject=subject,
            created_at=int(created) if created.isdigit() else 0,
        )
        # "WIP on <branch>: ..." / "On <branch>: ..."
        for marker in (" on ", "On "):
            if marker in subject:
                tail = subject.split(marker, 1)[1]
                it.branch_of_origin = tail.split(":", 1)[0].strip()
                break
        it.has_untracked = bool(git("rev-parse", "--verify", "--quiet",
                                    sha + "^3").strip())
        items.append(it)

    # Fail loud on a parse mismatch. A stash reconciler that reports "no
    # stashes" because its format string broke is worse than one that errors:
    # the caller would record the repo as clean and the evidence would be lost.
    raw = [ln for ln in git("stash", "list").splitlines() if ln.strip()]
    if len(items) != len(raw):
        raise RuntimeError(
            "stash enumeration mismatch: parsed %d entries but `git stash list` "
            "reports %d; refusing to report incomplete evidence"
            % (len(items), len(raw))
        )
    return items


def stash_diff(sha: str) -> str:
    return subprocess.run(
        ["git", "diff", "--no-color", sha + "^1", sha],
        capture_output=True, text=True, errors="replace",
    ).stdout


def changed_files(sha: str) -> "list[str]":
    out = git("diff", "--name-only", sha + "^1", sha)
    return [f for f in out.splitlines() if f.strip()]


def untracked_files(sha: str) -> "list[str]":
    out = git("show", "--pretty=format:", "--name-only", sha + "^3")
    return [f for f in out.splitlines() if f.strip()]


def patch_id_of(diff_text: str) -> "str | None":
    if not diff_text.strip():
        return None
    out = subprocess.run(
        ["git", "patch-id", "--stable"],
        input=diff_text, capture_output=True, text=True, errors="replace",
    ).stdout
    return out.split()[0] if out.strip() else None


def base_patch_ids(base: str, depth: int) -> "set[str]":
    shas = git("log", "--no-merges", "--pretty=format:%H", "-n", str(depth),
               base).split()
    ids: set[str] = set()
    for start in range(0, len(shas), 150):
        diff = subprocess.run(
            ["git", "show", "--no-color", "--patch", "--first-parent"]
            + shas[start : start + 150],
            capture_output=True, text=True, errors="replace",
        ).stdout
        out = subprocess.run(
            ["git", "patch-id", "--stable"],
            input=diff, capture_output=True, text=True, errors="replace",
        ).stdout
        for line in out.splitlines():
            if line.strip():
                ids.add(line.split()[0])
    return ids


def newest_touch(base: str, path: str) -> int:
    out = git("log", "-1", "--format=%ct", base, "--", path).strip()
    return int(out) if out.isdigit() else 0


def is_generated(path: str) -> bool:
    p = "/" + path.replace(os.sep, "/")
    return any(h in p for h in GENERATED_HINTS)


def diff_applies(diff_text: str, base: str = "HEAD", cwd: str = ".") -> bool:
    """True only when the diff lands WITHOUT conflicts (see recovery_apply_check)."""
    return apply_verdict(diff_text, base, cwd) in LANDABLE


def classify(item: Item, base: str, known: "set[str]") -> None:
    tracked = changed_files(item.sha)
    untracked = untracked_files(item.sha) if item.has_untracked else []
    item.files = sorted(set(tracked + untracked))
    diff_text = stash_diff(item.sha)

    if not item.files:
        item.classification = "ALREADY_PRESENT"
        item.disposition = "stash carries no file changes; nothing to recover"
        item.evidence = "empty stash diff"
        return

    real = [f for f in item.files if not is_generated(f)]
    if not real:
        item.classification = "ALREADY_PRESENT"
        item.disposition = (
            f"all {len(item.files)} stashed path(s) are generated/vendored "
            "(lockfiles, node_modules, build output); nothing to recover"
        )
        item.evidence = "generated-only stash"
        return

    pid = patch_id_of(diff_text)
    if pid and pid in known:
        item.classification = "ALREADY_PRESENT"
        item.disposition = f"patch-id {pid[:12]} already in {base}"
        item.evidence = "patch-id=" + pid
        return

    # The commit the stash was taken from can itself already be merged while the
    # stashed delta is not -- so being an ancestor is NOT sufficient on its own.
    parent_merged = git_ok("merge-base", "--is-ancestor", item.sha + "^1", base)

    tracked_real = [f for f in tracked if not is_generated(f)]
    if (tracked_real and not untracked and item.created_at
            and all(newest_touch(base, f) > item.created_at
                    for f in tracked_real)):
        item.classification = "SUPERSEDED_BY_NEWER"
        item.disposition = (
            f"all {len(tracked_real)} stashed path(s) rewritten in {base} after "
            "the stash was taken; newest implementation wins"
        )
        item.evidence = "base newer on every stashed path"
        return

    if diff_applies(diff_text, base):
        item.classification = "RECOVERABLE_VALUE"
        item.disposition = (
            f"stash of {len(real)} path(s)"
            + (f" (+{len(untracked)} untracked)" if untracked else "")
            + " applies cleanly to base"
            + ("; its base commit is already merged, so only the stashed delta "
               "is missing" if parent_merged else "")
            + ". Recover with `git stash show -p` into a NEW isolated worktree "
              "-- do NOT pop or apply in place."
        )
        item.evidence = "git apply --check --3way clean"
    else:
        item.classification = "CONFLICTED_NEEDS_FOCUSED_TASK"
        item.disposition = (
            "stashed diff no longer applies to base; queue a focused follow-up "
            "rather than forcing an overwrite. Do NOT pop the stash."
        )
        item.evidence = "git apply --check --3way rejected"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="origin/master")
    ap.add_argument("--fingerprint", required=True)
    ap.add_argument("--out", default=".orch/recovery-ledger-stashes.json")
    ap.add_argument("--depth", type=int, default=1200)
    args = ap.parse_args()

    items = enumerate_stashes()
    known = base_patch_ids(args.base, args.depth) if items else set()

    for it in items:
        try:
            classify(it, args.base, known)
        except Exception as exc:  # never leave an item UNKNOWN silently
            it.classification = "CONFLICTED_NEEDS_FOCUSED_TASK"
            it.disposition = "classification error, needs focused task: %s" % exc
            it.evidence = "exception"

    counts: dict = {}
    for it in items:
        counts[it.classification] = counts.get(it.classification, 0) + 1

    ledger = {
        "audit_fingerprint": args.fingerprint,
        "base": args.base,
        "evidence_kind": "stashes",
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
