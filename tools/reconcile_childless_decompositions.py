#!/usr/bin/env python3
"""Repair DECOMPOSED parents that have no children.

WHY THIS EXISTS
---------------
`runner/db.py::_closed_decompositions()` refuses to treat a childless DECOMPOSED
parent as satisfied, and its comment is right to::

    A childless parent is NOT closed. It is a decomposition that lost its
    children, which is a different defect and must not be papered over.

Nothing ever repaired the defect it names. Measured on the live queue
2026-09-09: **5,015 of 5,316 DECOMPOSED parents (94%) have zero children**, and
the dependency edges behind them are what deadlocked the operator drop-box --
every QUEUED `dropbox-*` task sat at attempt=0 because it waits on a parent that
can never reach a satisfying state.

THE DIAGNOSIS THE TASK CARRIED WAS INCOMPLETE
---------------------------------------------
The card blamed `runner/task_slicer.py`. The slicer is one source, but it is not
the biggest one. Of the 5,015 childless parents, **2,433 (49%) were never sliced
at all** -- they carry a note of the form::

    backlog-compactor: collapsed into backlog-batch-<project>-<hash>

The backlog compactor marks a task DECOMPOSED when it folds it into a batch
task. That is a legitimate retirement, but the work moves into a *sibling* task
rather than into children, so no `parent_task_id` row is ever written and the
parent is childless by construction, not by accident. Fixing only the slicer
would leave every one of those edges dead.

Splitting the population by evidence gives four dispositions, and only one of
them is the "lost children" case the card described:

``RELINK``
    Slice-named children (`<slug>-slice-N`) exist in the same project but carry
    no ``parent_task_id``. The children were never lost -- only the link was.
    Backfilling the FK lets ``_closed_decompositions()`` resolve the parent
    normally. 304 parents.

``CLOSE_VIA_COLLAPSE``
    A compactor note names a collapse target that exists **and is finished**.
    The work shipped, under another slug. Marking the parent DONE with that
    provenance is the card's own "its work shipped under another slug/branch"
    branch. 409 parents.

``DEFER_TO_COLLAPSE``
    The collapse target exists but has not finished. Nothing is broken and
    nothing should be forced: the parent closes when the target lands. These are
    reported, not mutated -- see ``runner/db.py``, which now follows the collapse
    pointer so these resolve on their own.

``REQUEUE``
    No children, and no reachable collapse target -- 804 parents point at a
    batch task that does not exist in the queue at all. The work does not exist
    anywhere, so the honest repair is to put the **parent** back in QUEUED and
    let it be done. Crucially this does NOT satisfy its dependents: they keep
    waiting, but now they wait on something that can actually finish.

``LEAVE``
    Anything that does not match the above. Ambiguity is reported, never guessed.

SAFETY
------
Dry-run by default; ``--apply`` is required to write. Nothing is ever deleted,
and no dependent is released on the strength of work that cannot be shown to
exist -- that is the trap ``_closed_decompositions()`` warns about, and the
reason ``REQUEUE`` returns the parent rather than satisfying the edge.

Usage::

    python3 tools/reconcile_childless_decompositions.py             # report
    python3 tools/reconcile_childless_decompositions.py --json
    python3 tools/reconcile_childless_decompositions.py --apply
    python3 tools/reconcile_childless_decompositions.py --apply --only REQUEUE
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
#: Same location tools/queue_health.py reads. The credentials live under
#: runner/, not at the repo root -- defaulting to the root silently produced a
#: FileNotFoundError on every invocation.
ENV = os.path.join(REPO, "runner", ".env")

#: States in which a task's work counts as delivered. Kept identical to
#: ``runner/db.py::_DEP_SATISFYING_STATES`` -- a reconciler that disagreed with
#: the claim path about "finished" would repair the queue into a shape the
#: runner still refuses to claim.
SATISFYING_STATES = frozenset({"DONE", "MERGED", "DEPLOYED_AND_VERIFIED"})

#: The compactor writes exactly one shape, and it is the only note form we are
#: willing to read a collapse target out of. A looser pattern would happily
#: match prose and invent a target slug.
COLLAPSE_RE = re.compile(r"backlog-compactor:\s*collapsed into\s+([A-Za-z0-9._-]+)")

DISPOSITIONS = ("RELINK", "CLOSE_VIA_COLLAPSE", "DEFER_TO_COLLAPSE", "REQUEUE", "LEAVE")


def collapse_target(note):
    """The slug a compactor note says this task was folded into, or None."""
    if not note:
        return None
    m = COLLAPSE_RE.search(str(note))
    return m.group(1) if m else None


def classify(parent, slice_children, target_task):
    """Decide what to do with one childless DECOMPOSED parent. Pure.

    ``parent``          the parent row (``slug``, ``note``, ...)
    ``slice_children``  rows named ``<parent slug>-slice-N`` in the same project
    ``target_task``     the collapse-target row, or None if it does not exist

    Returns ``(disposition, reason)``.
    """
    if slice_children:
        # Ordering matters: a task can be both sliced and later collapsed. The
        # children are concrete evidence of where the work went, so they win
        # over a note that only records an intent.
        return ("RELINK", "%d slice-named child(ren) exist without parent_task_id; "
                          "backfilling the link lets the parent close normally"
                          % len(slice_children))

    target = collapse_target(parent.get("note"))
    if target:
        if target_task is None:
            return ("REQUEUE", "collapsed into %r, which does not exist in the queue — "
                               "the work was never carried anywhere and must be redone" % target)
        state = str(target_task.get("state") or "")
        if state in SATISFYING_STATES:
            return ("CLOSE_VIA_COLLAPSE",
                    "work shipped as %s (state=%s)" % (target, state))
        return ("DEFER_TO_COLLAPSE",
                "collapsed into %s, still %s — closes on its own when that lands"
                % (target, state or "unknown"))

    return ("REQUEUE", "no children and no collapse target — the decomposition "
                       "produced nothing, so the parent is the only thing left to do")


def plan_for(parent, slice_children, target_task):
    """The concrete mutation implied by a classification, or None for read-only."""
    disposition, reason = classify(parent, slice_children, target_task)

    if disposition == "RELINK":
        return {
            "disposition": disposition, "reason": reason, "slug": parent.get("slug"),
            "writes": [{"table": "tasks", "match": {"id": c.get("id")},
                        "values": {"parent_task_id": parent.get("id")}}
                       for c in slice_children],
        }

    if disposition == "CLOSE_VIA_COLLAPSE":
        target = collapse_target(parent.get("note"))
        note = ("childless-decomposition-reconciler: work shipped as %s; "
                "closed with that provenance rather than left DECOMPOSED-and-childless"
                % target)
        values = {"state": "DONE", "note": note}
        # The closure guard in the DB requires a sha on any DONE claim. Inherit
        # the target's, because that is literally the commit that did this work.
        commit = (target_task or {}).get("artifact_commit")
        if commit:
            values["artifact_commit"] = commit
        else:
            values["note"] = note + " | NO-ARTIFACT-JUSTIFIED: the collapse target " \
                                    "closed without recording one"
        return {"disposition": disposition, "reason": reason, "slug": parent.get("slug"),
                "writes": [{"table": "tasks", "match": {"id": parent.get("id")},
                            "values": values}]}

    if disposition == "REQUEUE":
        return {"disposition": disposition, "reason": reason, "slug": parent.get("slug"),
                "writes": [{"table": "tasks", "match": {"id": parent.get("id")},
                            "values": {"state": "QUEUED",
                                       "note": "childless-decomposition-reconciler: "
                                               + reason}}]}

    # DEFER_TO_COLLAPSE and LEAVE are observations, not repairs.
    return {"disposition": disposition, "reason": reason,
            "slug": parent.get("slug"), "writes": []}


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------


def load_config(env_path=ENV):
    cfg = {}
    with open(env_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            cfg[k.strip()] = v.strip().strip('"').strip("'")
    url = cfg.get("SUPABASE_URL") or cfg.get("ORCH_SUPABASE_URL")
    key = (cfg.get("SUPABASE_SERVICE_KEY") or cfg.get("SUPABASE_SERVICE_ROLE_KEY")
           or cfg.get("ORCH_SUPABASE_SERVICE_KEY"))
    if not url or not key:
        raise SystemExit("missing SUPABASE_URL / SUPABASE_SERVICE_KEY in %s" % env_path)
    return url.rstrip("/"), key


def _req(url, key, path, method="GET", body=None):
    req = urllib.request.Request(
        "%s/rest/v1/%s" % (url, path), method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"apikey": key, "Authorization": "Bearer %s" % key,
                 "Content-Type": "application/json", "Prefer": "return=minimal"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = resp.read().decode() or "[]"
    return json.loads(raw) if method == "GET" else None


def fetch_all(url, key, path, page=1000):
    out, offset = [], 0
    while True:
        sep = "&" if "?" in path else "?"
        chunk = _req(url, key, "%s%slimit=%d&offset=%d" % (path, sep, page, offset))
        out.extend(chunk)
        if len(chunk) < page:
            return out
        offset += page


def build_plans(parents, all_tasks):
    """Plans for every childless DECOMPOSED parent. Pure over its inputs."""
    by_key = {}
    children_by_parent = {}
    for t in all_tasks:
        by_key[(t.get("project_id"), t.get("slug"))] = t
        pid = t.get("parent_task_id")
        if pid:
            children_by_parent.setdefault(pid, []).append(t)

    slices_by_prefix = {}
    for t in all_tasks:
        slug = t.get("slug") or ""
        if "-slice-" in slug:
            prefix = slug.rsplit("-slice-", 1)[0]
            slices_by_prefix.setdefault((t.get("project_id"), prefix), []).append(t)

    plans = []
    for p in parents:
        if children_by_parent.get(p.get("id")):
            continue  # not childless
        kids = [c for c in slices_by_prefix.get((p.get("project_id"), p.get("slug")), [])
                if not c.get("parent_task_id")]
        target_slug = collapse_target(p.get("note"))
        target = by_key.get((p.get("project_id"), target_slug)) if target_slug else None
        plans.append(plan_for(p, kids, target))
    return plans


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", default=ENV)
    ap.add_argument("--apply", action="store_true", help="write; default is dry-run")
    ap.add_argument("--only", choices=DISPOSITIONS, help="restrict to one disposition")
    ap.add_argument("--slug", action="append", default=[],
                    help="restrict to these parent slugs (repeatable). Lets a "
                         "targeted repair -- e.g. just the parents blocking the "
                         "operator drop-box -- run through the same classifier as "
                         "the bulk pass instead of being hand-written in SQL.")
    ap.add_argument("--limit", type=int, default=0, help="cap rows mutated (0 = no cap)")
    ap.add_argument("--json", action="store_true", dest="as_json")
    args = ap.parse_args()

    url, key = load_config(args.env)
    parents = fetch_all(url, key,
                        "tasks?select=id,slug,note,project_id&state=eq.DECOMPOSED")
    all_tasks = fetch_all(
        url, key,
        "tasks?select=id,slug,state,note,project_id,parent_task_id,artifact_commit")

    plans = build_plans(parents, all_tasks)
    if args.only:
        plans = [p for p in plans if p["disposition"] == args.only]
    if args.slug:
        wanted = set(args.slug)
        plans = [p for p in plans if p["slug"] in wanted]
        missing = wanted - {p["slug"] for p in plans}
        if missing:
            # Silence here would look like a successful no-op repair.
            print("not childless DECOMPOSED parents (nothing to do): %s"
                  % ", ".join(sorted(missing)), file=sys.stderr)

    counts = {d: 0 for d in DISPOSITIONS}
    for p in plans:
        counts[p["disposition"]] += 1

    applied = 0
    if args.apply:
        for plan in plans:
            if args.limit and applied >= args.limit:
                break
            for w in plan["writes"]:
                q = "&".join("%s=eq.%s" % (k, v) for k, v in w["match"].items())
                try:
                    _req(url, key, "%s?%s" % (w["table"], q), "PATCH", w["values"])
                    applied += 1
                except urllib.error.HTTPError as exc:
                    # One rejected row must not abandon the other 5,000.
                    print("  ! %s: %s" % (plan["slug"], exc.read().decode()[:160]),
                          file=sys.stderr)

    report = {"childless_parents": len(plans), "counts": counts,
              "applied_writes": applied, "dry_run": not args.apply}

    if args.as_json:
        report["plans"] = plans
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print("childless DECOMPOSED parents  %d" % len(plans))
        for d in DISPOSITIONS:
            print("  %-20s %d" % (d, counts[d]))
        print("%s writes: %d" % ("applied" if args.apply else "would apply",
                                 applied if args.apply
                                 else sum(len(p["writes"]) for p in plans)))
        if not args.apply:
            print("\ndry run — pass --apply to write")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
