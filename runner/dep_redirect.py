#!/usr/bin/env python3
"""Repoint dependency edges at the batch task that absorbed their target.

WHY THIS EXISTS

queue_deadlock_report names every QUEUED task whose dependencies can never be
satisfied, and sorts them into four categories. It is deliberately read-only,
because three of the four need a human to say what was meant:

    decomposed-childless  the work is LOST; someone must decide what to do
    terminal              somebody abandoned it; proceeding is a judgement
    dangling              the slug never existed; a typo needs a human

The fourth is not like the others:

    collapsed             the backlog compactor folded this task into a batch
                          task and RECORDED THE TARGET IN THE NOTE. The work
                          still exists, under a different slug. The dependency
                          simply points at the wrong one.

That is a clerical error with the answer written next to it. No judgement is
required, and nothing about the intent is ambiguous: the depending task wanted
that work, and that work is right there under another name. Leaving it for a
human means QUEUED tasks wait on a slug the compactor already told us was
renamed — which is how dependency edges sat unsatisfiable, invisibly, since
2026-07-15.

So this module acts on exactly that one category and nothing else.

WHAT IT REFUSES TO DO

Redirecting is only safe while it stays clerical, so a redirect is skipped when:

  * the note names a target that no task has ever had — that is a `dangling`
    edge wearing a collapsed edge's clothes, and re-pointing at it would swap
    one unsatisfiable dep for another
  * the target is the depending task itself — a self-dependency is permanently
    unsatisfiable, and a compactor that folded a task into its own dependent is
    a bug this tool must expose, not paper over
  * the depending task is not QUEUED — a RUNNING or finished task's deps are
    history, and rewriting history to make a report look better is the failure
    mode this whole family of tools exists to avoid

DRY RUN BY DEFAULT. `--apply` writes; without it nothing is changed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import db
import queue_deadlock_report as qdr


def collapsed_target(task_row):
    """The slug a collapsed task's work moved to, or None.

    Reads the marker queue_deadlock_report already knows about, so the two
    tools cannot disagree about what "collapsed" means.
    """
    note = str((task_row or {}).get("note") or "")
    if qdr.COLLAPSE_MARKER not in note:
        return None
    tail = note.split(qdr.COLLAPSE_MARKER, 1)[1].strip()
    if not tail:
        return None
    return tail.split()[0].rstrip(".,;)")


def plan_redirects(tasks, by_slug, children, finished_children):
    """Every safe dep rewrite, as {task_id, slug, dep, into, deps_before, deps_after}.

    Pure: reads the index, decides, and returns. Nothing here writes, so the
    dry run and the apply run are guaranteed to agree.
    """
    plan = []
    for row in tasks:
        if row.get("state") != "QUEUED":
            continue
        deps = row.get("deps") or []
        if not isinstance(deps, list) or not deps:
            continue

        new_deps = list(deps)
        changed = []
        for index, dep in enumerate(deps):
            verdict = qdr._classify(dep, by_slug, children, finished_children)
            if not verdict or verdict[0] != "collapsed":
                continue
            bare = str(dep).split(":")[-1]
            into = collapsed_target(by_slug.get(bare))
            if not into:
                continue
            if into not in by_slug:
                continue                      # dangling in disguise
            if into == row.get("slug"):
                continue                      # would create a self-dependency
            if into in new_deps:
                new_deps[index] = None        # target already listed; drop the stale edge
            else:
                new_deps[index] = into
            changed.append((dep, into))

        if not changed:
            continue
        deduped = [d for d in new_deps if d is not None]
        if deduped == deps:
            continue
        plan.append({
            "task_id": row.get("id"),
            "slug": row.get("slug"),
            "redirects": changed,
            "deps_before": deps,
            "deps_after": deduped,
        })
    return plan


def _write_one(item):
    """Write one task's deps. True on success, False on a named failure.

    Failures are counted and printed rather than raised: one row losing a race
    must not abandon the rest, and a silent failure would leave a task blocked
    while the summary claimed it had been freed.
    """
    try:
        db.update("tasks", {"id": item["task_id"]}, {"deps": item["deps_after"]})
        return True
    except Exception as exc:
        print("[dep-redirect] %s: update failed: %s" % (item["slug"], exc))
        return False


def apply_plan(plan, write=False):
    """Write the planned deps. Returns {applied, failed}. Fail-soft per row."""
    applied = 0
    failed = 0
    for item in plan:
        if not write:
            continue
        if _write_one(item):
            applied += 1
        else:
            failed += 1
    return {"applied": applied, "failed": failed}


def run(write=False):
    """Build the index, plan, and optionally apply. Returns a summary dict."""
    tasks, by_slug, children, finished_children = qdr._index()
    plan = plan_redirects(tasks, by_slug, children, finished_children)
    result = apply_plan(plan, write=write)
    result["planned"] = len(plan)
    result["edges"] = sum(len(p["redirects"]) for p in plan)
    result["plan"] = plan
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true",
                        help="write the redirects (default: dry run)")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    result = run(write=args.apply)

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
        return 0

    if not result["planned"]:
        print("dep-redirect: no collapsed dependency edges to repoint")
        return 0

    print("dep-redirect: %d task(s), %d edge(s)%s"
          % (result["planned"], result["edges"],
             "" if args.apply else "  [DRY RUN — pass --apply to write]"))
    for item in result["plan"]:
        for dep, into in item["redirects"]:
            print("  %s: %s -> %s" % (item["slug"], dep, into))
    if args.apply:
        print("applied=%d failed=%d" % (result["applied"], result["failed"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
