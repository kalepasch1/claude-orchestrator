#!/usr/bin/env python3
"""
enqueue_task.py - push a JSON task definition into the orchestrator queue so the
runner executes it under the normal budget/verify/PR gates. The canonical channel
for cross-repo work (e.g. vendoring the Darwin Kernel into Pareto via git subtree
+ PR) instead of hand-editing another repo.

Usage:
  python runner/enqueue_task.py tasks/pareto-darwin-kernel.task.json

Requires the same env as the runner (SUPABASE_URL + service key, read by db.py).
Idempotent: skips if a task with the same (project_id, slug) is already open/done.
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import pipeline_contract
import tests_first_gate


def project_by_name(name):
    rows = db.select("projects", {"select": "id,name,repo_path"}) or []
    for p in rows:
        if p.get("name") == name:
            return p
    # tolerate the '2080' folder name too
    for p in rows:
        if name in (p.get("repo_path") or ""):
            return p
    return None


def project_id_by_name(name):
    p = project_by_name(name)
    return p["id"] if p else None


def already_present(project_id, slug):
    rows = db.select("tasks", {"select": "id,state",
                               "project_id": f"eq.{project_id}",
                               "slug": f"eq.{slug}"}) or []
    return len(rows) > 0


def main(path):
    spec = json.load(open(path))
    proj = project_by_name(spec["project"])
    if not proj:
        sys.exit(f"[enqueue] project '{spec['project']}' not found in projects table. "
                 f"Register it first (name + repo_path).")
    pid = proj["id"]

    # Apply tests-first gate: if proof references a missing test file, split into two tasks
    repo_path = proj.get("repo_path")
    task_for_gate = {"slug": spec["slug"], "prompt": spec.get("prompt", ""),
                     "kind": spec.get("kind", "build"), "deps": spec.get("deps", []),
                     "proof": spec.get("proof", "")}
    expanded = tests_first_gate.split_if_needed(task_for_gate, repo_path=repo_path)
    if len(expanded) > 1:
        # Enqueue the test-authoring task first, then the original with updated deps
        for sub in expanded:
            if already_present(pid, sub["slug"]):
                print(f"[enqueue] task '{sub['slug']}' already exists for project — skipping.")
                continue
            sub_spec = dict(spec)
            sub_spec.update(sub)
            _enqueue_one(sub_spec, proj, pid)
        return

    if already_present(pid, spec["slug"]):
        print(f"[enqueue] task '{spec['slug']}' already exists for project — skipping.")
        return
    _enqueue_one(spec, proj, pid)


def _enqueue_one(spec, proj, pid):
    """Insert a single task row into the DB."""
    row = {
        "project_id": pid,
        "slug": spec["slug"],
        "prompt": pipeline_contract.wrap_prompt(spec.get("prompt", ""), project=proj.get("name") or spec["project"],
                                                kind=spec.get("kind", "build"),
                                                source=spec.get("source", "json-enqueue"),
                                                slug=spec["slug"],
                                                material=bool(spec.get("material"))),
        "kind": spec.get("kind", "build"),
        "state": spec.get("state", "QUEUED"),
        "note": pipeline_contract.note(spec.get("note", ""), source=spec.get("source", "json-enqueue")),
    }
    if spec.get("deps"):
        row["deps"] = spec["deps"]
    if spec.get("model"):
        row["model"] = spec["model"]
    res = db.insert("tasks", row)
    print(f"[enqueue] queued '{spec['slug']}' for project '{spec['project']}' -> {res}")
    if res:
        task_id = res[0].get("id") if isinstance(res, list) else (res or {}).get("id")
        if task_id:
            triggered = db.test_trigger(task_id)
            if triggered:
                print(f"[enqueue] test trigger fired for '{spec['slug']}' -> state=TESTING")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: python runner/enqueue_task.py <task.json>")
    main(sys.argv[1])
