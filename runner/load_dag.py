#!/usr/bin/env python3
"""
load_dag.py — load a contract-first tasks.yaml DAG into the Supabase `tasks` queue.

The runner polls `tasks` and `claim_task()` only runs a task once every slug in its
`deps` is DONE/MERGED. The planner emits tasks.yaml for human review but nothing
inserts it — this does, idempotently (upsert on slug, per SPEC: no duplicate rows on
retry). Safe to re-run; existing QUEUED/RUNNING rows are not clobbered to an earlier
state.

Usage:
    python3 runner/load_dag.py --project tomorrow \
        ~/Documents/tomorrow/tomorrow/completeness-credit.tasks.yaml
    python3 runner/load_dag.py --project tomorrow --dry-run tasks.yaml

Env: SUPABASE_URL + SUPABASE_SERVICE_KEY (loaded from runner/.env like runner.py).
"""
import os, sys, argparse, yaml
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db  # tiny PostgREST client already in the runner


def resolve_project_id(name_or_id: str) -> str:
    rows = db.select("projects", {"select": "id,name"}) or []
    for r in rows:
        if r["id"] == name_or_id or r.get("name") == name_or_id:
            return r["id"]
    sys.exit(f"[load_dag] project '{name_or_id}' not found. Registered: "
             + ", ".join(sorted(r.get('name', r['id']) for r in rows)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("yaml_path")
    ap.add_argument("--project", required=True, help="project name or id (must exist in `projects`)")
    ap.add_argument("--kind", default="feature")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    with open(args.yaml_path) as f:
        tasks = yaml.safe_load(f)
    if not isinstance(tasks, list) or not tasks:
        sys.exit("[load_dag] tasks.yaml must be a non-empty list")

    slugs = [t["slug"] for t in tasks]
    if len(slugs) != len(set(slugs)):
        sys.exit("[load_dag] duplicate slugs — deps are matched globally by slug, keep them unique")
    if tasks[0]["slug"] != "contracts" or tasks[0].get("deps"):
        sys.exit("[load_dag] first task must be slug 'contracts' with empty deps (contract-first)")
    known = set(slugs)
    for t in tasks:
        for d in t.get("deps", []):
            if d not in known:
                sys.exit(f"[load_dag] task '{t['slug']}' depends on unknown slug '{d}'")

    project_id = "DRY" if args.dry_run else resolve_project_id(args.project)
    rows = []
    for t in tasks:
        rows.append({
            "project_id": project_id,
            "slug": t["slug"],
            "prompt": t["prompt"],
            "deps": t.get("deps", []),
            "model": t.get("model"),
            "base": t.get("base", "main"),
            "kind": args.kind,
            "state": "QUEUED",
        })

    if args.dry_run:
        print(f"[load_dag] {len(rows)} tasks would be queued for project '{args.project}':")
        for r in rows:
            dep = (" <- " + ", ".join(r["deps"])) if r["deps"] else " (root)"
            print(f"  - {r['slug']}{dep}")
        return

    for r in rows:
        db.insert("tasks", r, upsert=True)  # upsert on slug unique constraint
    print(f"[load_dag] queued {len(rows)} tasks for project '{args.project}'. "
          f"Start/keep the runner running: python3 runner/runner.py")


if __name__ == "__main__":
    main()
