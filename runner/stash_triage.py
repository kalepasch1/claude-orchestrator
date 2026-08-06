#!/usr/bin/env python3
"""stash_triage.py — reproducible, read-only classification of git stashes.

## Why this exists (audit addendum §D)

The 2026-07-30 triage of 315 stashes on Mac 1 produced:

    119 empty  ·  37 already-landed  ·  12 cleanly-recoverable  ·  120 conflicted (76 touch runner/)

Those numbers were computed by hand, once, on one machine. `recover_stashes.sh` then hardcoded
the twelve recoverable ones as POSITIONAL refs:

    RECOVERABLE=(stash@{2} stash@{37} stash@{39} ... stash@{259})

That is a latent correctness bug, not just a style issue. `stash@{N}` is an index into the
reflog, not an identity: dropping or creating ANY stash renumbers every entry after it. Re-run
the script after the stash list has shifted and it recovers a different set of stashes than the
triage vetted — silently, because each one still applies cleanly. On a machine whose stash list
differs entirely (this repo currently has 0 stashes) it either no-ops or applies arbitrary work.

So this module makes the triage reproducible and addresses stashes by COMMIT SHA, which is
stable. It is strictly read-only: it never pops, never drops, never applies. `recover_stashes.sh`
remains the thing that writes; this is the thing that decides what it should write.

## The four buckets, defined precisely

    empty                the stash's diff against its own parent is empty — nothing to recover
    already_landed       every hunk is already present in HEAD (`git apply --reverse --check`
                         succeeds), i.e. the content shipped by another route
    recoverable          applies cleanly to HEAD (`git apply --check` succeeds)
    conflicted           real content that no longer applies — needs judgment, one at a time

Order matters: already-landed is tested before recoverable, because a stash whose content is
already in HEAD often ALSO fails a forward apply, and calling that "conflicted" would send
finished work back to a human for triage.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

EMPTY = "empty"
ALREADY_LANDED = "already_landed"
RECOVERABLE = "recoverable"
CONFLICTED = "conflicted"
ERROR = "error"

BUCKETS = (EMPTY, ALREADY_LANDED, RECOVERABLE, CONFLICTED, ERROR)

_TIMEOUT_S = int(os.environ.get("ORCH_STASH_TRIAGE_TIMEOUT_S", "30") or 30)


def _git(repo, *args, stdin=None, timeout=None):
    return subprocess.run(["git", *args], cwd=repo, input=stdin,
                          capture_output=True, text=True,
                          timeout=timeout or _TIMEOUT_S)


def list_stashes(repo):
    """[{ref, sha, subject}] newest first. Empty list when there are no stashes.

    `ref` is kept only for human-readable output. Every decision downstream uses `sha`,
    because the ref is positional and shifts under any drop.
    """
    r = _git(repo, "stash", "list", "--format=%gd%x00%H%x00%gs")
    if r.returncode != 0:
        return []
    out = []
    for line in r.stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split("\x00")
        if len(parts) < 3:
            continue
        out.append({"ref": parts[0], "sha": parts[1], "subject": parts[2]})
    return out


def stash_diff(repo, sha):
    """The stash's patch against its first parent. Returns (patch, err)."""
    r = _git(repo, "stash", "show", "-p", "--include-untracked", sha)
    if r.returncode != 0:
        # Older git, or a stash with no untracked part — retry without the flag before
        # declaring an error, so a flag-support difference is not misreported as corruption.
        r = _git(repo, "stash", "show", "-p", sha)
        if r.returncode != 0:
            return "", (r.stderr or "").strip()[-200:]
    return r.stdout, None


def stash_files(repo, sha):
    r = _git(repo, "stash", "show", "--name-only", sha)
    if r.returncode != 0:
        return []
    return [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]


def _applies(repo, patch, reverse=False):
    args = ["apply", "--check"]
    if reverse:
        args.append("--reverse")
    return _git(repo, *args, "-", stdin=patch).returncode == 0


def classify_stash(repo, entry):
    """Classify one stash. Pure with respect to the repo — nothing is written."""
    sha = entry["sha"]
    patch, err = stash_diff(repo, sha)
    if err:
        return {**entry, "bucket": ERROR, "detail": err, "files": []}
    if not patch.strip():
        return {**entry, "bucket": EMPTY, "detail": "no diff against its parent", "files": []}

    files = stash_files(repo, sha)
    touches_runner = any(f.startswith("runner/") for f in files)

    # Already-landed FIRST: content already in HEAD frequently fails a forward apply too, and
    # classifying it as conflicted would route finished work back to a human.
    if _applies(repo, patch, reverse=True):
        bucket, detail = ALREADY_LANDED, "content already present in HEAD"
    elif _applies(repo, patch):
        bucket, detail = RECOVERABLE, "applies cleanly to HEAD"
    else:
        bucket, detail = CONFLICTED, "does not apply to HEAD; needs judgment"

    return {**entry, "bucket": bucket, "detail": detail,
            "files": files, "touches_runner": touches_runner}


def triage(repo=".", limit=None):
    """Classify every stash. Read-only: never pops, drops, or applies.

    Returns counts plus the per-stash detail, with the conflicted set enumerated — that set is
    the actual remaining work, and it has to be addressable one at a time.
    """
    entries = list_stashes(repo)
    if limit:
        entries = entries[:int(limit)]
    results = [classify_stash(repo, e) for e in entries]

    counts = {b: 0 for b in BUCKETS}
    for r in results:
        counts[r["bucket"]] += 1

    conflicted = [r for r in results if r["bucket"] == CONFLICTED]
    return {
        "repo": os.path.abspath(repo),
        "total": len(results),
        "counts": counts,
        "runner_conflicted": sum(1 for r in conflicted if r.get("touches_runner")),
        # SHAs, never stash@{N} — the whole point. Feed these to a recovery step.
        "recoverable_shas": [r["sha"] for r in results if r["bucket"] == RECOVERABLE],
        "conflicted": [{"sha": r["sha"], "ref": r["ref"], "subject": r["subject"],
                        "files": r["files"], "touches_runner": r.get("touches_runner", False)}
                       for r in conflicted],
        "stashes": results,
    }


def format_report(report):
    c = report["counts"]
    lines = [
        f"stash triage — {report['repo']}",
        f"  total ............... {report['total']}",
        f"  empty ............... {c[EMPTY]}",
        f"  already landed ...... {c[ALREADY_LANDED]}",
        f"  recoverable ......... {c[RECOVERABLE]}",
        f"  conflicted .......... {c[CONFLICTED]}  ({report['runner_conflicted']} touch runner/)",
    ]
    if c[ERROR]:
        lines.append(f"  unreadable .......... {c[ERROR]}")
    if report["recoverable_shas"]:
        lines.append("")
        lines.append("  recoverable (by SHA — stable, unlike stash@{N}):")
        lines.extend(f"    {s}" for s in report["recoverable_shas"])
    if report["conflicted"]:
        lines.append("")
        lines.append("  conflicted — the real work, triage one at a time:")
        for item in report["conflicted"][:40]:
            flag = " [runner]" if item["touches_runner"] else ""
            lines.append(f"    {item['sha'][:12]}{flag}  {item['subject'][:70]}")
        if len(report["conflicted"]) > 40:
            lines.append(f"    ... and {len(report['conflicted']) - 40} more")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Read-only triage of git stashes into empty / already-landed / "
                    "recoverable / conflicted. Never pops, drops, or applies.")
    ap.add_argument("--repo", default=".")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    report = triage(args.repo, limit=args.limit)
    print(json.dumps(report, indent=2, sort_keys=True) if args.json
          else format_report(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
