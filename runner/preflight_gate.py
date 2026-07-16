#!/usr/bin/env python3
"""
preflight_gate.py - cost/value control before expensive agentic work.

It never terminally blocks work. If a cheap model thinks a task is vague/no-diff, the task
is rewritten into an explicit implementation directive and left QUEUED so the fleet keeps
moving instead of surfacing "blocked_task" interruptions.

Enhanced with scope definition and ambiguity flagging to reduce unnecessary remediation
and improve routing efficiency per operator feedback.
"""
import os, sys, json, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import pipeline_contract
try:
    import app_triage
except Exception:
    app_triage = None

BATCH = int(os.environ.get("PREFLIGHT_BATCH", "15"))
PROTECT = ("canary-", "sec-rls-", "fix-", "verify-", "rollback-", "rls-", "auto-approve", "deploy")


def _protected(slug):
    s = (slug or "").lower()
    return any(s.startswith(p) or p in s for p in PROTECT)


def _extract_scope_and_ambiguities(response_text: str) -> tuple:
    """Extract scope definition and ambiguities from triage response.

    Returns (actionable: bool, scope_def: str, ambiguities: list[str])
    """
    text = (response_text or "").strip()
    actionable = False
    scope_def = ""
    ambiguities = []

    lines = text.split("\n")
    if not lines:
        return False, "", []

    first_line = lines[0].strip().upper()
    if first_line.startswith("YES"):
        actionable = True
    elif first_line.startswith("NO"):
        actionable = False

    scope_section = False
    ambiguity_section = False
    scope_lines = []
    ambiguity_lines = []

    for line in lines[1:]:
        line = line.strip()
        if not line:
            continue

        if line.startswith("SCOPE:") or line.startswith("SCOPE DEFINITION:"):
            scope_section = True
            ambiguity_section = False
            scope_def_content = line.split(":", 1)[1].strip()
            if scope_def_content:
                scope_lines.append(scope_def_content)
        elif line.startswith("AMBIGUITIES:") or line.startswith("AMBIGUITIES/CONCERNS:"):
            scope_section = False
            ambiguity_section = True
            first_ambiguity = line.split(":", 1)[1].strip()
            if first_ambiguity:
                ambiguity_lines.append(first_ambiguity)
        elif line.startswith("-") or line.startswith("•"):
            if ambiguity_section:
                ambiguity_lines.append(line.lstrip("-•").strip())
            elif scope_section:
                scope_lines.append(line.lstrip("-•").strip())
        elif scope_section and line:
            scope_lines.append(line)
        elif ambiguity_section and line:
            ambiguity_lines.append(line)

    scope_def = " ".join(scope_lines) if scope_lines else ""
    ambiguities = [a for a in ambiguity_lines if a]

    return actionable, scope_def, ambiguities


def run():
    if not app_triage:
        print("preflight: app_triage unavailable; skipping"); return
    rows = db.select("tasks", {"select": "id,slug,prompt,kind,material,note,model,force_coder,project_id", "state": "eq.QUEUED",
                              # Updating a row moves it to the back, so every queued
                              # task is eventually triaged instead of screening the
                              # same oldest BATCH forever.
                              "order": "updated_at.asc", "limit": str(BATCH)}) or []
    try:
        projects = {p["id"]: p.get("name", "") for p in
                    (db.select("projects", {"select": "id,name"}) or [])}
    except Exception:
        projects = {}
    sharpened = 0
    for t in rows:
        if _protected(t.get("slug", "")):
            continue
        prompt = pipeline_contract.original_request(t.get("prompt") or "")[:1500]
        ask = ("You are a build-task triager. Analyze this task and respond with:\n\n"
               "1. First line: YES or NO (will this produce an actual committable code/file change?)\n"
               "2. SCOPE DEFINITION: What specific changes will be made, to which files/components?\n"
               "3. AMBIGUITIES/CONCERNS: List any vagueness, missing context, or potential issues.\n\n"
               "Vague, duplicate, already-done, discussion-only, or under-specified tasks => NO.\n\n"
               "TASK:\n" + prompt)
        try:
            r = app_triage.run("orchestrator", "preflight_triage", ask, task_class="rating")
            response_text = (r or {}).get("text", "").strip()
        except Exception as e:
            print(f"preflight {t['slug']}: {e}"); continue

        actionable, scope_def, ambiguities = _extract_scope_and_ambiguities(response_text)
        existing_note = t.get("note") or ""

        if not actionable:
            revised = ((t.get("prompt") or "").rstrip() +
                       "\n\nPREFLIGHT DIRECTIVE\n"
                       "A cheap preflight model thought this might not produce a concrete diff. "
                       "Do not stop at analysis. Implement the smallest useful code/file change, "
                       "or convert the idea into a specific test/docs/config improvement and commit it.\n"
                       f"Preflight scope concern: {scope_def[:220] if scope_def else 'Not clearly defined'}")
            existing_note = "preflight: sharpened instead of blocked"
            sharpened += 1
        else:
            revised = t.get("prompt") or ""

        scope_note = ""
        if scope_def:
            scope_note = f"scope: {scope_def[:200]}"
        if ambiguities:
            ambiguity_note = f"ambiguities: {'; '.join(ambiguities[:3])}"
            scope_note = f"{scope_note}; {ambiguity_note}" if scope_note else ambiguity_note

        if scope_note:
            existing_note = f"{existing_note}; {scope_note}" if existing_note else scope_note

        explicit_route = any(mark in existing_note.lower() for mark in
                             ("agentic-repair", "forced coder", "coder-canary"))
        admission = pipeline_contract.task_fields(
            pipeline_contract.original_request(revised),
            project=projects.get(t.get("project_id"), "orchestrator"),
            kind=t.get("kind") or "build", source="preflight-gate",
            slug=t.get("slug") or "", material=bool(t.get("material")),
            existing_note=existing_note,
            model=t.get("model") if explicit_route else None,
            force_coder=t.get("force_coder") if explicit_route else None,
        )
        db.update("tasks", {"id": t["id"]}, {
            **admission, "updated_at": "now()",
        })
    print(f"preflight: screened {len(rows)} queued, sharpened {sharpened} non-actionable predictions")


if __name__ == "__main__":
    run()
