#!/usr/bin/env python3
"""Name every QUEUED task whose dependencies can never be satisfied.

WHY THIS EXISTS

claim_task() returns None both when the queue is empty and when it is full of
work nothing can claim. The [claim] STALLED line tells you which of the two you
are in and how many tasks depend on work that will never complete; this tells
you WHICH tasks, WHICH dependencies, and why each one is hopeless -- which is
the part an operator needs before deciding anything.

Measured on the live queue 2026-08-25, before any of this existed: 321 QUEUED
tasks, 325 dependency edges, 4 satisfied. 204 of the remaining edges pointed at
something structurally unsatisfiable and had done so, invisibly, since
2026-07-15.

THE FOUR CATEGORIES, AND WHY THEY ARE SEPARATE

  decomposed-childless  The dep was split into sub-tasks and the sub-tasks were
                        never created. The work is LOST -- not deferred. Nothing
                        will ever finish on this task's behalf.

  collapsed             The dep was folded into a batch task by the backlog
                        compactor, which records the target in the note. The
                        work still exists, under a different slug, and the
                        dependency simply points at the wrong one. These are
                        REDIRECTABLE and the report prints where to.

  terminal              SUPERSEDED / CLOSED / QUARANTINED / PHANTOM_UNVERIFIED.
                        Somebody decided this work was replaced, abandoned or
                        unverifiable. Whether its dependents should now proceed
                        is a judgement about intent, not a fact about the queue,
                        so this tool reports and does not act.

  dangling              The dep names a slug no task has ever had. Split by
                        cause, because "no task has ever had this slug" names
                        the symptom and leaves the remedy to guesswork:

                          slice-series gap  the decomposer produced
                                            <base>-slice-1..N and skipped one,
                                            while a sibling still depends on the
                                            member that was never created. The
                                            dependency is not wrong about what
                                            it wanted; the work is missing.
                                            Re-slice the parent, or drop the dep.
                                            EVERY dangling edge on the live queue
                                            measured 2026-08-26 was this.

                          bad slug          a typo or a deleted row. Fix or drop.

This script is READ-ONLY. It changes nothing. That is deliberate: the four
categories want four different remedies, and three of them need a human to say
what was meant.
"""
import argparse
import collections
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

SATISFYING = ("DONE", "MERGED", "DEPLOYED_AND_VERIFIED")
TERMINAL = ("SUPERSEDED", "CLOSED", "QUARANTINED", "PHANTOM_UNVERIFIED")
COLLAPSE_MARKER = "collapsed into "


def _index():
    """Everything the classifier needs, in three paged reads."""
    tasks = db.select_all("tasks", {
        "select": "id,slug,state,deps,note,parent_task_id,project_id,created_at",
    }, order="id.asc") or []

    by_slug = {}
    for row in tasks:
        slug = row.get("slug")
        if not slug:
            continue
        # Prefer the most-finished row when a slug repeats, matching the claim
        # path's own preference order.
        best = by_slug.get(slug)
        if best is None or _rank(row) < _rank(best):
            by_slug[slug] = row

    children = collections.Counter()
    finished_children = collections.Counter()
    for row in tasks:
        parent = row.get("parent_task_id")
        if not parent:
            continue
        children[parent] += 1
        if row.get("state") in SATISFYING:
            finished_children[parent] += 1

    return tasks, by_slug, children, finished_children


def _rank(row):
    order = {"DEPLOYED_AND_VERIFIED": 0, "MERGED": 1, "DONE": 2}
    return order.get(row.get("state"), 3)


_SLICE_RE = re.compile(r"^(?P<base>.+)-slice-(?P<n>\d+)$")


def _diagnose_dangling(bare, by_slug):
    """Why a dep names a slug no task has ever had.

    "no task has ever had this slug" is true and useless: it names the symptom
    and leaves the operator to work out whether it is a typo, a deleted row, or
    something structural. Every dangling edge on the live queue turned out to be
    the same structural thing, and it was invisible until the slugs were laid
    side by side.

    A slice series is decomposed as <base>-slice-1..N. The decomposer sometimes
    skips one. Measured 2026-08-26: improve-implement-automated-testing-framework
    has slices 1, 3, 4, 5 and a dependency on the slice-2 that was never
    created; improve-implement-real-time-configuration-manage has 1, 2, 3, 5 and
    a dependency on 4. The dependency is not wrong about what it wanted — the
    work is simply missing from the series.

    That distinction changes the remedy. "Fix the slug" is the wrong advice for
    a gap: there is no slug to fix. Either re-slice the parent so the missing
    member exists, or decide the dependent no longer needs it.

    This function only explains. Filling a gap means re-running a decomposition,
    which is a decision about intent, so the report still refuses to act.
    """
    match = _SLICE_RE.match(bare)
    if not match:
        return "no task has ever had the slug %r" % bare

    base, missing = match.group("base"), int(match.group("n"))
    siblings = sorted(
        int(m.group("n"))
        for slug in by_slug
        for m in [_SLICE_RE.match(slug)]
        if m and m.group("base") == base
    )
    if not siblings:
        return "no task has ever had the slug %r" % bare
    return (
        "gap in a slice series: %s-slice-%d was never created "
        "(siblings present: %s) — re-slice the parent or drop the dep"
        % (base, missing, ", ".join(str(n) for n in siblings))
    )


def _classify(dep, by_slug, children, finished_children):
    """(category, detail) for one dependency, or None when it is satisfiable."""
    bare = str(dep).split(":")[-1]
    target = by_slug.get(bare)
    if target is None:
        return "dangling", _diagnose_dangling(bare, by_slug)

    state = target.get("state")
    if state in SATISFYING:
        return None

    if state == "DECOMPOSED":
        total = children.get(target["id"], 0)
        if total:
            done = finished_children.get(target["id"], 0)
            if done == total:
                return None                       # closure will satisfy it
            return None                           # children still running: legitimate wait
        note = target.get("note") or ""
        if COLLAPSE_MARKER in note:
            into = note.split(COLLAPSE_MARKER, 1)[1].split()[0].rstrip(".,;")
            into_state = (by_slug.get(into) or {}).get("state", "<<missing>>")
            return "collapsed", "work moved to %r (state %s)" % (into, into_state)
        return "decomposed-childless", "decomposed but no sub-tasks were ever created"

    if state in TERMINAL:
        return "terminal", "dependency is %s" % state

    return None                                    # QUEUED/RUNNING/etc: a real wait


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--limit", type=int, default=25,
                        help="tasks to list per category (default 25; 0 = all)")
    args = parser.parse_args(argv)

    tasks, by_slug, children, finished_children = _index()
    queued = [t for t in tasks if t.get("state") == "QUEUED"]

    blocked = collections.defaultdict(list)
    edges = collections.Counter()
    for task in queued:
        for dep in (task.get("deps") or []):
            verdict = _classify(dep, by_slug, children, finished_children)
            if not verdict:
                continue
            category, detail = verdict
            edges[category] += 1
            blocked[category].append({
                "slug": task.get("slug"),
                "id": task.get("id"),
                "dep": dep,
                "why": detail,
                "created_at": task.get("created_at"),
            })

    stuck_ids = {row["id"] for rows in blocked.values() for row in rows}
    summary = {
        "queued_total": len(queued),
        "queued_blocked_forever": len(stuck_ids),
        "edges_by_category": dict(edges),
    }

    if args.json:
        print(json.dumps({"summary": summary, "blocked": dict(blocked)},
                         indent=2, default=str))
        return 0 if not stuck_ids else 1

    print("QUEUE DEADLOCK REPORT")
    print("=" * 72)
    print("%d QUEUED task(s); %d can never be claimed as things stand."
          % (summary["queued_total"], summary["queued_blocked_forever"]))
    if not stuck_ids:
        print("\nNothing is permanently blocked. Any stall is ordinary waiting.")
        return 0

    order = ["decomposed-childless", "collapsed", "terminal", "dangling"]
    for category in order:
        rows = blocked.get(category) or []
        if not rows:
            continue
        print("\n%s  (%d edge(s))" % (category.upper(), len(rows)))
        print("-" * 72)
        shown = rows if args.limit == 0 else rows[:args.limit]
        for row in shown:
            print("  %-52s <- %s" % (row["slug"][:52], row["dep"]))
            print("  %-52s    %s" % ("", row["why"]))
        if len(rows) > len(shown):
            print("  ... and %d more (use --limit 0)" % (len(rows) - len(shown)))

    print("\n" + "=" * 72)
    print("This report changes nothing. The four categories want four different")
    print("remedies and three of them need someone to say what was meant:")
    print("  decomposed-childless -> re-queue the parent, or re-slice it")
    print("  collapsed            -> repoint the dep at the batch named above")
    print("  terminal             -> decide whether the dependent should proceed")
    print("  dangling             -> a slice-series gap needs the parent")
    print("                          re-sliced; anything else is a bad slug")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
