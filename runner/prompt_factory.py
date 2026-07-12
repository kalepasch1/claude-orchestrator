#!/usr/bin/env python3
"""
prompt_factory.py - objective -> optimal prompt -> intake DAG -> fleet execution, with no
operator in the loop after the objective is stated.

Inputs (each best-effort; a missing/empty source just contributes nothing):
  1. Open objectives: the existing `goals` table (status='active'), the same source goals.py
     already reads. goals.py turns a goal into a FLAT batch of directly-inserted DB tasks;
     this module instead runs each objective through planner.py's contract-first DAG
     decomposition and emits it as a canonical intake file, so it flows through the same
     dependency-linked, model-routed, proof-gated path as any other intake drop (including
     operator-authored PROMPT-*.md files, see intake_watcher.py's decompose_freeform()).
     The two modules overlap in purpose; left both in place rather than deleting goals.py's
     simpler direct-insert path in this same change — worth consolidating in a follow-up.
  2. Top unresolved blockers: tasks stuck in BLOCKED/CONFLICT/TESTFAIL/SHELVED longer than
     BLOCKER_AGE_MIN minutes become single-task "diagnose and fix" intake entries.
  3. KPI gaps from the scoreboard: NOT wired in yet — Part D's scoreboard table doesn't exist
     in this codebase as of this writing (deferred to intake per the mission's own guardrail
     that Parts C+D ship as intake DAGs, not in this serial session). gather_kpi_gaps() is a
     stub that returns [] and is the extension point once that table lands.

Every emitted task carries a `proof:` line (a command or check) — required by mission spec
("no task without a proof command"): extracted from the task prompt if the model included one,
else falls back to the project's configured test command.

Idempotent by slug: an objective/blocker that already has a processed factory-<slug>.md (in
intake/processed/) or a QUEUED/RUNNING task whose slug starts with factory-<slug> is skipped.
Bounded by ORCH_FACTORY_MAX_OPEN (default 3): never more than N un-ingested factory-*.md files
sitting in intake/ at once, so a slow-draining fleet doesn't get buried in generated work on
top of its existing backlog.
"""
import os, sys, re, glob, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

INTAKE_DIR = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "intake"))
PROCESSED_DIR = os.path.join(INTAKE_DIR, "processed")
MAX_OPEN = int(os.environ.get("ORCH_FACTORY_MAX_OPEN", "3"))
BLOCKER_AGE_MIN = int(os.environ.get("ORCH_FACTORY_BLOCKER_AGE_MIN", "60"))
MAX_BLOCKERS_PER_RUN = int(os.environ.get("ORCH_FACTORY_MAX_BLOCKERS", "3"))
BLOCKER_STATES = ("BLOCKED", "CONFLICT", "TESTFAIL", "SHELVED")

_PROOF_LINE_RX = re.compile(r"(?:proof|acceptance test|test)\s*:\s*(\S.+)", re.I)


def _slugify(text):
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s[:60] or "objective"


def gather_objectives(limit=5):
    """Active goals, oldest-priority-first, that aren't already open in the pipeline."""
    try:
        rows = db.select("goals", {"select": "*", "status": "eq.active",
                                   "order": "priority.asc", "limit": str(limit)}) or []
    except Exception:
        return []
    return rows


def gather_blockers(limit=MAX_BLOCKERS_PER_RUN):
    """Tasks stuck long enough that a human hasn't noticed, or blocker_quarantine.py hasn't
    reached yet. Best-effort: a DB error returns []. Age filtering is done in Python (not via
    a `lt.` PostgREST filter) to keep the query resilient to clock-format quirks across rows."""
    try:
        rows = db.select("tasks", {"select": "id,slug,state,note,project_id,updated_at",
                                   "state": f"in.({','.join(BLOCKER_STATES)})",
                                   "order": "updated_at.asc", "limit": "50"}) or []
    except Exception:
        return []
    cutoff = time.time() - BLOCKER_AGE_MIN * 60
    aged = []
    for r in rows:
        try:
            import datetime
            ts = datetime.datetime.fromisoformat(str(r["updated_at"]).replace("Z", "+00:00"))
            if ts.timestamp() <= cutoff:
                aged.append(r)
        except Exception:
            aged.append(r)  # unparsable timestamp -> assume old enough rather than drop it
    return aged[:limit]


def gather_kpi_gaps():
    """Stub extension point for Part D's scoreboard (not built as of this writing — see module
    docstring). Returns [] until that table exists; never raises."""
    return []


def _project_repo_map():
    return {p["id"]: p for p in (db.select("projects", {"select": "*"}) or [])}


def _extract_proof(prompt_text, project_row):
    m = _PROOF_LINE_RX.search(prompt_text or "")
    if m:
        return m.group(1).strip().rstrip(".")
    return (project_row or {}).get("test_cmd") or os.environ.get("TEST_CMD", "npm test")


def _already_shipped(slug):
    if glob.glob(os.path.join(PROCESSED_DIR, f"*factory-{slug}*.md")):
        return True
    if os.path.isfile(os.path.join(INTAKE_DIR, f"factory-{slug}.md")):
        return True
    try:
        existing = db.select("tasks", {"select": "id", "slug": f"like.factory-{slug}-*"}) or []
        if existing:
            return True
    except Exception:
        pass
    return False


def _open_factory_file_count():
    return len(glob.glob(os.path.join(INTAKE_DIR, "factory-*.md")))


def render_objective_dag(objective_row, project_row):
    """Run one objective through planner.py's contract-first decomposition and render as a
    canonical intake block (a list of task dicts ready for _render_intake_file).

    If TDD is enabled, acceptance criteria from planner are propagated to task metadata."""
    import planner
    import tdd_gate
    slug = _slugify(objective_row.get("objective") or objective_row.get("id") or "objective")
    goal_text = objective_row.get("objective") or ""
    metric = objective_row.get("metric")
    target = objective_row.get("target")
    master = goal_text
    if metric or target:
        master += f" (metric: {metric}, target: {target})"
    repo = (project_row or {}).get("repo_path")
    tasks = planner.plan(master, repo=repo)
    hint = {"haiku": "claude-haiku-4-5-20251001", "sonnet": "claude-sonnet-4-6", "opus": "claude-opus-4-8"}
    rendered = []
    for t in tasks:
        entry = {
            "id": f"factory-{slug}-{t['slug']}",
            "title": (t.get("prompt") or "")[:80].replace("\n", " ") or t["slug"],
            "material": False,
            "model": hint.get(t.get("model_hint"), t.get("model_hint") or ""),
            "depends": [f"factory-{slug}-{d}" for d in (t.get("deps") or [])],
            "proof": _extract_proof(t.get("prompt"), project_row),
            "prompt": t.get("prompt") or "",
        }
        if tdd_gate.is_tdd_enabled() and t.get("acceptance_criteria"):
            entry["acceptance_criteria"] = t["acceptance_criteria"]
        rendered.append(entry)
    return slug, rendered


def render_blocker_task(blocker_row, project_row):
    slug = _slugify(f"unblock-{blocker_row.get('slug') or blocker_row.get('id')}")
    original_slug = blocker_row.get("slug") or "(unknown)"
    state = blocker_row.get("state") or "BLOCKED"
    note = blocker_row.get("note") or "(no note recorded)"
    prompt = (f"Task '{original_slug}' has been stuck in state {state} for over "
              f"{BLOCKER_AGE_MIN} minutes. Recorded note: {note}\n\n"
              f"Diagnose the root cause (build failure, merge conflict, flaky test, or a genuine "
              f"blocker needing a design decision) and fix it, or if it's a duplicate/obsolete "
              f"task, close it with a reason. Do not just retry blindly — read the actual error.")
    entry = {
        "id": f"factory-{slug}",
        "title": f"Unblock {original_slug} (stuck {state})",
        "material": False,
        "model": "",
        "depends": [],
        "proof": _extract_proof(prompt, project_row),
        "prompt": prompt,
    }
    return slug, [entry]


def _render_intake_file(project_name, entries):
    lines = [f"PROJECT: {project_name}", ""]
    for e in entries:
        lines.append(f"- id: {e['id']}")
        lines.append(f"  title: {e['title']}")
        lines.append(f"  material: {'yes' if e['material'] else 'no'}")
        if e.get("model"):
            lines.append(f"  model: {e['model']}")
        if e.get("depends"):
            lines.append("  depends: [" + ", ".join(e["depends"]) + "]")
        lines.append(f"  proof: {e['proof']}")
        lines.append("  prompt: |")
        for pl in (e["prompt"] or "").splitlines() or [""]:
            lines.append(f"    {pl}")
        lines.append("")
    return "\n".join(lines)


def run():
    if not os.path.isdir(INTAKE_DIR):
        return {"written": 0, "skipped": 0, "reason": "no intake/ dir"}
    open_count = _open_factory_file_count()
    if open_count >= MAX_OPEN:
        print(f"prompt_factory: {open_count} factory DAG(s) already open (cap {MAX_OPEN}) — skipping this run")
        return {"written": 0, "skipped": 0, "reason": "at cap"}

    projects = _project_repo_map()
    projects_by_name = {p.get("name"): p for p in projects.values()}
    written, skipped = 0, 0
    budget = MAX_OPEN - open_count

    for obj in gather_objectives():
        if budget <= 0:
            break
        # Cheap idempotency check FIRST — render_objective_dag() calls planner.plan(), which
        # makes a real model call. Checking shipped-status only after decomposing would waste
        # a model call (and real $/time) on every already-shipped objective, every single run.
        precheck_slug = _slugify(obj.get("objective") or obj.get("id") or "objective")
        if _already_shipped(precheck_slug):
            skipped += 1
            continue
        proj = projects_by_name.get(obj.get("project"))
        try:
            slug, entries = render_objective_dag(obj, proj)
        except Exception as e:
            print(f"prompt_factory: objective decomposition failed ({e}); skipping")
            continue
        if not entries or _already_shipped(slug):
            skipped += 1
            continue
        path = os.path.join(INTAKE_DIR, f"factory-{slug}.md")
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(_render_intake_file(obj.get("project") or "unknown", entries))
            written += 1
            budget -= 1
            print(f"prompt_factory: wrote factory-{slug}.md ({len(entries)} tasks) from objective")
        except Exception as e:
            print(f"prompt_factory: failed writing factory-{slug}.md ({e})")

    for blk in gather_blockers():
        if budget <= 0:
            break
        proj = projects.get(blk.get("project_id"))
        proj_name = (proj or {}).get("name") or "unknown"
        slug, entries = render_blocker_task(blk, proj)
        if _already_shipped(slug):
            skipped += 1
            continue
        path = os.path.join(INTAKE_DIR, f"factory-{slug}.md")
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(_render_intake_file(proj_name, entries))
            written += 1
            budget -= 1
            print(f"prompt_factory: wrote factory-{slug}.md (unblock task)")
        except Exception as e:
            print(f"prompt_factory: failed writing factory-{slug}.md ({e})")

    # KPI-gap sourcing is a documented stub (see gather_kpi_gaps docstring) until Part D lands
    gather_kpi_gaps()

    print(f"prompt_factory: wrote {written}, skipped {skipped} (already shipped or decomposition failed)")
    return {"written": written, "skipped": skipped}


if __name__ == "__main__":
    run()
