#!/usr/bin/env python3
"""
enqueue_task.py - push a JSON task definition into the orchestrator queue so the
runner executes it under the normal budget/verify/PR gates. The canonical channel
for cross-repo work (e.g. vendoring the Darwin Kernel into Pareto via git subtree
+ PR) instead of hand-editing another repo.

Usage:
  python runner/enqueue_task.py tasks/pareto-darwin-kernel.task.json

Requires the same env as the runner (SUPABASE_URL + service key, read by db.py).
Idempotent: coalesces equivalent open intent while allowing completed intent to recur.
"""
import datetime
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import pipeline_contract
import tests_first_gate
from enqueue import TERMINAL_STATES, enqueue_task as enqueue_intent, intent_key


PROJECT_ALIASES = {
    "orchestrator": "beethoven",
    "claude-orchestrator": "beethoven",
    "madeus": "beethoven",
    "2080": "pareto-2080",
}
_RECOVERABLE_STATES = {"BLOCKED", "CONFLICT", "TESTFAIL", "WAITING", "DECOMPOSED", "SHELVED"}
_INTENT_MARKER = "enqueue-intent:"


def canonical_project_name(name):
    raw = str(name or "").strip()
    return PROJECT_ALIASES.get(raw.lower(), raw)


def project_by_name(name):
    canonical = canonical_project_name(name)
    rows = db.select("projects", {"select": "id,name,repo_path,default_base"}) or []
    for p in rows:
        if str(p.get("name") or "").lower() == canonical.lower():
            return p
    # tolerate the '2080' folder name too
    for p in rows:
        if canonical.lower() in str(p.get("repo_path") or "").lower():
            return p
    return None


def project_id_by_name(name):
    p = project_by_name(name)
    return p["id"] if p else None


def already_present(project_id, slug):
    rows = db.select("tasks", {"select": "id,state",
                               "project_id": f"eq.{project_id}",
                               "slug": f"eq.{slug}",
                               "state": "not.in.(%s)" % ",".join(sorted(TERMINAL_STATES))}) or []
    return len(rows) > 0


def _intent_from_note(note):
    for token in str(note or "").split():
        if token.startswith("[" + _INTENT_MARKER) and token.endswith("]"):
            return token[len(_INTENT_MARKER) + 1:-1]
    return ""


def _find_open_by_intent(project_id, key):
    rows = db.select("tasks", {
        "select": "id,slug,state,attempt,note",
        "project_id": f"eq.{project_id}",
        "state": "not.in.(%s)" % ",".join(sorted(TERMINAL_STATES)),
        "order": "updated_at.desc",
        "limit": "1000",
    }) or []
    for row in rows:
        candidate = _intent_from_note(row.get("note"))
        if not candidate:
            candidate = intent_key(project_id, row.get("slug", ""))
        if candidate == key:
            return row
    return None


def _insert_id(result):
    if isinstance(result, list):
        result = result[0] if result else None
    return result.get("id") if isinstance(result, dict) else result


def main(path):
    with open(path, encoding="utf-8") as source:
        spec = json.load(source)
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
            sub_spec = dict(spec)
            sub_spec.update(sub)
            _enqueue_one(sub_spec, proj, pid)
        return

    _enqueue_one(spec, proj, pid)


def _enqueue_one(spec, proj, pid):
    """Insert or coalesce a single task through the canonical intent chokepoint."""
    raw_prompt = spec.get("prompt", "")
    proof = str(spec.get("proof") or "").strip()
    if proof and proof not in raw_prompt:
        raw_prompt = f"{raw_prompt.rstrip()}\n\nProof: {proof}"
    row = {
        "project_id": pid,
        "slug": spec["slug"],
        "prompt": pipeline_contract.wrap_prompt(raw_prompt, project=proj.get("name") or spec["project"],
                                                kind=spec.get("kind", "build"),
                                                source=spec.get("source", "json-enqueue"),
                                                slug=spec["slug"],
                                                material=bool(spec.get("material"))),
        "kind": spec.get("kind", "build"),
        "state": spec.get("state", "QUEUED"),
        "base_branch": spec.get("base_branch") or proj.get("default_base") or "master",
        "note": pipeline_contract.note(spec.get("note", ""), source=spec.get("source", "json-enqueue")),
    }
    if spec.get("deps"):
        row["deps"] = spec["deps"]
    if spec.get("model"):
        row["model"] = spec["model"]
    if spec.get("submitted_by_label"):
        row["submitted_by_label"] = spec["submitted_by_label"]
    if spec.get("material") is not None:
        row["material"] = bool(spec.get("material"))
    if spec.get("target_path"):
        # Used by enqueue.intent_key only; tasks has no target_path column.
        row["target_path"] = spec["target_path"]

    def find_open(key):
        return _find_open_by_intent(pid, key)

    def insert(record, key):
        persisted = dict(record)
        persisted.pop("target_path", None)
        marker = f"[{_INTENT_MARKER}{key}]"
        persisted["note"] = f"{persisted.get('note', '').rstrip()} {marker}".strip()
        # The core has already determined that no open equivalent exists. Let a
        # terminal historical row with the same exact slug recur legitimately.
        persisted["_allow_dup"] = True
        result = db.insert("tasks", persisted)
        task_id = _insert_id(result)
        if not task_id:
            raise RuntimeError(f"queue insert refused or returned no receipt: {spec['slug']}")
        return task_id

    def bump(existing):
        patch = {"updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat()}
        if str(existing.get("state") or "").upper() in _RECOVERABLE_STATES:
            patch.update({"state": "QUEUED", "attempt": 0})
        db.update("tasks", {"id": existing["id"]}, patch)

    result = enqueue_intent(row, find_open_by_intent=find_open, insert=insert, bump=bump)
    print(f"[enqueue] {result.action} '{spec['slug']}' for project "
          f"'{proj.get('name') or spec['project']}' -> {result.task_id}")
    if result.action == "created" and result.task_id:
        triggered = db.test_trigger(result.task_id)
        if triggered:
            print(f"[enqueue] test trigger fired for '{spec['slug']}' -> state=TESTING")
    return result


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: python runner/enqueue_task.py <task.json>")
    main(sys.argv[1])
