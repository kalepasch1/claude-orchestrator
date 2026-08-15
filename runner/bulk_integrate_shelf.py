#!/usr/bin/env python3
"""bulk_integrate_shelf.py - drain the shelf of agent branches that already contain work.

THE PROBLEM
Every executor pass pushes `agent/<slug>` branches with real commits on them. When the merge
train later fails a branch (rebase conflict, flaky test, missing card) the work does not
disappear — it sits on the shelf, committed and pushed, ahead of master forever. Re-queueing
those tasks re-runs the *agent*, which burns tokens rewriting code that is already written and
usually produces a slightly different diff that conflicts with the shelved one.

WHAT THIS DOES
Enumerates every `agent/*` branch that is ahead of the base and carries a non-empty diff, then
feeds each one into the EXISTING integrate-existing path — merge_train.ensure_integration_card()
— which is the same door runner.py uses when it detects a branch ahead of base and skips the
agent (see runner.py "[integrate-existing]"). No agent is ever re-run from here.

REBASE-STACK ORDERING
Branches that touch overlapping files are related: merging them in arbitrary order means the
second, third and fourth all rebase onto a base that just moved under them, and you get a
conflict storm. Branches are grouped into stacks by shared file footprint (union-find) and
emitted stack-contiguously, oldest commit first within a stack, so related work lands as a
sequence and unrelated work never interleaves with it.

GUARANTEES
  * Idempotent - ensure_integration_card() de-dupes on slug, so re-running queues nothing new.
  * --dry-run  - prints the plan in rebase-stack order and touches nothing.
  * Fail-soft  - a branch that errors is recorded and skipped; the sweep continues.

Usage:
    python3 runner/bulk_integrate_shelf.py --dry-run
    python3 runner/bulk_integrate_shelf.py --base master --limit 25
"""
import argparse
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

REPO_DEFAULT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRANCH_PREFIX = "agent/"


def _git(repo, *args, timeout=60):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True,
                          encoding="utf-8", errors="replace", timeout=timeout)


def _out(repo, *args, timeout=60):
    r = _git(repo, *args, timeout=timeout)
    return r.stdout.strip() if r.returncode == 0 else ""


def resolve_base(repo, requested=None):
    """Prefer the caller's base, else the repo's actual default branch, else master."""
    if requested:
        return requested
    for candidate in ("origin/master", "origin/main", "master", "main"):
        if _git(repo, "rev-parse", "--verify", candidate).returncode == 0:
            return candidate
    return "master"


def resolve_project(repo, requested=None):
    """Fail-soft project name: explicit flag > projects table > directory basename."""
    if requested:
        return requested
    try:
        import db
        rows = db.select("projects", {"select": "name,repo_path"}) or []
        real = os.path.realpath(repo)
        for row in rows:
            if os.path.realpath(str(row.get("repo_path") or "")) == real:
                return row["name"]
    except Exception:
        pass
    return os.path.basename(os.path.abspath(repo))


def _branch_refs(repo):
    """Every agent/* branch, local first, then remotes we have no local copy of.

    A slug can exist as both refs/heads/agent/x and refs/remotes/origin/agent/x. The local
    ref wins: it is what the merge train will resolve, and preferring the remote would hide
    a local branch that is further ahead.
    """
    seen = {}
    fmt = "%(refname:short)"
    for ref in ("refs/heads/" + BRANCH_PREFIX, "refs/remotes/origin/" + BRANCH_PREFIX):
        out = _out(repo, "for-each-ref", "--format=" + fmt, ref + "**")
        for line in out.splitlines():
            name = line.strip()
            if not name:
                continue
            slug = name.split(BRANCH_PREFIX, 1)[1] if BRANCH_PREFIX in name else name
            seen.setdefault(slug, name)
    return seen


def _changed_files(repo, branch, base):
    out = _out(repo, "diff", "--name-only", f"{base}...{branch}")
    return sorted(f for f in out.splitlines() if f.strip())


def list_shelf_branches(repo, base):
    """Agent branches that are ahead of base AND carry a real diff.

    "Ahead" alone is not enough: a branch can be ahead by an empty or revert-only commit and
    integrating it wastes a full train pass. A branch already merged (tip is an ancestor of
    base) is skipped, which is what makes the whole sweep idempotent across runs.
    """
    shelf = []
    for slug, branch in sorted(_branch_refs(repo).items()):
        try:
            if _git(repo, "merge-base", "--is-ancestor", branch, base).returncode == 0:
                continue  # already integrated
            counts = _out(repo, "rev-list", "--left-right", "--count", f"{base}...{branch}")
            behind, ahead = (counts.split() + ["0", "0"])[:2]
            ahead = int(ahead or 0)
            if ahead <= 0:
                continue
            files = _changed_files(repo, branch, base)
            if not files:
                continue  # ahead, but nothing to merge
            shelf.append({
                "slug": slug,
                "branch": branch,
                "ahead": ahead,
                "behind": int(behind or 0),
                "files": files,
                "tip": _out(repo, "rev-parse", branch)[:12],
                "committed_at": _out(repo, "log", "-1", "--format=%ct", branch) or "0",
            })
        except Exception as e:  # fail-soft per branch
            shelf.append({"slug": slug, "branch": branch, "error": str(e),
                          "ahead": 0, "behind": 0, "files": [], "tip": "", "committed_at": "0"})
    return shelf


def rebase_stack_order(shelf):
    """Group branches that touch overlapping files, then emit stack by stack.

    Union-find over the file footprint: two branches that touch any file in common belong to
    the same stack. Within a stack, oldest commit first (that is the order the work was
    actually written, so it is the order least likely to conflict). Stacks are emitted
    largest first — draining the biggest interdependent cluster while the base is quiet is
    worth more than trickling singletons in ahead of it. Ties break on slug for determinism.
    """
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    owner = {}
    for item in shelf:
        slug = item["slug"]
        find(slug)
        for path in item.get("files") or []:
            if path in owner:
                union(owner[path], slug)
            else:
                owner[path] = slug

    stacks = {}
    for item in shelf:
        stacks.setdefault(find(item["slug"]), []).append(item)

    def sort_key(item):
        try:
            ts = int(item.get("committed_at") or 0)
        except (TypeError, ValueError):
            ts = 0
        return (ts, item["slug"])

    ordered_stacks = []
    for root, members in stacks.items():
        members.sort(key=sort_key)
        ordered_stacks.append((-len(members), sort_key(members[0]), members))
    ordered_stacks.sort(key=lambda s: (s[0], s[1]))

    out = []
    for index, (_, _, members) in enumerate(ordered_stacks):
        for position, item in enumerate(members):
            item = dict(item)
            item["stack"] = index
            item["stack_size"] = len(members)
            item["stack_position"] = position
            out.append(item)
    return out


def queue_for_integration(item, project, dry_run=False):
    """Hand ONE branch to the canonical integrate-existing path. Never runs an agent.

    Returns a result dict; never raises. ensure_integration_card() is itself idempotent
    (it de-dupes on slug against open merge-kind cards), so the worst case of a repeated
    sweep is a no-op rather than a duplicate card.
    """
    slug = item["slug"]
    if dry_run:
        return {"slug": slug, "action": "would-queue"}
    try:
        import merge_train
        created = merge_train.ensure_integration_card(
            project, slug, kind="integrate",
            title=f"integrate shelved branch {item['branch']}",
            why=(f"{item['branch']} is {item['ahead']} commit(s) ahead of base with "
                 f"{len(item['files'])} changed file(s) at {item['tip']}; queued by "
                 f"bulk_integrate_shelf without re-running the agent"),
            detail=json.dumps({"branch": item["branch"], "tip": item["tip"],
                               "files": item["files"][:50],
                               "stack": item.get("stack"),
                               "stack_position": item.get("stack_position")}),
            decided_by="canonical-train:bulk-integrate-shelf")
        return {"slug": slug, "action": "queued" if created else "already-queued"}
    except Exception as e:  # fail-soft: one bad branch must not end the sweep
        return {"slug": slug, "action": "error", "error": str(e)}


def sweep(repo=None, base=None, project=None, dry_run=False, limit=0):
    repo = repo or REPO_DEFAULT
    base = resolve_base(repo, base)
    project = resolve_project(repo, project)
    shelf = [b for b in list_shelf_branches(repo, base) if not b.get("error")]
    ordered = rebase_stack_order(shelf)
    if limit and limit > 0:
        ordered = ordered[:limit]
    results = [queue_for_integration(item, project, dry_run=dry_run) for item in ordered]
    return {"repo": repo, "base": base, "project": project, "dry_run": bool(dry_run),
            "candidates": ordered, "results": results,
            "queued": sum(1 for r in results if r["action"] == "queued"),
            "already_queued": sum(1 for r in results if r["action"] == "already-queued"),
            "errors": sum(1 for r in results if r["action"] == "error")}


def _print_plan(report):
    ordered = report["candidates"]
    print(f"bulk_integrate_shelf: {len(ordered)} shelved branch(es) ahead of "
          f"{report['base']} in {report['project']}"
          + (" [DRY RUN]" if report["dry_run"] else ""))
    last_stack = None
    for item in ordered:
        if item["stack"] != last_stack:
            last_stack = item["stack"]
            print(f"  -- stack {item['stack']} ({item['stack_size']} branch(es)) --")
        print(f"    {item['branch']}  +{item['ahead']} commit(s)  "
              f"{len(item['files'])} file(s)  @{item['tip']}")
    if not report["dry_run"]:
        print(f"bulk_integrate_shelf: queued={report['queued']} "
              f"already_queued={report['already_queued']} errors={report['errors']}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", default=REPO_DEFAULT)
    ap.add_argument("--base", default=None, help="integration base (default: repo default branch)")
    ap.add_argument("--project", default=None, help="project name for the integration card")
    ap.add_argument("--dry-run", action="store_true", help="list the plan, change nothing")
    ap.add_argument("--limit", type=int,
                    default=int(os.environ.get("ORCH_BULK_SHELF_LIMIT", "25") or 25),
                    help="cap how many branches to queue (default 25; 0 = unlimited)")
    ap.add_argument("--json", action="store_true", help="emit the report as JSON")
    args = ap.parse_args(argv)

    report = sweep(repo=args.repo, base=args.base, project=args.project,
                   dry_run=args.dry_run, limit=args.limit)
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        _print_plan(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
