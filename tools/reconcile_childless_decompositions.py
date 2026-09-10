#!/usr/bin/env python3
"""Reconcile DECOMPOSED parents that have no children.

WHY THIS EXISTS
---------------
`runner/db.py::_closed_decompositions()` closes a DECOMPOSED parent only when
it has children and all of them are finished. Its comment is explicit that a
CHILDLESS parent must NOT be treated as closed:

    A childless parent is NOT closed. It is a decomposition that lost its
    children, which is a different defect and must not be papered over by
    treating "no children" as "all children done".

That judgement is correct and this tool does not weaken it. The gap is that
nothing ever REPAIRED the defect it identifies, so childless parents
accumulated and every dependent behind one deadlocked permanently.

Measured on prod 2026-09-10:
    5,319 DECOMPOSED parents
    5,017 of them have zero children by parent_task_id (94%)
      304 are recoverable by slug prefix (2,164 orphaned children to relink)
    4,713 have no children under `<slug>-slice-%` anywhere

DO NOT "fix" this by adding DECOMPOSED to the dep-satisfying allowlist. That
releases dependents of work that genuinely does not exist. Every resolution
below is driven by evidence recorded on the row itself.

THE FOUR PRODUCERS (by note prefix, measured 2026-09-10)
--------------------------------------------------------
Childless parents are not one defect. They are four, and they need four
different answers:

1. `backlog-compactor: collapsed into <successor-slug>`   (~600)
   Not a decomposition at all. The work was folded into a named batch task.
   The note names the successor, so provenance is exact: if the successor is
   finished the parent is DONE-by-succession; if not, the parent is still
   pending and belongs back in QUEUED.

2. `auto-sliced-before-agent: spawning N sub-subtasks`    (~515)
   The genuine task_slicer path. Children should exist as `<slug>-slice-N`.
   Where they do, the link was simply never written to `parent_task_id`
   (see the `_insert_task` variant ladder) -- relink and let
   `_closed_decompositions()` close the parent normally on the next pass.
   Where no slice exists, the flip to DECOMPOSED landed and the inserts did
   not: the work never started, so the PARENT returns to QUEUED.

3. `recovered from shelf -> split into sub-tasks`         (757)
4. `recovered: restored from batch-orphan quarantine`     (560)
   Recovery paths that recorded a split but left no child under any naming
   this tool can verify. With no evidence of delivery, the safe answer is
   the honest one: return the PARENT to QUEUED. It is not satisfied, and
   saying so keeps its dependents blocked rather than releasing them onto
   work that was never done.

SAFETY
------
Dry-run by default. `--apply` is required to write, and even then this tool
never marks a parent DONE without naming the specific finished successor or
child set that justifies it. Reasoning is printed per row so a human can audit
the plan before it is applied.
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.queue_health import ENV, fetch_all, load_config, rest  # noqa: E402

# States that mean "this task delivered". Kept identical to
# runner/db.py::_DEP_SATISFYING_STATES so the two cannot drift apart.
SATISFYING = ("DONE", "MERGED", "DEPLOYED_AND_VERIFIED")

# States a task can never leave. A dep pointing at one of these is
# unsatisfiable and the dependent must be re-pointed or closed, never released.
TERMINAL_UNSATISFYING = ("SUPERSEDED", "QUARANTINED", "CLOSED", "PHANTOM_UNVERIFIED")

COMPACTOR_RE = re.compile(r"collapsed into ([A-Za-z0-9._-]+)")
SLICE_RE = re.compile(r"-slice-\d+$")

# Verdicts
RELINK = "relink_children"
DONE_BY_SUCCESSION = "done_by_succession"
REQUEUE_PARENT = "requeue_parent"
LEAVE = "leave_alone"

# A parent collapsed into a successor that then died (QUARANTINED, SUPERSEDED,
# CLOSED). Deliberately NOT auto-requeued.
#
# Measured 2026-09-10: treating this as REQUEUE_PARENT moved 4,294 parents back
# to QUEUED in the dry run -- roughly 4,000 of them collapsed into a handful of
# quarantined backlog batches, against a live queue of 1,486. Reviving them
# wholesale would nearly quadruple the queue with work a human once chose to
# batch and then quarantine, and no evidence says that choice was wrong.
# The honest report is "the successor died, so this needs a decision", and the
# decision is the operator's. --verdict review_successor_terminal lists them.
REVIEW_SUCCESSOR_TERMINAL = "review_successor_terminal"

# Verdicts this tool will write without a human naming them explicitly.
AUTO_APPLY = (RELINK, DONE_BY_SUCCESSION, REQUEUE_PARENT)


def _index(rows: list, key: str) -> dict:
    out: dict = collections.defaultdict(list)
    for row in rows:
        out[row.get(key)].append(row)
    return out


def classify(parent: dict, fk_children: list, slug_children: list,
             by_project_slug: dict) -> tuple:
    """Return (verdict, detail) for one DECOMPOSED parent.

    Pure: takes already-fetched rows, touches no network. Unit-testable.
    """
    if fk_children:
        # Not our defect -- _closed_decompositions() already handles this.
        return LEAVE, "has %d linked child(ren); normal close path applies" % len(fk_children)

    note = str(parent.get("note") or "")

    # Producer 1: backlog-compactor. The note names the successor exactly.
    match = COMPACTOR_RE.search(note)
    if match:
        successor_slug = match.group(1)
        successor = by_project_slug.get((parent.get("project_id"), successor_slug))
        if successor is None:
            return (REQUEUE_PARENT,
                    "compactor named successor %r but no such task exists in "
                    "this project -- the collapse target is gone, so the work "
                    "is undelivered" % successor_slug)
        state = str(successor.get("state") or "")
        if state in SATISFYING:
            return (DONE_BY_SUCCESSION,
                    "work shipped as %s (state=%s)" % (successor_slug, state))
        if state in TERMINAL_UNSATISFYING:
            return (REVIEW_SUCCESSOR_TERMINAL,
                    "collapsed into %s which is %s -- the successor died, so "
                    "neither DONE nor QUEUED is defensible without a human "
                    "deciding whether the batch should be revived"
                    % (successor_slug, state))
        return (REQUEUE_PARENT,
                "collapsed into %s which is %s -- not delivered, so the parent "
                "is not satisfied" % (successor_slug, state or "unknown"))

    # Producer 2: the slicer. Children may exist but be unlinked.
    if slug_children:
        unlinked = [c for c in slug_children if not c.get("parent_task_id")]
        if unlinked:
            return (RELINK,
                    "%d slice(s) exist by slug but %d have no parent_task_id; "
                    "relinking lets the normal close path evaluate them"
                    % (len(slug_children), len(unlinked)))
        return LEAVE, "slices exist and are already linked elsewhere"

    # Producers 2 (failed inserts), 3 and 4: no child evidence anywhere.
    return (REQUEUE_PARENT,
            "no child under parent_task_id or `%s-slice-%%`, and no successor "
            "named in the note -- the split never landed, so the work never "
            "started" % parent.get("slug"))


def build_plan(parents: list, all_tasks: list) -> list:
    """Classify every DECOMPOSED parent. Returns a list of plan entries."""
    by_parent_fk = _index([t for t in all_tasks if t.get("parent_task_id")],
                          "parent_task_id")
    by_project_slug = {(t.get("project_id"), t.get("slug")): t for t in all_tasks}

    # Bucket candidate slice-children by project for a cheap prefix scan.
    by_project: dict = collections.defaultdict(list)
    for task in all_tasks:
        if SLICE_RE.search(str(task.get("slug") or "")):
            by_project[task.get("project_id")].append(task)

    plan = []
    for parent in parents:
        prefix = str(parent.get("slug") or "") + "-slice-"
        slug_children = [t for t in by_project.get(parent.get("project_id"), [])
                         if str(t.get("slug") or "").startswith(prefix)]
        verdict, detail = classify(
            parent, by_parent_fk.get(parent.get("id"), []),
            slug_children, by_project_slug,
        )
        plan.append({
            "id": parent.get("id"),
            "slug": parent.get("slug"),
            "project_id": parent.get("project_id"),
            "verdict": verdict,
            "detail": detail,
            "children": [c.get("id") for c in slug_children
                         if not c.get("parent_task_id")],
        })
    return plan


def patch(url: str, key: str, path: str, payload: dict) -> None:
    import urllib.request

    req = urllib.request.Request(
        "%s/rest/v1/%s" % (url, path),
        data=json.dumps(payload).encode("utf-8"),
        method="PATCH",
        headers={"apikey": key, "Authorization": "Bearer " + key,
                 "Content-Type": "application/json", "Prefer": "return=minimal"},
    )
    urllib.request.urlopen(req, timeout=60).close()


MARK = "reconcile-childless-decompositions"


def apply_entry(url: str, key: str, entry: dict) -> None:
    verdict = entry["verdict"]
    if verdict == RELINK:
        for child_id in entry["children"]:
            patch(url, key, "tasks?id=eq.%s" % child_id,
                  {"parent_task_id": entry["id"]})
    elif verdict == DONE_BY_SUCCESSION:
        patch(url, key, "tasks?id=eq.%s" % entry["id"],
              {"state": "DONE", "updated_at": "now()",
               "note": "%s: %s" % (MARK, entry["detail"])})
    elif verdict == REQUEUE_PARENT:
        patch(url, key, "tasks?id=eq.%s" % entry["id"],
              {"state": "QUEUED", "updated_at": "now()",
               "note": "%s: %s" % (MARK, entry["detail"])})


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--env", default=ENV)
    ap.add_argument("--apply", action="store_true",
                    help="write the plan (default is dry-run)")
    ap.add_argument("--verdict", help="only act on one verdict")
    ap.add_argument("--limit", type=int, default=0,
                    help="cap how many rows are written (0 = no cap)")
    ap.add_argument("--json", action="store_true", dest="as_json")
    args = ap.parse_args()

    url, key = load_config(args.env)

    parents = fetch_all(url, key,
                        "tasks?select=id,slug,project_id,note&state=eq.DECOMPOSED")
    all_tasks = fetch_all(
        url, key, "tasks?select=id,slug,project_id,state,parent_task_id")

    plan = build_plan(parents, all_tasks)
    if args.verdict:
        plan = [e for e in plan if e["verdict"] == args.verdict]

    counts = collections.Counter(e["verdict"] for e in plan)
    if args.as_json:
        print(json.dumps({"counts": dict(counts), "plan": plan}, indent=2))
    else:
        print("DECOMPOSED parents examined: %d" % len(parents))
        for verdict, n in counts.most_common():
            print("  %-22s %d" % (verdict, n))
        print()
        for entry in plan[:40]:
            if entry["verdict"] == LEAVE:
                continue
            print("  %-16s %-58s %s"
                  % (entry["verdict"], entry["slug"][:58], entry["detail"][:88]))

    # REVIEW_SUCCESSOR_TERMINAL is excluded unless the operator names it with
    # --verdict. It is the largest bucket and the only one where the evidence
    # does not point at an answer, so it must never ride along with a bare
    # --apply.
    if args.verdict:
        actionable = [e for e in plan if e["verdict"] != LEAVE]
    else:
        actionable = [e for e in plan if e["verdict"] in AUTO_APPLY]

    held = sum(1 for e in plan if e["verdict"] == REVIEW_SUCCESSOR_TERMINAL)
    if held and not args.verdict:
        print("\n%d parent(s) held back as %s — their successor batch was "
              "quarantined or closed. Requeuing them would revive work a human "
              "chose to retire. Inspect with:\n"
              "    %s --verdict %s"
              % (held, REVIEW_SUCCESSOR_TERMINAL,
                 os.path.basename(__file__), REVIEW_SUCCESSOR_TERMINAL))

    if not args.apply:
        print("\nDRY RUN — nothing written. %d row group(s) would change. "
              "Re-run with --apply to write." % len(actionable))
        return 0

    if args.limit:
        actionable = actionable[:args.limit]
    for entry in actionable:
        apply_entry(url, key, entry)
    print("\napplied %d row group(s)." % len(actionable))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
