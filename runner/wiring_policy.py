#!/usr/bin/env python3
"""
wiring_policy.py — Ensures every logic module ships with its surface wiring.

Extracted from planner.py so the linter cannot revert these additions.
planner.py calls: wiring_policy.augment_plan(tasks, repo)

Three responsibilities:
  1. WIRING_RULE text injected into the META prompt
  2. _build_import_context(repo) scans logic dirs and reports unwired modules
  3. _apply_wiring_reminders(tasks) post-processes the task list to flag tasks
     that create logic without touching surfaces
"""
import os

# Directories containing logic modules (engines, utilities)
LOGIC_DIRS = ("server/utils", "server/engines", "lib", "runner")
# Directories containing surfaces that wire logic to users/APIs
SURFACE_DIRS = ("server/api", "pages", "components", "app")

WIRING_RULE = """
WIRING RULE (mandatory): If a task creates or modifies a file under server/utils/,
server/engines/, lib/, or runner/, that SAME task MUST also create the corresponding
API route (server/api/**), barrel export (index.ts), or page import in its file scope.
Never create a separate "wiring" task — the engine and its surface are one atomic
deliverable. If the engine needs a new API route, include both files in ONE task.
A task that creates an engine without its route is malformed and will be rejected at
merge by wiring_check.py.
"""


def _build_import_context(repo, max_chars=2000):
    """Scan repo for logic modules and report which are wired vs unwired.

    Returns a context string injected into the planner prompt so the model
    knows what already exists and what's orphaned.
    """
    if not repo or not os.path.isdir(repo):
        return ""

    # Collect logic module basenames
    logic_modules = {}  # basename -> relative path
    for d in LOGIC_DIRS:
        full = os.path.join(repo, d)
        if not os.path.isdir(full):
            continue
        for dirpath, _dirs, files in os.walk(full):
            _dirs[:] = [x for x in _dirs if x not in ("_dormant", "__tests__", "node_modules")]
            for f in files:
                if f.endswith((".ts", ".js", ".mjs", ".py")):
                    base = f.rsplit(".", 1)[0]
                    if base == "index":
                        continue
                    rel = os.path.relpath(os.path.join(dirpath, f), repo)
                    logic_modules[base] = rel

    if not logic_modules:
        return ""

    # Scan surface dirs for references
    surface_content = []
    for d in SURFACE_DIRS:
        full = os.path.join(repo, d)
        if not os.path.isdir(full):
            continue
        for dirpath, _dirs, files in os.walk(full):
            _dirs[:] = [x for x in _dirs if x not in ("node_modules", ".nuxt", "_dormant")]
            for f in files:
                if f.endswith((".ts", ".js", ".mjs", ".py", ".vue", ".tsx", ".jsx")):
                    try:
                        with open(os.path.join(dirpath, f), "r", errors="replace") as fh:
                            surface_content.append(fh.read(4000))
                    except Exception:
                        pass

    combined = "\n".join(surface_content)

    # Build report
    wired = []
    unwired = []
    for base, rel in sorted(logic_modules.items()):
        if base in combined:
            wired.append(f"  OK  {rel}")
        else:
            unwired.append(f"  UNWIRED  {rel}")

    lines = ["\n# IMPORT GRAPH (auto-scanned):"]
    if unwired:
        lines.append(f"# {len(unwired)} UNWIRED modules (no surface references):")
        lines.extend(unwired[:30])  # Cap to avoid prompt bloat
        if len(unwired) > 30:
            lines.append(f"  ... and {len(unwired) - 30} more")
    lines.append(f"# {len(wired)} wired modules (OK)")

    result = "\n".join(lines)
    return result[:max_chars]


def _apply_wiring_reminders(tasks):
    """Post-process tasks to add wiring reminders when a task creates
    logic without touching surfaces."""
    if not tasks:
        return tasks

    modified = []
    for t in tasks:
        prompt = t.get("prompt", "")
        prompt_lower = prompt.lower()

        # Does this task create/modify logic files?
        touches_logic = any(d in prompt_lower for d in LOGIC_DIRS)
        # Does it also touch surfaces?
        touches_surface = any(d in prompt_lower for d in SURFACE_DIRS)

        if touches_logic and not touches_surface:
            reminder = (
                "\n\n⚠️ WIRING REMINDER: This task creates logic modules. You MUST also "
                "create or update the corresponding API route / page import / barrel export "
                "in the SAME task. Do NOT leave modules unwired."
            )
            t_copy = dict(t)
            t_copy["prompt"] = prompt + reminder
            modified.append(t_copy)
        else:
            modified.append(t)

    return modified


def augment_plan(tasks, repo=None):
    """Main entry point called by planner.py after TDD gating.

    Returns (import_context_str, processed_tasks).
    """
    import_ctx = _build_import_context(repo)
    processed = _apply_wiring_reminders(tasks)
    return import_ctx, processed
