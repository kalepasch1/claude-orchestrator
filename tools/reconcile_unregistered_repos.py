#!/usr/bin/env python3
"""Reconcile local git repositories that the orchestrator does not know about.

An "unregistered local repo" is a git checkout on this machine whose path is not
in the orchestrator `projects` table. It is the least visible evidence class of
all: no executor will ever claim work in it, no merge train will ever pick its
branches up, and no rescue-ref sweep covers it. Work parked there is lost by
default, silently.

This script is READ-ONLY. It never fetches, checks out, prunes, resets, cleans
or pushes. It walks candidate roots, identifies repos, compares each against the
registered project list, and classifies what the unregistered ones still hold.

Classification (same vocabulary as tools/reconcile_rescue_refs.py, applied to a
whole repo rather than a single commit):

  ALREADY_PRESENT     a registered project points at the same origin remote AND
                      this checkout has nothing unpushed or uncommitted
  ACTIVE_IN_ANOTHER_TASK
                      shares an origin with a registered project and its
                      unpushed work is on branches the merge train can see
  RECOVERABLE_VALUE   holds unpushed commits and/or TRACKED modifications that
                      exist nowhere else
  UNTRACKED_NEEDS_TRIAGE
                      untracked files only: nothing is at risk of being
                      overwritten, but somebody has to diff them against the
                      base before calling them value
  CONFLICTED_NEEDS_FOCUSED_TASK
                      unreadable, no origin remote, or otherwise needs a human
                      call before anything is moved

The registered project list is read from the ledger caller (``--registered``,
repeatable) so this stays offline and side-effect free.

Usage:
    python3 tools/reconcile_unregistered_repos.py \
        --fingerprint <audit-sha> --root ~/Documents \
        --registered /path/to/repo --registered /other/repo \
        --out .orch/recovery-ledger-<short>-repos.json
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from dataclasses import asdict, dataclass, field

SKIP_DIR_NAMES = {
    "node_modules", ".venv", "venv", "__pycache__", ".next", ".nuxt",
    "dist", "build", ".cache", "Library", ".Trash",
}


def git(*args: str, cwd: str) -> str:
    return subprocess.run(
        ("git",) + args, cwd=cwd, capture_output=True, text=True, errors="replace"
    ).stdout


@dataclass
class Item:
    ref: str
    sha: str = ""
    subject: str = ""
    created_at: int = 0
    kind: str = "unregistered_local_repo"
    classification: str = "UNKNOWN"
    disposition: str = ""
    files: list = field(default_factory=list)
    evidence: str = ""
    origin: str = ""
    unpushed_branches: list = field(default_factory=list)
    dirty_paths: int = 0
    tracked_dirty: int = 0
    untracked_paths: int = 0


def find_repos(roots: "list[str]", max_depth: int) -> "list[str]":
    """Every directory containing a .git entry, bounded in depth. Read-only."""
    found: list[str] = []
    for root in roots:
        root = os.path.abspath(os.path.expanduser(root))
        if not os.path.isdir(root):
            continue
        base_depth = root.rstrip(os.sep).count(os.sep)
        for dirpath, dirnames, _files in os.walk(root):
            depth = dirpath.count(os.sep) - base_depth
            if depth >= max_depth:
                dirnames[:] = []
                continue
            dirnames[:] = [
                d for d in dirnames
                if d not in SKIP_DIR_NAMES and not d.endswith("-wt")
            ]
            if ".git" in dirnames or os.path.exists(os.path.join(dirpath, ".git")):
                found.append(dirpath)
                dirnames[:] = []  # do not descend into a repo's submodule noise
    return sorted(set(found))


def normalise_remote(url: str) -> str:
    """Compare remotes by owner/name so ssh and https forms match."""
    url = url.strip().rstrip("/")
    if url.endswith(".git"):
        url = url[:-4]
    for sep in ("://", "@"):
        if sep in url:
            url = url.split(sep, 1)[1]
    return url.replace(":", "/").lower()


def classify(item: Item, path: str, registered_origins: "set[str]",
             registered_paths: "set[str]") -> None:
    if not os.path.isdir(path):
        item.classification = "CONFLICTED_NEEDS_FOCUSED_TASK"
        item.disposition = "repo path vanished during the scan; re-run to confirm"
        item.evidence = "path absent"
        return

    origin = git("remote", "get-url", "origin", cwd=path).strip()
    item.origin = origin
    item.sha = git("rev-parse", "HEAD", cwd=path).strip()[:40]
    item.subject = git("log", "-1", "--pretty=%s", cwd=path).strip()[:120]
    created = git("log", "-1", "--pretty=%ct", cwd=path).strip()
    item.created_at = int(created) if created.isdigit() else 0

    # `-uall` because plain --porcelain collapses an untracked DIRECTORY into a
    # single `?? dir/` entry, so the headline count understates what is there
    # and two checkouts with wildly different contents can report the same
    # number. Per-file is the only count worth acting on.
    status = git("status", "--porcelain", "-uall", cwd=path)
    lines = [ln for ln in status.splitlines() if ln.strip()]
    item.dirty_paths = len(lines)
    # Tracked modifications and untracked files are NOT the same risk, and
    # collapsing them is how this scan reported /Users/kpasch/Documents/_Trojun_archived
    # as "the single largest pocket of unreviewed local state" (223 paths).
    # 222 of those were untracked: 169 were byte-identical copies of files
    # already on origin/master at a shifted path (web/supabase/migrations/ vs
    # supabase/migrations/), and the remainder belonged to a DIFFERENT product
    # built in a clone of this repo. Nothing was at risk and nothing was
    # landable. A tracked modification overwrites content the base already has,
    # so it is genuinely unrecoverable if the checkout is lost; an untracked
    # file may be anything at all, and has to be looked at before it is called
    # value.
    item.tracked_dirty = len([ln for ln in lines if not ln.startswith("??")])
    item.untracked_paths = len([ln for ln in lines if ln.startswith("??")])

    # Branches with commits not present on any remote-tracking ref.
    unpushed: list[str] = []
    for line in git(
        "for-each-ref", "--format=%(refname:short)", "refs/heads/", cwd=path
    ).splitlines():
        name = line.strip()
        if not name:
            continue
        # Argument ORDER is load-bearing: `--not` negates everything that
        # follows it, so `--count --not --remotes <name>` excluded the branch
        # as well as the remotes and returned 0 for EVERY branch. Unpushed-work
        # detection therefore never fired, and a checkout holding real unpushed
        # commits on a clean tree was classified ALREADY_PRESENT — the silent
        # loss this whole scan exists to prevent. The branch must come first.
        ahead = git(
            "rev-list", "--count", name, "--not", "--remotes", cwd=path
        ).strip()
        if ahead.isdigit() and int(ahead) > 0:
            unpushed.append(f"{name}(+{ahead})")
    item.unpushed_branches = unpushed
    item.files = [f"{len(unpushed)} unpushed branch(es)",
                  f"{item.tracked_dirty} tracked modification(s)",
                  f"{item.untracked_paths} untracked path(s)"]

    if not origin:
        item.classification = "CONFLICTED_NEEDS_FOCUSED_TASK"
        item.disposition = (
            "local repo with NO origin remote; its history exists only on this "
            "machine. Needs a human call on where it should be published — do "
            "not delete or move it."
        )
        item.evidence = "no origin remote"
        return

    known_origin = normalise_remote(origin) in registered_origins

    if not unpushed and not item.dirty_paths:
        item.classification = "ALREADY_PRESENT"
        item.disposition = (
            "fully pushed and clean; "
            + ("origin matches a registered project" if known_origin
               else "origin is not a registered project, but nothing is at risk")
        )
        item.evidence = "no unpushed commits, no dirty paths"
        return

    if known_origin and unpushed and not item.dirty_paths:
        item.classification = "ACTIVE_IN_ANOTHER_TASK"
        item.disposition = (
            f"shares an origin with a registered project and has {len(unpushed)} "
            "unpushed branch(es) but a clean tree; the merge train can reach this "
            "work once the branches are pushed"
        )
        item.evidence = ",".join(unpushed[:5])
        return

    # Untracked-only state is a triage job, not a recovery job. It routinely
    # turns out to be a stale duplicate of the base at a shifted path, build
    # output, or a different product living in a clone of this repo — none of
    # which anyone should queue an agent branch for sight unseen. Say what it
    # is and ask for the look, rather than asserting value nobody has checked.
    if not unpushed and not item.tracked_dirty and item.untracked_paths:
        item.classification = "UNTRACKED_NEEDS_TRIAGE"
        item.disposition = (
            f"unregistered checkout with {item.untracked_paths} UNTRACKED path(s) "
            "and no tracked modifications or unpushed commits. Nothing here is "
            "at risk of being overwritten, and untracked files are as often a "
            "stale copy of the base, build output, or a different project in a "
            "shared clone as they are lost work. Diff them against the base "
            "before queueing any recovery. Source repo is READ-ONLY."
        )
        item.evidence = f"{item.untracked_paths} untracked, 0 tracked-dirty"
        return

    item.classification = "RECOVERABLE_VALUE"
    bits = []
    if unpushed:
        bits.append(f"{len(unpushed)} unpushed branch(es)")
    if item.tracked_dirty:
        bits.append(f"{item.tracked_dirty} tracked modification(s)")
    if item.untracked_paths:
        bits.append(f"{item.untracked_paths} untracked path(s)")
    item.disposition = (
        "unregistered checkout holding " + " and ".join(bits) + ". "
        + ("Origin is not a registered project, so no executor or merge train "
           "will ever see it. " if not known_origin else "")
        + "Register the project or recover the work through an agent branch. "
          "Source repo is READ-ONLY — do not delete, reset or move it."
    )
    item.evidence = (",".join(unpushed[:5])
                     or f"{item.tracked_dirty} tracked-dirty")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fingerprint", required=True)
    ap.add_argument("--root", action="append", default=[])
    ap.add_argument("--registered", action="append", default=[],
                    help="repo_path of a registered project (repeatable)")
    ap.add_argument("--max-depth", type=int, default=4)
    ap.add_argument("--out", default=".orch/recovery-ledger-repos.json")
    args = ap.parse_args()

    roots = args.root or [os.path.expanduser("~/Documents")]
    registered_paths = {
        os.path.abspath(os.path.expanduser(p)) for p in args.registered
    }
    registered_origins = set()
    for p in registered_paths:
        if os.path.isdir(p):
            url = git("remote", "get-url", "origin", cwd=p).strip()
            if url:
                registered_origins.add(normalise_remote(url))

    items: list[Item] = []
    for path in find_repos(roots, args.max_depth):
        if os.path.abspath(path) in registered_paths:
            continue  # registered projects are covered by the other reconcilers
        it = Item(ref=path)
        try:
            classify(it, path, registered_origins, registered_paths)
        except Exception as exc:
            it.classification = "CONFLICTED_NEEDS_FOCUSED_TASK"
            it.disposition = "classification error, needs focused task: %s" % exc
            it.evidence = "exception"
        items.append(it)

    counts: dict = {}
    for it in items:
        counts[it.classification] = counts.get(it.classification, 0) + 1

    ledger = {
        "audit_fingerprint": args.fingerprint,
        "base": "n/a (whole-repo comparison)",
        "evidence_kind": "unregistered_local_repo",
        "registered_project_count": len(registered_paths),
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
