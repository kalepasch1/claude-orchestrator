#!/usr/bin/env python3
"""Report why the executor claim query returned nothing.

A dependency-starved queue and a finished queue produce the identical signal —
zero claimable rows — and the executor skill maps that signal to "work
complete". QUEUE-DEADLOCK-2026-08-25.md documents the result: sixteen executors
reporting clean runs against a queue that had not moved in six weeks. Its first
recommendation is to make the claim step distinguish `queued = 0` from
`claimable = 0` and alert on the second. This is that check.

It also catches a second, quieter way a task disappears. Every executor claim
CTE inner-joins projects:

    FROM tasks t JOIN projects p2 ON p2.id = t.project_id

so a row with `project_id IS NULL` is dropped from every candidate set
permanently. It stays QUEUED, it inflates the QUEUED total the P1-queue-clearance
playbook measures, and no zombie release touches it because it never reaches
RUNNING. Verified 2026-08-25: two such rows, both hourly guardrail-8 log entries
whose 19:57 UTC sibling carried a project_id and was claimed normally.

Read-only. It issues SELECTs and changes nothing.

Exit codes:
    0  queue is genuinely empty, or has claimable work
    2  queued > 0 and claimable == 0 — deadlock, not completion
"""

from __future__ import annotations

import argparse
import json
import re
import os
import sys
import urllib.parse
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV = os.path.join(REPO, "runner", ".env")

# Kept identical to runner/db.py::_DEP_SATISFYING_STATES. This list used to be
# ("DONE", "MERGED"), which made queue_health STRICTER than the claim path it is
# supposed to describe: the runner honours DEPLOYED_AND_VERIFIED, so every task
# waiting on one was reported "blocked" while being perfectly claimable. A health
# check that disagrees with the thing it checks generates false deadlocks and
# trains people to ignore it.
SATISFIED_STATES = ("DONE", "MERGED", "DEPLOYED_AND_VERIFIED")

#: Terminal states a dependency can sit in forever. An edge pointing at one of
#: these is not "waiting", it is dead, and the difference is the whole point of
#: the check: a blocked queue drains, a deadlocked one does not.
DEAD_END_STATES = ("SUPERSEDED", "CLOSED", "QUARANTINED", "PHANTOM_UNVERIFIED")


def load_config(env_path: str = ENV) -> tuple:
    cfg = {}
    with open(env_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            cfg[key.strip()] = value.strip().strip('"').strip("'")

    url = cfg.get("SUPABASE_URL", "").rstrip("/")
    key = (cfg.get("SUPABASE_SERVICE_KEY")
           or cfg.get("SUPABASE_SERVICE_ROLE_KEY")
           or cfg.get("SUPABASE_KEY"))
    if not url or not key:
        sys.exit("missing SUPABASE_URL / service key in runner/.env")
    return url, key


def rest(url: str, key: str, path: str):
    req = urllib.request.Request(
        "%s/rest/v1/%s" % (url, path),
        headers={"apikey": key, "Authorization": "Bearer " + key,
                 "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as response:
        return json.load(response)


def fetch_all(url: str, key: str, path: str, page: int = 1000) -> list:
    rows, offset = [], 0
    while True:
        sep = "&" if "?" in path else "?"
        batch = rest(url, key, "%s%slimit=%d&offset=%d" % (path, sep, page, offset))
        rows.extend(batch)
        if len(batch) < page:
            return rows
        offset += page


# ---------------------------------------------------------------------------
# pure classification — unit-testable without a database
# ---------------------------------------------------------------------------


def deps_of(task: dict) -> list:
    return [d for d in (task.get("deps") or []) if d]


def blocking_deps(task: dict, satisfied_slugs_by_project: dict) -> list:
    """Deps of `task` that are not satisfied within the task's own project."""
    satisfied = satisfied_slugs_by_project.get(task.get("project_id"), set())
    return [d for d in deps_of(task) if d not in satisfied]


def build_dead_ends(all_tasks: list) -> dict:
    """{project_id: {slug: why}} for deps that can never become satisfying.

    Three shapes, all of which look identical to "not finished yet" from the
    claim loop:

      * a terminal non-satisfying state (SUPERSEDED / CLOSED / QUARANTINED /
        PHANTOM_UNVERIFIED) -- nothing further will happen to it;
      * DECOMPOSED with no children, so the work it was split into does not
        exist and nothing can ever finish on its behalf. Measured 2026-09-09:
        5,015 of 5,316 DECOMPOSED parents were in exactly this state;
      * DECOMPOSED via a backlog-compactor collapse whose target task is not in
        the queue at all (804 of them).

    A DECOMPOSED parent WITH children is deliberately absent: it resolves as its
    children land, and calling it dead would be wrong the moment the last one does.
    Likewise a collapse pointing at a target that still exists -- unfinished is
    not the same as unreachable.
    """
    has_children = {t.get("parent_task_id") for t in all_tasks if t.get("parent_task_id")}
    by_key = {(t.get("project_id"), t.get("slug")) for t in all_tasks}

    dead: dict = {}
    for t in all_tasks:
        state = str(t.get("state") or "")
        pid, slug = t.get("project_id"), t.get("slug")
        why = None
        if state in DEAD_END_STATES:
            why = state
        elif state == "DECOMPOSED" and t.get("id") not in has_children:
            target = collapse_target(t.get("note"))
            if target and (pid, target) not in by_key:
                why = "DECOMPOSED, collapsed into %s which does not exist" % target
            elif target:
                why = None  # resolves when the collapse target lands
            else:
                why = "DECOMPOSED with no children"
        if why:
            dead.setdefault(pid, {})[slug] = why
    return dead


COLLAPSE_RE = re.compile(r"backlog-compactor:\s*collapsed into\s+([A-Za-z0-9._-]+)")


def collapse_target(note):
    """Slug a backlog-compactor note folded this task into, else None."""
    if not note:
        return None
    m = COLLAPSE_RE.search(str(note))
    return m.group(1) if m else None


def classify_task(task: dict, project_ids: set,
                  satisfied_slugs_by_project: dict,
                  dead_ends_by_project: dict = None) -> tuple:
    """Return (verdict, detail) for one QUEUED task.

    verdict is one of: claimable, orphan_project, blocked, unsatisfiable,
    speculative.

    "blocked" and "unsatisfiable" were the same bucket until 2026-09-09, and
    conflating them is what let the operator drop-box sit dead for a month: all
    6 QUEUED dropbox-* tasks were reported as ordinary "blocked" work waiting
    its turn, when in fact every one of them waited on a DECOMPOSED parent with
    no children -- a state that cannot become satisfying no matter how long the
    fleet runs. Blocked work drains. Unsatisfiable work needs a human or a
    reconciler, and should be loud.
    """
    if task.get("kind") == "speculative":
        return "speculative", "kind=speculative is excluded from claiming"

    project_id = task.get("project_id")
    if project_id is None:
        return ("orphan_project",
                "project_id IS NULL — the claim CTE inner-joins projects, so "
                "this row can never be claimed by any executor")
    if project_id not in project_ids:
        return ("orphan_project",
                "project_id %s has no row in projects — dropped by the claim "
                "join" % project_id)

    blocking = blocking_deps(task, satisfied_slugs_by_project)
    if blocking:
        dead = [d for d in blocking if d in (dead_ends_by_project or {}).get(project_id, {})]
        if dead:
            detail = "; ".join(
                "%s is %s" % (d, dead_ends_by_project[project_id][d]) for d in sorted(dead))
            return ("unsatisfiable",
                    "depends on work that can never reach a satisfying state: " + detail)
        return "blocked", "waiting on %s" % ", ".join(sorted(blocking))

    return "claimable", ""


def summarize(tasks: list, project_ids: set,
              satisfied_slugs_by_project: dict,
              dead_ends_by_project: dict = None) -> dict:
    buckets: dict = {"claimable": [], "orphan_project": [], "blocked": [],
                     "unsatisfiable": [], "speculative": []}
    for task in tasks:
        verdict, detail = classify_task(task, project_ids,
                                        satisfied_slugs_by_project,
                                        dead_ends_by_project)
        buckets[verdict].append({"slug": task.get("slug"), "detail": detail})

    return {
        "queued": len(tasks),
        "claimable": len(buckets["claimable"]),
        "blocked": len(buckets["blocked"]),
        "unsatisfiable": len(buckets["unsatisfiable"]),
        "orphan_project": len(buckets["orphan_project"]),
        "speculative": len(buckets["speculative"]),
        "deadlocked": len(tasks) > 0 and not buckets["claimable"],
        "buckets": buckets,
    }


# ---------------------------------------------------------------------------
# entrypoint
# ---------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", default=ENV)
    ap.add_argument("--json", action="store_true", dest="as_json")
    ap.add_argument("--assert-satisfiable", action="store_true",
                    help="exit non-zero if any QUEUED task depends on work that "
                         "can never reach a satisfying state")
    ap.add_argument("--limit", type=int, default=15,
                    help="how many example slugs to print per bucket")
    args = ap.parse_args()

    url, key = load_config(args.env)

    projects = rest(url, key, "projects?select=id,name")
    project_ids = {p["id"] for p in projects}

    queued = fetch_all(url, key, "tasks?select=slug,project_id,kind,deps&state=eq.QUEUED")
    all_tasks = fetch_all(
        url, key, "tasks?select=id,slug,state,note,project_id,parent_task_id")

    by_project: dict = {}
    for row in all_tasks:
        if str(row.get("state") or "") in SATISFIED_STATES:
            by_project.setdefault(row["project_id"], set()).add(row["slug"])

    report = summarize(queued, project_ids, by_project, build_dead_ends(all_tasks))

    if args.as_json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print("queued          %d" % report["queued"])
        print("  claimable     %d" % report["claimable"])
        print("  blocked       %d" % report["blocked"])
        print("  unsatisfiable %d" % report["unsatisfiable"])
        print("  orphan project%d" % report["orphan_project"])
        print("  speculative   %d" % report["speculative"])
        for name in ("orphan_project", "unsatisfiable", "blocked"):
            rows = report["buckets"][name]
            if not rows:
                continue
            print("\n%s (%d):" % (name, len(rows)))
            for row in rows[:args.limit]:
                print("  %-70s %s" % (row["slug"], row["detail"][:90]))
            if len(rows) > args.limit:
                print("  ... and %d more" % (len(rows) - args.limit))

        if report["deadlocked"]:
            print("\nDEADLOCK: %d task(s) queued, none claimable. This is not an "
                  "empty queue and must not be reported as a clean run."
                  % report["queued"], file=sys.stderr)

    if report["deadlocked"]:
        return 2
    if args.assert_satisfiable and report["unsatisfiable"]:
        # Exit 1, distinct from the exit 2 a full deadlock uses: a queue can be
        # draining normally and still carry dead edges, and the two need
        # different responses. This is the assertion the drop-box deadlock
        # needed and did not have -- it would have failed loudly on 2026-08-07
        # instead of letting 6 operator tasks sit at attempt=0 for a month.
        print("\nFAIL: %d QUEUED task(s) depend on work that can never reach a "
              "satisfying state." % report["unsatisfiable"], file=sys.stderr)
        print("Repair with: python3 tools/reconcile_childless_decompositions.py --apply",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
