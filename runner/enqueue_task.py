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
import os, sys, json, re
import time
import traceback
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

# Legacy (marker-less) intent scan. Paged rather than truncated: the previous
# single 1000-row read made any older open task invisible to dedup, so an
# equivalent open intent could be inserted twice. ORCH_-prefixed so the ceiling
# is fleet-pushable if a project's open queue ever outgrows it.
def _int_env(name, default):
    try:
        value = int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


_INTENT_SCAN_PAGE = _int_env("ORCH_INTENT_SCAN_PAGE", 1000)
_INTENT_SCAN_MAX = _int_env("ORCH_INTENT_SCAN_MAX", 20000)


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


def parse_cross_project_dep(dep_str: str) -> tuple:
    """Parse 'project:slug' or 'slug' into (project_name, slug).

    Returns: (project_name, slug) for cross-project deps or (None, dep_str) for bare deps.
    Raises: ValueError if format is invalid.
    """
    dep_str = str(dep_str or "").strip()
    if not dep_str:
        raise ValueError("empty dependency string")

    if ':' not in dep_str:
        return (None, dep_str)

    parts = dep_str.split(':', 1)
    if len(parts) != 2:
        raise ValueError(f"invalid dependency format: '{dep_str}'")

    project, slug = parts[0].strip(), parts[1].strip()

    if not project:
        raise ValueError(f"empty project name in dependency: '{dep_str}'")
    if not slug:
        raise ValueError(f"empty task slug in dependency: '{dep_str}'")

    if not re.match(r'^[a-zA-Z0-9_-]+$', project):
        raise ValueError(f"invalid project name '{project}' in dependency '{dep_str}': "
                        "project names must contain only alphanumeric characters, hyphens, and underscores")

    if not re.match(r'^[a-zA-Z0-9_-]+$', slug):
        raise ValueError(f"invalid task slug '{slug}' in dependency '{dep_str}': "
                        "task slugs must contain only alphanumeric characters, hyphens, and underscores")

    return (project, slug)


def _get_all_known_projects():
    """Fetch all known projects from the projects table."""
    try:
        rows = db.select("projects", {"select": "id,name"}) or []
        return {p.get("name"): p.get("id") for p in rows if p.get("name")}
    except Exception:
        return {}


def _find_cycle_from_deps(enqueue_project_id, enqueue_slug, initial_deps, target_project_id, target_slug,
                          visited=None, rec_stack=None):
    """Recursively check if any initial dependency transitively depends on the target task.

    Args:
        enqueue_project_id: The project ID of the task being enqueued
        enqueue_slug: The slug of the task being enqueued
        initial_deps: List of direct dependencies of the task being enqueued
        target_project_id: The project ID we're checking for (same as enqueue_project_id for bare deps)
        target_slug: The slug we're checking for (the enqueue_slug)
        visited: Set of (project_id, slug) tuples already visited
        rec_stack: Set of (project_id, slug) tuples in current recursion stack

    Returns:
        Cycle path as a list if found, None otherwise
    """
    if visited is None:
        visited = set()
    if rec_stack is None:
        rec_stack = set()

    for dep in initial_deps:
        try:
            dep_project, dep_slug = parse_cross_project_dep(dep)
            if dep_project is None:
                dep_project_id = enqueue_project_id
            else:
                canonical = canonical_project_name(dep_project)
                dep_project_id = project_id_by_name(canonical)
                if not dep_project_id:
                    continue

            task_key = (dep_project_id, dep_slug)
            if task_key == (target_project_id, target_slug):
                return [enqueue_slug, dep_slug]

            if task_key in rec_stack:
                continue

            if task_key in visited:
                continue

            visited.add(task_key)
            rec_stack.add(task_key)

            try:
                rows = db.select("tasks", {
                    "select": "deps",
                    "project_id": f"eq.{dep_project_id}",
                    "slug": f"eq.{dep_slug}",
                }) or []

                if rows:
                    task_row = rows[0]
                    sub_deps = task_row.get("deps") or []
                    if isinstance(sub_deps, str):
                        sub_deps = [d.strip() for d in sub_deps.split(",") if d.strip()]

                    cycle = _find_cycle_from_deps(enqueue_project_id, enqueue_slug, sub_deps,
                                                 target_project_id, target_slug, visited, rec_stack)
                    if cycle:
                        return [enqueue_slug, dep_slug] + cycle[1:]
            except Exception:
                pass

            rec_stack.discard(task_key)
        except Exception:
            pass

    return None


def validate_and_normalize_deps(project_id, task_slug, deps):
    """Validate and normalize dependencies for a task.

    Args:
        project_id: The project ID of the enqueuing task
        task_slug: The slug of the enqueuing task
        deps: List of dependency strings (bare slugs or 'project:slug' format)

    Returns:
        List of validated and normalized dependencies

    Raises:
        ValueError: If validation fails (unknown project, invalid format, circular dep)
    """
    if not deps:
        return []

    if isinstance(deps, str):
        deps = [d.strip() for d in deps.split(",") if d.strip()]

    validated = []
    known_projects = _get_all_known_projects()

    for dep in deps:
        try:
            dep_project, dep_slug = parse_cross_project_dep(dep)
        except ValueError as e:
            raise ValueError(f"[enqueue] Invalid dependency '{dep}': {str(e)}")

        if dep_project is None:
            validated.append(dep_slug)
        else:
            canonical = canonical_project_name(dep_project)
            if canonical not in known_projects:
                known_names = sorted(known_projects.keys())
                suggestion = ""
                if known_names:
                    suggestion = f" Known projects: {', '.join(known_names)}."
                raise ValueError(f"[enqueue] Unknown project '{dep_project}' in dependency '{dep}'.{suggestion}")

            validated.append(f"{canonical}:{dep_slug}")

    cycle = _find_cycle_from_deps(project_id, task_slug, validated, project_id, task_slug)
    if cycle:
        cycle_str = " → ".join(cycle + [cycle[0]])
        raise ValueError(f"[enqueue] Circular dependency detected: {cycle_str}. "
                        f"Task '{task_slug}' cannot depend on itself transitively.")

    return validated


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
    """Find the open task carrying this intent key, or None.

    Filtered server-side. The previous shape pulled the newest 1000 open rows and
    scanned them in Python, which the repo's own TRUNCATED SCAN detector flagged
    at this line: any open task older than the newest 1000 was invisible, so the
    dedup silently missed it and inserted a duplicate. Two cheap targeted queries
    replace one truncated bulk read — first on the explicit intent marker, then
    on the slug for rows enqueued before markers existed.
    """
    marker = "[" + _INTENT_MARKER + key + "]"
    base = {
        "select": "id,slug,state,attempt,note",
        "project_id": f"eq.{project_id}",
        "state": "not.in.(%s)" % ",".join(sorted(TERMINAL_STATES)),
        "order": "updated_at.desc",
        "limit": "50",
    }
    tagged = dict(base)
    # PostgREST `like` uses * as the wildcard; commas and parens would break the
    # filter grammar, so a key containing them falls through to the slug pass.
    if not any(ch in marker for ch in ",()"):
        tagged["note"] = "like.*{0}*".format(marker)
        rows = db.select("tasks", tagged) or []
        for row in rows:
            if _intent_from_note(row.get("note")) == key:
                return row

    # Legacy rows predate the marker, so their key must be derived from the slug
    # and cannot be filtered server-side (intent_key normalizes the slug first).
    # Page through them instead of truncating at the first 1000 — an open task
    # older than that page was previously invisible, and a missed dedup means a
    # duplicate insert, not just a slow query.
    base = dict(base, limit=str(_INTENT_SCAN_PAGE))
    page, offset = _INTENT_SCAN_PAGE, 0
    while offset < _INTENT_SCAN_MAX:
        scoped = dict(base, offset=str(offset))
        rows = db.select("tasks", scoped) or []
        for row in rows:
            candidate = _intent_from_note(row.get("note"))
            if not candidate:
                candidate = intent_key(project_id, row.get("slug", ""))
            if candidate == key:
                return row
        if len(rows) < page:
            return None
        offset += page
    return None


def _insert_id(result):
    if isinstance(result, list):
        result = result[0] if result else None
    return result.get("id") if isinstance(result, dict) else result


def render_intake(spec):
    """Render one JSON spec into the canonical credential-owning intake format."""
    project = canonical_project_name(spec.get("project"))
    deps = spec.get("deps") or []
    if isinstance(deps, str):
        deps = [item.strip() for item in deps.split(",") if item.strip()]
    lines = [
        f"PROJECT: {project}",
        "",
        f"- id: {spec['slug']}",
        f"  title: {spec.get('title') or spec['slug']}",
        f"  material: {'yes' if spec.get('material') else 'no'}",
        f"  model: {spec.get('model') or ''}",
        f"  submitted-by: {spec.get('submitted_by_label') or ''}",
        f"  depends: [{', '.join(deps)}]",
        f"  proof: {spec.get('proof') or ''}",
        "  prompt: |",
    ]
    prompt = str(spec.get("prompt") or "")
    if spec.get("note"):
        prompt = f"{prompt.rstrip()}\n\nQueue context: {spec['note']}"
    lines.extend(f"    {line}" for line in prompt.splitlines())
    return "\n".join(lines) + "\n"


def stage_intake(path, intake_dir=None):
    """Atomically stage a spec for the runner process that owns DB credentials."""
    with open(path, encoding="utf-8") as source:
        spec = json.load(source)
    target_dir = intake_dir or os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "intake"))
    os.makedirs(target_dir, exist_ok=True)
    target = os.path.join(target_dir, f"operator-{spec['slug']}.md")
    tmp = target + ".tmp"
    with open(tmp, "w", encoding="utf-8") as output:
        output.write(render_intake(spec))
    os.replace(tmp, target)
    return target


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
        try:
            validated_deps = validate_and_normalize_deps(pid, spec["slug"], spec["deps"])
            if validated_deps:
                row["deps"] = validated_deps
        except ValueError as e:
            sys.exit(str(e))
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
            print(f"[enqueue] test trigger fired for '{spec['slug']}' "
                  f"-> state={db.TRIGGER_STATE}")
        else:
            # Say why. A trigger that silently never fires is indistinguishable
            # from one that does, which is how the QUEUED->trigger transition
            # stayed broken without anyone noticing.
            reason = getattr(db.test_trigger, "last_error", "") or "unknown reason"
            print(f"[enqueue] test trigger did NOT fire for '{spec['slug']}': {reason}")
            print(f"[enqueue] '{spec['slug']}' remains QUEUED and claimable.")
    return result


def _run_cli(argv):
    """CLI body. Every exit path says what happened and why.

    The 2026-08-12 regression was not a crash -- it was silence. enqueue_task
    blocked inside the prompt wrapper's live provider lookups, was killed by its
    supervisor before reaching db.insert, and emitted nothing at all, so a task
    that was never queued looked exactly like a task that was. Any termination
    of this process must now be legible on stderr and in the exit status.
    """
    if len(argv) < 2:
        raise SystemExit("usage: python runner/enqueue_task.py [--stage-intake] <task.json> [...]")
    if argv[1] == "--stage-intake":
        if len(argv) < 3:
            raise SystemExit("usage: python runner/enqueue_task.py --stage-intake <task.json> [...]")
        for task_path in argv[2:]:
            print(f"[enqueue] staged intake -> {stage_intake(task_path)}")
        return 0
    started = time.monotonic()
    try:
        main(argv[1])
    except SystemExit:
        raise
    except KeyboardInterrupt:
        sys.stderr.write(
            "[enqueue] interrupted after {0:.1f}s; '{1}' may not have been queued. "
            "Re-run to confirm -- enqueue is intent-coalesced, so a repeat is safe.\n".format(
                time.monotonic() - started, argv[1]))
        return 130
    except Exception:
        sys.stderr.write(
            "[enqueue] FAILED after {0:.1f}s for {1}; nothing was queued.\n".format(
                time.monotonic() - started, argv[1]))
        traceback.print_exc()
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(_run_cli(sys.argv))
