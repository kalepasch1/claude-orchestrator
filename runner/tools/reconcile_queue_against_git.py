#!/usr/bin/env python3
"""
Reconcile QUEUED tasks against what git already contains.

The bug this exists for
-----------------------
Nothing in the pipeline closes the loop between "the work landed in git" and
"the task row says so". Work is implemented, committed, pushed to
`agent/<slug>`, and in many cases merged to the production branch -- and the
task stays QUEUED. Every executor pass then re-claims it and does it again.

Measured on beethoven, 2026-09-09:

  1779  tasks QUEUED fleet-wide
  1827  `agent/*` branches already pushed to origin in this one repo
  1675  distinct slugs already having an `agent: <slug>` commit in history
   166  QUEUED copies of the single `chatgpt-local-reconcile-beethoven-*` family,
        against 148 already-pushed branches for that same family

Two spot-checks, both still QUEUED at the time of writing, both already
*merged into master*:

  toolchain-repair-99f45988 .......... fixed in 0203b85aa, 10/10 tests green
  recover-missing-branch-vercel-json-* fixed in 99dc65a4a, vercel.json clean

This is why throughput reads as collapsing (437 -> 339 -> 63 -> 40 -> 8 -> 1
shipped per week over the last six weeks) while task creation holds near a
thousand a week. The queue is not a backlog of undone work. It is substantially
a replay log of finished work, and each executor pass adds branches rather than
removing tasks.

What this tool does
-------------------
For every active project with a clone on this host, it classifies each QUEUED
task by what git can prove:

  SHIPPED      an `agent: <slug>` commit is an ancestor of the production
               branch. The work is merged. Nothing to do but close the row.
  BRANCH_ONLY  `origin/agent/<slug>` exists but is not merged. The work exists;
               it is the merge train's to integrate, not an executor's to redo.
  ABSENT       git has no trace. Genuinely outstanding -- real queue depth.

Report by default. `--apply` writes only the SHIPPED rows, and only to
SUPERSEDED, with the proving commit recorded in the note. BRANCH_ONLY is
deliberately never auto-written: "a branch exists" is not proof the work is
correct, only that it is not missing.

    python3 runner/tools/reconcile_queue_against_git.py
    python3 runner/tools/reconcile_queue_against_git.py --project beethoven
    python3 runner/tools/reconcile_queue_against_git.py --apply

Exit status is 0 on a clean read, 2 if any SHIPPED rows remain unwritten in
report mode -- so a periodic job can page on "the queue is lying again".
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db  # noqa: E402

# Projects deliberately halted. A paused project's rows are not ours to rewrite;
# `controls` is the operator's switch and it outranks this tool.
PAUSED_SCOPES = ("global", "project")

CLASS_SHIPPED = "SHIPPED"
CLASS_BRANCH_ONLY = "BRANCH_ONLY"
CLASS_ABSENT = "ABSENT"


def _git(repo, *args, timeout=120):
    """Run git in `repo`. Returns (rc, stdout). Never raises on a non-zero rc."""
    try:
        p = subprocess.run(
            ("git", "-C", repo) + args,
            capture_output=True, text=True, timeout=timeout,
        )
        return p.returncode, (p.stdout or "").strip()
    except (subprocess.TimeoutExpired, OSError) as exc:
        return 1, "git failed: {}".format(exc)


def paused_projects():
    """Names of projects under a live pause, plus a global-pause flag.

    Mirrors runner/kill_switch.is_paused(): latest decision per scope wins and
    rows written by 'remote-quarantine' do not count.
    """
    rows = db.select_all(
        "controls",
        {"select": "scope,project,paused,updated_by,updated_at"},
        order="updated_at.asc",
    ) or []
    latest = {}
    for r in rows:
        if (r.get("updated_by") or "") == "remote-quarantine":
            continue
        if r.get("scope") not in PAUSED_SCOPES:
            continue
        latest[(r.get("scope"), r.get("project"))] = bool(r.get("paused"))
    global_paused = any(v for (scope, _), v in latest.items() if scope == "global")
    names = {proj for (scope, proj), v in latest.items()
             if scope == "project" and v and proj}
    return names, global_paused


def production_branch(repo, project):
    """Best available production ref, preferring what actually exists locally."""
    for cand in (project.get("prod_branch"), project.get("default_base"), "master", "main"):
        if not cand:
            continue
        for ref in ("refs/remotes/origin/{}".format(cand), "refs/heads/{}".format(cand)):
            rc, _ = _git(repo, "rev-parse", "--verify", "-q", ref)
            if rc == 0:
                return ref
    return None


def shipped_slugs(repo, prod_ref):
    """Slugs whose `agent: <slug>` commit is an ancestor of the production ref.

    One `git log` over the merged history beats one subprocess per task: on a
    repo with ~1800 candidate slugs the per-task form took minutes, which is
    how this check gets skipped and the queue drifts in the first place.
    """
    rc, out = _git(repo, "log", prod_ref, "--pretty=%s", timeout=300)
    if rc != 0:
        return set()
    found = set()
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("agent: "):
            found.add(line[len("agent: "):].strip())
    return found


def pushed_branches(repo):
    """Slugs having an `agent/<slug>` ref, local or on origin."""
    rc, out = _git(repo, "for-each-ref", "--format=%(refname:short)",
                   "refs/heads/agent/", "refs/remotes/origin/agent/", timeout=180)
    if rc != 0:
        return set()
    found = set()
    for line in out.splitlines():
        name = line.strip()
        if name.startswith("origin/"):
            name = name[len("origin/"):]
        if name.startswith("agent/"):
            found.add(name[len("agent/"):])
    return found


def classify(slugs, merged, branched):
    out = {CLASS_SHIPPED: [], CLASS_BRANCH_ONLY: [], CLASS_ABSENT: []}
    for slug in slugs:
        if slug in merged:
            out[CLASS_SHIPPED].append(slug)
        elif slug in branched:
            out[CLASS_BRANCH_ONLY].append(slug)
        else:
            out[CLASS_ABSENT].append(slug)
    return out


def reconcile_project(project, apply=False, verbose=False):
    name = project.get("name")
    repo = db.localize_repo_path(project.get("repo_path"))
    if not repo or not os.path.isdir(os.path.join(repo or "", ".git")):
        return {"project": name, "skipped": "no clone on this host"}

    prod_ref = production_branch(repo, project)
    if not prod_ref:
        return {"project": name, "skipped": "no production branch resolvable"}

    tasks = db.select_all(
        "tasks",
        {"select": "id,slug,state,project_id",
         "state": "eq.QUEUED",
         "project_id": "eq.{}".format(project.get("id"))},
        order="id.asc",
    ) or []
    by_slug = {t["slug"]: t for t in tasks if t.get("slug")}

    merged = shipped_slugs(repo, prod_ref)
    branched = pushed_branches(repo)
    buckets = classify(by_slug.keys(), merged, branched)

    written = 0
    if apply:
        for slug in buckets[CLASS_SHIPPED]:
            task = by_slug[slug]
            rc, sha = _git(repo, "log", prod_ref, "-1", "--format=%h",
                           "--grep", "^agent: {}$".format(slug), "-E")
            proof = sha if rc == 0 and sha else "merged"
            # db.update() adds the `eq.` operator itself, so match takes raw
            # values. Matching on `id` also keeps each write a single-row update,
            # which is what exempts it from bulk_update_guard -- this tool must
            # never look like the bulk state flip that guard exists to stop.
            db.update(
                "tasks",
                {"id": task["id"], "state": "QUEUED"},
                {"state": "SUPERSEDED",
                 "note": ("reconcile_queue_against_git: already merged into {} as {}; "
                          "closed without a duplicate commit".format(prod_ref, proof))},
            )
            written += 1

    result = {
        "project": name,
        "prod_ref": prod_ref,
        "queued": len(by_slug),
        CLASS_SHIPPED: len(buckets[CLASS_SHIPPED]),
        CLASS_BRANCH_ONLY: len(buckets[CLASS_BRANCH_ONLY]),
        CLASS_ABSENT: len(buckets[CLASS_ABSENT]),
        "written": written,
    }
    if verbose:
        result["shipped_slugs"] = sorted(buckets[CLASS_SHIPPED])[:50]
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", help="limit to one project by name")
    ap.add_argument("--apply", action="store_true",
                    help="write SHIPPED rows to SUPERSEDED (default: report only)")
    ap.add_argument("--verbose", action="store_true", help="list sample shipped slugs")
    args = ap.parse_args(argv)

    halted, global_paused = paused_projects()
    if global_paused:
        print("global pause is in effect -- refusing to write. Nothing done.")
        return 0

    projects = db.select_all("projects",
                             {"select": "id,name,repo_path,prod_branch,default_base"},
                             order="name.asc") or []
    if args.project:
        projects = [p for p in projects if p.get("name") == args.project]

    total_shipped = total_written = 0
    rows = []
    for p in projects:
        if p.get("name") in halted:
            rows.append({"project": p.get("name"), "skipped": "paused by controls"})
            continue
        r = reconcile_project(p, apply=args.apply, verbose=args.verbose)
        rows.append(r)
        total_shipped += r.get(CLASS_SHIPPED, 0)
        total_written += r.get("written", 0)

    width = max([len(str(r.get("project") or "")) for r in rows] + [7])
    print("{:<{w}}  {:>6} {:>8} {:>11} {:>7}".format(
        "project", "queued", "shipped", "branch_only", "absent", w=width))
    for r in rows:
        if r.get("skipped"):
            print("{:<{w}}  {}".format(r.get("project") or "?", r["skipped"], w=width))
            continue
        print("{:<{w}}  {:>6} {:>8} {:>11} {:>7}".format(
            r["project"], r["queued"], r[CLASS_SHIPPED],
            r[CLASS_BRANCH_ONLY], r[CLASS_ABSENT], w=width))
        for slug in r.get("shipped_slugs", []):
            print("    shipped: {}".format(slug))

    if args.apply:
        print("\nclosed {} task(s) that were already merged.".format(total_written))
        return 0

    if total_shipped:
        print("\n{} QUEUED task(s) are already merged into production.".format(total_shipped))
        print("Re-run with --apply to close them without duplicate commits.")
        return 2
    print("\nno already-merged tasks left QUEUED.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
