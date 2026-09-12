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
import os
import sys
import urllib.parse
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV = os.path.join(REPO, "runner", ".env")

SATISFIED_STATES = ("DONE", "MERGED")


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


def classify_task(task: dict, project_ids: set,
                  satisfied_slugs_by_project: dict) -> tuple:
    """Return (verdict, detail) for one QUEUED task.

    verdict is one of: claimable, orphan_project, blocked, speculative.
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
        return "blocked", "waiting on %s" % ", ".join(sorted(blocking))

    return "claimable", ""


def summarize(tasks: list, project_ids: set,
              satisfied_slugs_by_project: dict) -> dict:
    buckets: dict = {"claimable": [], "orphan_project": [], "blocked": [],
                     "speculative": []}
    for task in tasks:
        verdict, detail = classify_task(task, project_ids,
                                        satisfied_slugs_by_project)
        buckets[verdict].append({"slug": task.get("slug"), "detail": detail})

    return {
        "queued": len(tasks),
        "claimable": len(buckets["claimable"]),
        "blocked": len(buckets["blocked"]),
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
    ap.add_argument("--limit", type=int, default=15,
                    help="how many example slugs to print per bucket")
    args = ap.parse_args()

    url, key = load_config(args.env)

    projects = rest(url, key, "projects?select=id,name")
    project_ids = {p["id"] for p in projects}

    queued = fetch_all(url, key, "tasks?select=slug,project_id,kind,deps&state=eq.QUEUED")
    satisfied = fetch_all(
        url, key,
        "tasks?select=slug,project_id&state=in.(%s)" % ",".join(SATISFIED_STATES),
    )

    by_project: dict = {}
    for row in satisfied:
        by_project.setdefault(row["project_id"], set()).add(row["slug"])

    report = summarize(queued, project_ids, by_project)

    if args.as_json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print("queued          %d" % report["queued"])
        print("  claimable     %d" % report["claimable"])
        print("  blocked       %d" % report["blocked"])
        print("  orphan project%d" % report["orphan_project"])
        print("  speculative   %d" % report["speculative"])
        for name in ("orphan_project", "blocked"):
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

    return 2 if report["deadlocked"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
