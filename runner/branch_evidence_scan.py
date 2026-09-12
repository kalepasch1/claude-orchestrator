#!/usr/bin/env python3
"""Ask the branches whether a "dead" dependency actually shipped.

WHY THIS EXISTS

queue_deadlock_report classifies a dependency as `terminal` when its task sits
in SUPERSEDED / CLOSED / QUARANTINED / PHANTOM_UNVERIFIED, and reports that
"whether its dependents should now proceed is a judgement about intent". That is
the right caution for SUPERSEDED and CLOSED, where somebody decided something.

It is not the right caution for PHANTOM_UNVERIFIED, and it turns out not to be
the right caution for a fair number of QUARANTINED rows either, because in those
cases the task STATE and the REPOSITORY can disagree — and the repository is the
one that decides whether the work exists.

Observed 2026-08-26 while resolving one of these by hand: a task's sibling was
queued as a fresh recovery of `...-implement-bootstrap-inj` on the strength of
its state, while `runner/branch_bootstrap_injection.py`, its 310-line test file
and the intake_watcher hook were all sitting on origin/master, merged. The state
said the work needed redoing. The tree said it was done. Redoing it would have
been a duplicate of shipped code.

PHANTOM_UNVERIFIED is that disagreement named explicitly — "marked MERGED but no
shipped code found" — recorded once, in an audit, and never re-checked. Code
lands after an audit runs. Nothing goes back to look.

This goes back to look. For every dependency blocking a QUEUED task whose state
says the work will never arrive, it asks git one question: is `agent/<slug>`
reachable from the project's default branch? If it is, the work SHIPPED, the
dependent is not blocked by anything real, and that is a fact rather than a
judgement.

READ-ONLY, AND IT REPORTS RATHER THAN ACTS. Knowing the work landed does not
tell you the dependent should now run — the dependent may itself be obsolete.
The point is to stop presenting a shipped dependency as a dead end.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import db

#: States where the task row claims the work will never arrive, but the row is
#: evidence ABOUT the work rather than the work itself, so the tree can disagree.
#: SUPERSEDED and CLOSED are deliberately excluded: those record a decision
#: someone made, and a branch existing does not overrule a decision.
RECHECKABLE = ("PHANTOM_UNVERIFIED", "QUARANTINED")

BRANCH_PREFIX = "agent/"


def _git(repo, *args, timeout=60):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True,
                          text=True, timeout=timeout)


def branch_landed(repo, slug, base):
    """Is agent/<slug> reachable from `base`? (None when there is no branch.)

    Reachability, not existence: a branch that exists but was never merged is
    not evidence that anything shipped, and treating it as such would be the
    same mistake in the other direction.
    """
    ref = BRANCH_PREFIX + slug
    for candidate in ("refs/remotes/origin/" + ref, "refs/heads/" + ref):
        shown = _git(repo, "rev-parse", "--verify", "--quiet", candidate)
        if shown.returncode != 0 or not shown.stdout.strip():
            continue
        sha = shown.stdout.strip()
        contained = _git(repo, "merge-base", "--is-ancestor", sha, base)
        return {"ref": candidate, "sha": sha, "landed": contained.returncode == 0}
    return None


def blocking_deps(tasks):
    """{dep_slug: [dependent_slug, ...]} for QUEUED tasks with recheckable deps."""
    by_slug = {}
    for row in tasks:
        slug = row.get("slug")
        if slug and slug not in by_slug:
            by_slug[slug] = row

    out = {}
    for row in tasks:
        if row.get("state") != "QUEUED":
            continue
        for dep in row.get("deps") or []:
            bare = str(dep).split(":")[-1]
            target = by_slug.get(bare)
            if not target or target.get("state") not in RECHECKABLE:
                continue
            out.setdefault(bare, []).append(row.get("slug"))
    return out


def scan(repo, base="origin/master", tasks=None):
    """Report which recheckable dependencies have in fact shipped."""
    if tasks is None:
        tasks = db.select_all("tasks", {"select": "slug,state,deps"},
                              order="id.asc") or []
    states = {row.get("slug"): row.get("state") for row in tasks if row.get("slug")}

    shipped, absent, unmerged = [], [], []
    for dep, dependents in sorted(blocking_deps(tasks).items()):
        evidence = branch_landed(repo, dep, base)
        record = {"dep": dep, "state": states.get(dep), "blocks": sorted(dependents)}
        if evidence is None:
            absent.append(record)
            continue
        record.update(ref=evidence["ref"], sha=evidence["sha"][:12])
        (shipped if evidence["landed"] else unmerged).append(record)

    return {
        "base": base,
        "shipped": shipped,
        "unmerged": unmerged,
        "no_branch": absent,
        "counts": {"shipped": len(shipped), "unmerged": len(unmerged),
                   "no_branch": len(absent)},
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", default=os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))
    parser.add_argument("--base", default="origin/master")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    result = scan(args.repo, args.base)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0

    counts = result["counts"]
    print("BRANCH EVIDENCE FOR DEAD-END DEPENDENCIES")
    print("=" * 72)
    print("base %s: %d shipped, %d unmerged branch(es), %d with no branch at all"
          % (result["base"], counts["shipped"], counts["unmerged"],
             counts["no_branch"]))

    if result["shipped"]:
        print("\nSHIPPED — the task state says dead end, the tree says merged")
        print("-" * 72)
        for row in result["shipped"]:
            print("  %s  [%s]  %s" % (row["dep"], row["state"], row["sha"]))
            for dependent in row["blocks"]:
                print("      blocks %s" % dependent)

    if result["unmerged"]:
        print("\nUNMERGED — a branch exists but never landed; not evidence of anything")
        print("-" * 72)
        for row in result["unmerged"]:
            print("  %s  [%s]  %s" % (row["dep"], row["state"], row["sha"]))

    print("\n" + "=" * 72)
    print("This report changes nothing. That the work shipped does not mean the")
    print("dependent should now run — it may itself be obsolete. The point is to")
    print("stop presenting a shipped dependency as a dead end.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
