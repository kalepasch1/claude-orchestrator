#!/usr/bin/env python3
"""Reconcile local-only branch tips against the current default branch.

A "local-only branch tip" is a ref under refs/heads/ that has no counterpart
under refs/remotes/origin/. Those tips are the usual residue of ChatGPT/Codex
sessions and crashed agent runs: the work exists on this machine only, so it is
invisible to the merge train and to every other executor.

This script is READ-ONLY with respect to the evidence. No branch is deleted,
force-updated, rebased, checked out or merged here; it classifies and reports so
the merge train and focused follow-up tasks can act with provenance.

Classification vocabulary matches tools/reconcile_rescue_refs.py:

  ALREADY_PRESENT            tip is reachable from base, or its range-diff is
                             patch-identical to something already in base
  SUPERSEDED_BY_NEWER        every file the branch touches was modified in base
                             *after* the branch tip was authored
  ACTIVE_IN_ANOTHER_TASK     the tip is contained in a published remote branch,
                             so the merge train already owns it
  RECOVERABLE_VALUE          not present anywhere and its diff still applies
  CONFLICTED_NEEDS_FOCUSED_TASK
                             not present anywhere and its diff no longer applies

Unlike a rescue ref (a single commit), a branch tip is reconciled over its whole
range: merge-base(base, tip)..tip. That is what the merge train would actually
have to take, so it is what gets classified.

Usage:
    python3 tools/reconcile_local_branches.py --base origin/master \
        --fingerprint <audit-sha> --out .orch/recovery-ledger-<short>-local.json
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from dataclasses import asdict, dataclass, field

# Branches that are never "local-only evidence": the checked-out base itself and
# scratch refs the tooling creates. Reconciling them would be self-referential.
SKIP_PREFIXES = ("worktree-agent-",)
SKIP_EXACT = {"master", "main", "dev", "orchestrator/dev", "_rb"}


def git(*args: str, check: bool = False) -> str:
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
    ahead: int = 0


def remote_branch_names() -> "set[str]":
    out = git("for-each-ref", "--format=%(refname:short)", "refs/remotes/origin/")
    names = set()
    for line in out.splitlines():
        line = line.strip()
        if not line or line.endswith("/HEAD"):
            continue
        names.add(line.split("origin/", 1)[-1])
    return names


def enumerate_local_only(exclude_self: str = "") -> "list[Item]":
    """Every refs/heads/ tip with no origin/ counterpart. Source is never mutated."""
    published = remote_branch_names()
    fmt = "%(refname:short)%09%(objectname)%09%(creatordate:unix)%09%(contents:subject)"
    items: list[Item] = []
    for line in git("for-each-ref", "--format=" + fmt, "refs/heads/").splitlines():
        parts = line.split("\t")
        if len(parts) < 4:
            continue
        name, sha, created, subject = parts[0], parts[1], parts[2], parts[3]
        if name in published or name in SKIP_EXACT or name == exclude_self:
            continue
        if any(name.startswith(p) for p in SKIP_PREFIXES):
            continue
        items.append(
            Item(
                ref="refs/heads/" + name,
                sha=sha,
                subject=subject,
                created_at=int(created) if created.isdigit() else 0,
            )
        )
    return items


def range_diff(base: str, sha: str) -> str:
    mb = git("merge-base", base, sha).strip()
    if not mb:
        return ""
    return subprocess.run(
        ["git", "diff", "--no-color", mb, sha],
        capture_output=True, text=True, errors="replace",
    ).stdout


def patch_id_of(diff_text: str) -> "str | None":
    if not diff_text.strip():
        return None
    out = subprocess.run(
        ["git", "patch-id", "--stable"],
        input=diff_text, capture_output=True, text=True, errors="replace",
    ).stdout
    return out.split()[0] if out.strip() else None


def base_patch_ids(base: str, depth: int) -> "set[str]":
    shas = git(
        "log", "--no-merges", "--pretty=format:%H", "-n", str(depth), base
    ).split()
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


def changed_files(base: str, sha: str) -> "list[str]":
    mb = git("merge-base", base, sha).strip()
    if not mb:
        return []
    out = git("diff", "--name-only", mb, sha)
    return [f for f in out.splitlines() if f.strip()]


def newest_touch(base: str, path: str) -> int:
    out = git("log", "-1", "--format=%ct", base, "--", path).strip()
    return int(out) if out.isdigit() else 0


def remote_branches_containing(sha: str) -> "list[str]":
    out = git("branch", "-r", "--contains", sha)
    return [
        b.strip() for b in out.splitlines()
        if b.strip() and "->" not in b
    ]


def diff_applies(diff_text: str) -> bool:
    if not diff_text.strip():
        return False
    return subprocess.run(
        ["git", "apply", "--check", "--3way", "-"],
        input=diff_text, capture_output=True, text=True,
    ).returncode == 0


def classify(item: Item, base: str, known_patch_ids: "set[str]") -> None:
    # 1. Already merged into the default branch.
    if git_ok("merge-base", "--is-ancestor", item.sha, base):
        item.classification = "ALREADY_PRESENT"
        item.disposition = f"tip reachable from {base}; no action"
        item.evidence = "merge-base --is-ancestor"
        return

    ahead = git("rev-list", "--count", f"{base}..{item.sha}").strip()
    item.ahead = int(ahead) if ahead.isdigit() else 0
    item.files = changed_files(base, item.sha)
    diff_text = range_diff(base, item.sha)

    # 2. Range is patch-identical to work already in base.
    pid = patch_id_of(diff_text)
    if pid and pid in known_patch_ids:
        item.classification = "ALREADY_PRESENT"
        item.disposition = f"patch-id {pid[:12]} already in {base}"
        item.evidence = "patch-id=" + pid
        return

    # 3. No net change against base.
    if not item.files:
        item.classification = "ALREADY_PRESENT"
        item.disposition = "no net file changes against base; no action"
        item.evidence = "empty range diff"
        return

    # 4. Published remote branch already carries the tip -> merge train owns it.
    owners = remote_branches_containing(item.sha)
    if owners:
        item.classification = "ACTIVE_IN_ANOTHER_TASK"
        item.disposition = f"contained in {owners[0]}; leave to that task"
        item.evidence = ",".join(owners[:5])
        return

    # 5. Base rewrote every touched path after this tip was authored.
    if item.created_at and all(
        newest_touch(base, f) > item.created_at for f in item.files
    ):
        item.classification = "SUPERSEDED_BY_NEWER"
        item.disposition = (
            "all %d touched file(s) modified in %s after the tip was authored; "
            "newest implementation wins" % (len(item.files), base)
        )
        item.evidence = "base newer on every touched path"
        return

    # 6. Still has value. Does it still apply?
    if diff_applies(diff_text):
        item.classification = "RECOVERABLE_VALUE"
        item.disposition = (
            "range diff applies cleanly to base; recover via isolated worktree "
            "+ agent branch through the merge train"
        )
        item.evidence = "git apply --check --3way clean"
    else:
        item.classification = "CONFLICTED_NEEDS_FOCUSED_TASK"
        item.disposition = (
            "range diff no longer applies; queue a focused follow-up rather "
            "than forcing an overwrite"
        )
        item.evidence = "git apply --check --3way rejected"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="origin/master")
    ap.add_argument("--fingerprint", required=True)
    ap.add_argument("--out", default=".orch/recovery-ledger-local-branches.json")
    ap.add_argument("--depth", type=int, default=1500)
    ap.add_argument("--exclude-self", default="",
                    help="branch name of the reconciling task itself")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    items = enumerate_local_only(args.exclude_self)
    if args.limit:
        items = items[: args.limit]

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
        "evidence_kind": "local_only_branch_tips",
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
