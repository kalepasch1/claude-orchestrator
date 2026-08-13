#!/usr/bin/env python3
"""Reconcile unmerged agent/* branches against the current default branch.

Read-only. No branch is deleted, force-updated, rebased or merged by this
script; it classifies and reports so the merge train and focused follow-up
tasks can act with provenance.

Classification vocabulary matches tools/reconcile_rescue_refs.py.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from dataclasses import dataclass, asdict, field


def git(*args, check=False):
    p = subprocess.run(("git",) + args, capture_output=True, text=True,
                       errors="replace")
    if check and p.returncode != 0:
        raise RuntimeError("git %s: %s" % (" ".join(args), p.stderr.strip()))
    return p.stdout


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


def enumerate_branches(pattern):
    # `for-each-ref refs/heads/*` only matches one path segment, so
    # `agent/foo/bar` is silently dropped. Normalising a trailing `*` away
    # turns the pattern into a prefix match, which recurses.
    if pattern.endswith("/*"):
        pattern = pattern[:-1]
    fmt = "%(refname)%09%(objectname)%09%(creatordate:unix)%09%(contents:subject)"
    out = git("for-each-ref", "--format=" + fmt, pattern)
    items = []
    for line in out.splitlines():
        p = line.split("\t")
        if len(p) < 4:
            continue
        items.append(Item(ref=p[0], sha=p[1], subject=p[3],
                          created_at=int(p[2]) if p[2].isdigit() else 0))
    return items


def branch_diff(base, sha):
    """Diff of the branch's own work: merge-base(base, sha)..sha."""
    mb = git("merge-base", base, sha).strip()
    if not mb:
        return "", []
    diff = git("diff", "--no-color", mb + ".." + sha)
    files = [f for f in git("diff", "--name-only", mb + ".." + sha).splitlines()
             if f.strip()]
    return diff, files


def patch_id(diff_text):
    if not diff_text.strip():
        return None
    out = subprocess.run(["git", "patch-id", "--stable"], input=diff_text,
                         capture_output=True, text=True,
                         errors="replace").stdout
    return out.split()[0] if out.strip() else None


def base_patch_ids(base, depth):
    shas = git("log", "--no-merges", "--pretty=format:%H", "-n", str(depth),
               base).split()
    ids = set()
    for i in range(0, len(shas), 150):
        d = subprocess.run(["git", "show", "--no-color", "--patch",
                            "--first-parent"] + shas[i:i + 150],
                           capture_output=True, text=True,
                           errors="replace").stdout
        out = subprocess.run(["git", "patch-id", "--stable"], input=d,
                             capture_output=True, text=True,
                             errors="replace").stdout
        for line in out.splitlines():
            if line.strip():
                ids.add(line.split()[0])
    return ids


def newest_touch(base, path):
    out = git("log", "-1", "--format=%ct", base, "--", path).strip()
    return int(out) if out.isdigit() else 0


def applies(diff_text):
    if not diff_text.strip():
        return False
    return subprocess.run(["git", "apply", "--check", "--3way", "-"],
                          input=diff_text, capture_output=True,
                          text=True).returncode == 0


def classify(it, base, known, live_slugs):
    if subprocess.run(["git", "merge-base", "--is-ancestor", it.sha, base],
                      capture_output=True).returncode == 0:
        it.classification = "ALREADY_PRESENT"
        it.disposition = "already merged into " + base
        it.evidence = "is-ancestor"
        return

    diff, files = branch_diff(base, it.sha)
    it.files = files

    pid = patch_id(diff)
    if pid and pid in known:
        it.classification = "ALREADY_PRESENT"
        it.disposition = "patch-identical to work already in " + base
        it.evidence = "patch-id=" + pid
        return

    if not files:
        it.classification = "ALREADY_PRESENT"
        it.disposition = "no net diff against merge-base; nothing to recover"
        it.evidence = "empty diff"
        return

    slug = it.ref.split("/agent/", 1)[-1]
    if slug in live_slugs:
        it.classification = "ACTIVE_IN_ANOTHER_TASK"
        it.disposition = "a live queued/running task owns slug " + slug
        it.evidence = "live-task-slug"
        return

    if it.created_at and all(newest_touch(base, f) > it.created_at
                             for f in files):
        it.classification = "SUPERSEDED_BY_NEWER"
        it.disposition = ("all %d touched path(s) rewritten in %s after the "
                          "branch was cut; newest wins" % (len(files), base))
        it.evidence = "base newer on every touched path"
        return

    if applies(diff):
        it.classification = "RECOVERABLE_VALUE"
        it.disposition = "diff still applies; route through the merge train"
        it.evidence = "git apply --check --3way clean"
    else:
        it.classification = "CONFLICTED_NEEDS_FOCUSED_TASK"
        it.disposition = ("diff no longer applies; queue a focused follow-up "
                          "instead of forcing an overwrite")
        it.evidence = "git apply --check --3way rejected"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="origin/main")
    ap.add_argument("--pattern", default="refs/remotes/origin/agent/*")
    ap.add_argument("--fingerprint", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--depth", type=int, default=600)
    ap.add_argument("--live-slugs", default="",
                    help="comma-separated slugs owned by live tasks")
    args = ap.parse_args()

    live = {s.strip() for s in args.live_slugs.split(",") if s.strip()}
    items = enumerate_branches(args.pattern)
    known = base_patch_ids(args.base, args.depth) if items else set()

    for it in items:
        try:
            classify(it, args.base, known, live)
        except Exception as exc:
            it.classification = "CONFLICTED_NEEDS_FOCUSED_TASK"
            it.disposition = "classification error, needs focused task: %s" % exc
            it.evidence = "exception"

    counts = {}
    for it in items:
        counts[it.classification] = counts.get(it.classification, 0) + 1

    ledger = {"audit_fingerprint": args.fingerprint, "base": args.base,
              "total": len(items), "counts": counts,
              "unknown": counts.get("UNKNOWN", 0),
              "items": [asdict(i) for i in items]}
    d = os.path.dirname(args.out)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(args.out, "w") as fh:
        json.dump(ledger, fh, indent=1, sort_keys=True)
    print(json.dumps({"total": len(items), "counts": counts}, indent=2))
    return 1 if counts.get("UNKNOWN") else 0


if __name__ == "__main__":
    raise SystemExit(main())
