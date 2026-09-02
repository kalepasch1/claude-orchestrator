#!/usr/bin/env python3
"""
stranded_branch_inventory.py - what is sitting on agent branches that never merged.

WHY
---
Audited 2026-08-30. merge_train had run 532 consecutive passes considering 0
branches (the fleet was paused), and the last 12 DONE tasks in each of tomorrow
and apparently carried an artifact commit that existed in the repo but was not on
the mainline. 24 of 24. The work was done, recorded as done, and never landed:

    tomorrow    403 branches / 1183 commits not in origin/main
    apparently  387 branches / 665  commits not in origin/master

That is not a backlog, because nobody can act on it as a number. This turns it
into rows you can sort, so the ones worth landing can be found and the rest
deleted honestly rather than left to look like inventory.

WHAT IT DOES NOT DO
-------------------
Reads only. No checkout, no merge, no branch deletion, no network beyond the
fetch you choose to run yourself first. Judging which of 790 branches deserves to
land is not a decision to automate.

SUPERSEDED
----------
The useful signal is not "has commits" - almost all of them do. It is whether the
FILES a branch touches have since moved on in mainline. A branch whose files are
untouched since it forked is a clean candidate to land; one whose every file has
been rewritten is almost certainly dead. `superseded_pct` is that ratio, and
sorting by it ascending puts the landable work at the top.

USAGE
    python3 tools/stranded_branch_inventory.py <repo> <mainline> [--csv out.csv]
    python3 tools/stranded_branch_inventory.py ~/Documents/tomorrow/tomorrow origin/main
"""
import argparse
import csv
import datetime
import os
import re
import subprocess
import sys

AGENT_PREFIX = re.compile(
    r"^origin/(agent|bot|codex|qafix|relfix|recover|recovery|rescue|consolidate|"
    r"canary|wt|ssw|mac1)[-/]")

# A branch touching more files than this is a batch/merge artifact, not a change
# someone reviews; counted but not diffed file-by-file, which is the slow part.
WIDE_BRANCH_FILES = 400

# Share of a branch's files that mainline has rewritten since the fork point,
# above which the branch is reported as almost certainly dead. Not a delete
# threshold - a sort key, so a human looks at the landable end of the list first.
DEAD_SUPERSEDED_PCT = 90.0


def git(repo, *args, timeout=60):
    try:
        out = subprocess.run(["git", "-C", repo] + list(args),
                             capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return ""
    return out.stdout if out.returncode == 0 else ""


def branches(repo):
    listing = git(repo, "branch", "-r", "--format=%(refname:short)")
    return [b.strip() for b in listing.splitlines()
            if b.strip() and AGENT_PREFIX.match(b.strip())]


def _int(text, default=0):
    text = (text or "").strip()
    return int(text) if text.isdigit() else default


def inspect(repo, branch, mainline):
    """One row, or None when the branch holds nothing mainline lacks."""
    ahead = _int(git(repo, "rev-list", "--count", "%s..%s" % (mainline, branch)))
    if not ahead:
        return None

    base = git(repo, "merge-base", mainline, branch).strip()
    files = [f for f in git(repo, "diff", "--name-only", "%s...%s" % (mainline, branch)
                            ).splitlines() if f.strip()]
    last = git(repo, "log", "-1", "--format=%ct|%s", branch).strip()
    when, subject = (last.split("|", 1) + [""])[:2] if "|" in last else ("0", last)
    age_days = ((datetime.datetime.utcnow()
                 - datetime.datetime.utcfromtimestamp(_int(when))).days
                if _int(when) else None)

    # How many of this branch's files has mainline changed since the fork point?
    superseded = 0
    if base and files and len(files) <= WIDE_BRANCH_FILES:
        for path in files:
            if _int(git(repo, "rev-list", "--count", "%s..%s" % (base, mainline),
                        "--", path)):
                superseded += 1

    return {
        "branch": branch,
        "commits_ahead": ahead,
        "files": len(files),
        "superseded_files": superseded,
        "superseded_pct": round(100.0 * superseded / len(files), 1) if files else 0.0,
        "age_days": age_days,
        "last_subject": subject[:90],
    }


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("repo")
    ap.add_argument("mainline")
    ap.add_argument("--csv", dest="csv_path")
    ap.add_argument("--top", type=int, default=25)
    args = ap.parse_args(argv)

    repo = os.path.expanduser(args.repo)
    todo = branches(repo)
    print("%s: %d agent-style remote branches" % (os.path.basename(repo), len(todo)),
          file=sys.stderr)

    rows = []
    for i, branch in enumerate(todo, 1):
        row = inspect(repo, branch, args.mainline)
        if row:
            rows.append(row)
        if i % 100 == 0:
            print("  ...%d/%d scanned, %d stranded" % (i, len(todo), len(rows)),
                  file=sys.stderr)

    rows.sort(key=lambda r: (r["superseded_pct"], -(r["commits_ahead"])))

    total_commits = sum(r["commits_ahead"] for r in rows)
    clean = [r for r in rows if r["superseded_pct"] == 0.0]
    dead = [r for r in rows if r["superseded_pct"] >= DEAD_SUPERSEDED_PCT]

    print()
    print("STRANDED: %d branches, %d commits not in %s"
          % (len(rows), total_commits, args.mainline))
    print("  untouched since fork (land candidates): %d branches / %d commits"
          % (len(clean), sum(r["commits_ahead"] for r in clean)))
    print("  >=%.0f%% of files rewritten since (likely dead): %d branches / %d commits"
          % (DEAD_SUPERSEDED_PCT, len(dead), sum(r["commits_ahead"] for r in dead)))
    print()
    print("%-58s %5s %5s %7s %5s  %s"
          % ("BRANCH", "AHEAD", "FILES", "SUPER%", "AGE", "LAST COMMIT"))
    for r in rows[:args.top]:
        print("%-58s %5d %5d %6.1f%% %4sd  %s"
              % (r["branch"][:58], r["commits_ahead"], r["files"],
                 r["superseded_pct"], r["age_days"], r["last_subject"][:60]))

    if args.csv_path:
        with open(args.csv_path, "w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()) if rows
                                    else ["branch"])
            writer.writeheader()
            writer.writerows(rows)
        print("\nfull inventory -> %s" % args.csv_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
