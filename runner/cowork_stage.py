#!/usr/bin/env python3
"""
cowork_stage.py — the Cowork → Orchestrator staging bridge.
============================================================================
Lets any Cowork session (or a human) stage a backlog of build tasks into the
orchestrator's Supabase `tasks` queue, idempotently and safely. The Mac runner
then picks them up — one per isolated `{repo}-wt/{slug}` git worktree — gated by
the existing cost caps, kill switch, tests, and approval cards. Cowork never
runs Claude Code itself or touches a worktree; it only *stages* the work and the
governed runner executes it. That is the whole point: replicable, monitored,
QA'd, cost-capped autonomous building, channelled through one control plane.

Design
  - SAFE BY DEFAULT: dry-run unless `--commit` is passed. Dry-run validates the
    DAG (deps resolve, no cycles, contract-first) and prints exactly what would
    be inserted — no DB writes.
  - IDEMPOTENT: a (project, slug) that already exists in a non-terminal state is
    skipped, so re-staging the same backlog never duplicates work. (Mirrors the
    seed_demo.py pattern and the SPEC.md "upsert / ON CONFLICT DO NOTHING" rule.)
  - NATIVE: uses db.py (service-role REST) and the real `tasks`/`projects`
    schema, so staged rows are exactly what runner.claim_task expects.
  - CONTRACT-FIRST: enforces planner.py's rule — the first task of each project
    must be the boundary-pinning `contracts-*` task with deps [].

Usage
  python3 cowork_stage.py --backlog ../cowork-backlog/backlog.json            # dry-run
  python3 cowork_stage.py --backlog ../cowork-backlog/backlog.json --commit   # write
  python3 cowork_stage.py --backlog ... --project tomorrow --commit           # one project
Requires (only for --commit): SUPABASE_URL + SUPABASE_SERVICE_KEY in runner/.env
"""
import os, sys, json, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

VALID_KINDS = {
    # Core pipeline kinds
    "build", "bugfix", "refactor", "batch", "research",
    # Operational kinds
    "recovery", "toolchain-repair", "canary", "feature",
    # QA/release kinds
    "qafix", "relfix",
    # Improvement kinds (improve-architecture, improve-ux, improve-performance, etc.)
    "improve-architecture", "improve-ux", "improve-performance",
    "improve-reliability", "improve-security", "improve-observability",
    # Strategy/planning kinds
    "efficiency", "self", "legal", "gtm",
    # Speculative (excluded from executor claim but valid for staging)
    "speculative",
}


def load_backlog(path):
    with open(path) as f:
        doc = json.load(f)
    projects = doc.get("projects", {})   # name -> {repo_path, default_base}
    tasks = doc.get("tasks", [])
    return projects, tasks


def validate(projects, tasks):
    """Static validation: kinds, project refs, dep resolution, no cycles, contract-first."""
    errors = []
    slugs_by_project = {}
    for t in tasks:
        slugs_by_project.setdefault(t["project"], []).append(t["slug"])

    for name, slugs in slugs_by_project.items():
        if name not in projects:
            errors.append(f"task references unknown project '{name}' (add it to backlog.projects)")
        # contract-first: every project's FIRST listed task should be its contracts pin with deps []
        first = next((t for t in tasks if t["project"] == name), None)
        if first and not first["slug"].startswith("contracts"):
            errors.append(f"[{name}] contract-first violated: first task '{first['slug']}' is not a contracts-* task")

    all_keys = {(t["project"], t["slug"]) for t in tasks}
    for t in tasks:
        task_kind = t.get("kind", "build")
        # Accept any improve-* kind (improve-architecture, improve-latency, etc.)
        kind_valid = task_kind in VALID_KINDS or task_kind.startswith("improve-")
        if not kind_valid:
            errors.append(f"[{t['project']}/{t['slug']}] invalid kind '{task_kind}'")
        for dep in t.get("deps", []):
            if (t["project"], dep) not in all_keys:
                errors.append(f"[{t['project']}/{t['slug']}] dep '{dep}' not found in same project")

    # cycle check per project (Kahn)
    for name in slugs_by_project:
        nodes = [t for t in tasks if t["project"] == name]
        indeg = {t["slug"]: len(t.get("deps", [])) for t in nodes}
        adj = {}
        for t in nodes:
            for d in t.get("deps", []):
                adj.setdefault(d, []).append(t["slug"])
        queue = [s for s, d in indeg.items() if d == 0]
        seen = 0
        while queue:
            s = queue.pop()
            seen += 1
            for nxt in adj.get(s, []):
                indeg[nxt] -= 1
                if indeg[nxt] == 0:
                    queue.append(nxt)
        if seen != len(nodes):
            errors.append(f"[{name}] dependency cycle detected among {len(nodes)} tasks")
    return errors


def ensure_project(db, name, meta, commit):
    existing = db.select("projects", {"select": "*", "name": f"eq.{name}"})
    if existing:
        return existing[0]["id"], "exists"
    row = {"name": name, "repo_path": meta["repo_path"], "default_base": meta.get("default_base", "main")}
    if commit:
        created = db.insert("projects", row)
        return (created[0]["id"] if created else None), "created"
    return None, "would-create"


def stage(backlog_path, only_project=None, commit=False):
    projects, tasks = load_backlog(backlog_path)
    if only_project:
        tasks = [t for t in tasks if t["project"] == only_project]
        projects = {only_project: projects[only_project]} if only_project in projects else projects

    errors = validate(projects, {*()} and tasks or tasks)
    if errors:
        print("VALIDATION FAILED:")
        for e in errors:
            print("  ✗", e)
        sys.exit(2)
    print(f"✓ DAG valid: {len(tasks)} tasks across {len(projects)} projects "
          f"({'COMMIT' if commit else 'DRY-RUN — no writes'}).\n")

    db = None
    if commit:
        import db as _db
        db = _db

    proj_ids = {}
    for name, meta in projects.items():
        if commit:
            pid, status = ensure_project(db, name, meta, commit)
            proj_ids[name] = pid
        else:
            status = "would-ensure"
        print(f"project {name:14s} → {meta['repo_path']}  [{status}]")

    print()
    staged = skipped = 0
    for t in tasks:
        kind = t.get("kind", "build")
        base = t.get("base_branch", projects.get(t["project"], {}).get("default_base", "main"))
        line = f"  {t['project']}/{t['slug']:34s} kind={kind:9s} deps={t.get('deps', [])}"
        if commit:
            pid = proj_ids.get(t["project"])
            existing = db.select("tasks", {
                "select": "id,state", "project_id": f"eq.{pid}", "slug": f"eq.{t['slug']}",
            })
            live = [e for e in existing if e["state"] not in ("DONE", "MERGED")]
            if live:
                print(line, "→ SKIP (already staged)")
                skipped += 1
                continue
            db.insert("tasks", {
                "project_id": pid, "slug": t["slug"], "prompt": t["prompt"],
                "base_branch": base, "deps": t.get("deps", []), "kind": kind,
                "model": t.get("model"), "state": "QUEUED",
                "note": "staged by cowork_stage",
            })
            print(line, "→ QUEUED")
            staged += 1
        else:
            print(line, "→ would QUEUE")
            staged += 1

    print(f"\n{'Staged' if commit else 'Would stage'}: {staged}   Skipped(existing): {skipped}")
    if not commit:
        print("\nNothing was written. Re-run with --commit (on the runner Mac, with "
              "SUPABASE_SERVICE_KEY set) to enqueue. The runner stays PAUSED until you "
              "lift the kill switch per ACTIVATION.md, so staging never spends.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--backlog", default=os.path.join(os.path.dirname(__file__), "..", "cowork-backlog", "backlog.json"))
    ap.add_argument("--project", default=None, help="stage only this project")
    ap.add_argument("--commit", action="store_true", help="actually write to Supabase (default: dry-run)")
    args = ap.parse_args()
    stage(args.backlog, only_project=args.project, commit=args.commit)
