"""wiring_policy — stop the planner emitting dead-on-arrival modules.

THE PROBLEM
-----------
A plan that says "create server/utils/pricing.ts" and nothing else produces a
module nothing imports. It passes review, passes tests, merges green, and does
nothing, because the API route or page import that would reach it was never
written — or was split into a separate "wiring" task that never ran. An engine
and the surface that calls it are one deliverable; splitting them is how a repo
accumulates code that has never executed.

This module gives the planner two things:

  * `WIRING_RULE` — the rule, stated once, injected into the planning prompt so
    the model is told up front rather than corrected at merge.
  * `_build_import_context` / `_apply_wiring_reminders` — a scan of the repo as
    it actually is, so the prompt carries the CURRENT list of unwired modules
    rather than a general instruction to be careful.

FAIL-SOFT THROUGHOUT
--------------------
Every public function returns a usable value on any error and never raises. This
is planner-path code: an unreadable file, a missing repo or a `repo=None` must
degrade to "no wiring context this run", never to a planner that cannot plan. A
policy helper that can wedge the planner is worse than no policy helper.

CLI CONTRACT (`scripts/check-wiring.mjs`)
-----------------------------------------
The merge-time checker that enforces this policy MUST honour:

    check-wiring.mjs --root <path> [--strict] [--json]

  --root <path>  repo root to scan (required)
  --strict       exit 1 when orphans > 0; otherwise always exit 0
  --json         emit JSON instead of the human line

Human output includes the line::

    Total=N Wired=N Orphans=N

JSON output has the keys ``total``, ``wired`` and ``orphans``.

`.wiring.json` SCHEMA
---------------------
An optional per-repo override, read from the repo root::

    {
      "framework":      "nuxt" | "next" | ...,   # informational
      "autoImportDirs": ["composables", "components"],  # auto-imported, never orphans
      "logicDirs":      ["server/utils", "lib"],        # overrides LOGIC_DIRS
      "surfaceDirs":    ["server/api", "pages"],        # overrides SURFACE_DIRS
      "exceptions":     ["lib/legacy/*.ts"]             # known-unwired, not reported
    }

Every key is optional; a missing or malformed file means "use the defaults".
"""
import os

# Where logic lives. A file created here needs a caller.
LOGIC_DIRS = ("server/utils", "server/engines", "lib", "runner")

# Where callers live. A basename appearing in any of these is considered wired.
SURFACE_DIRS = ("server/api", "pages", "components", "app")

# Injected verbatim into the planner's META prompt. FINAL text — do not reword;
# the merge-time checker's error message quotes it, and the two must match.
WIRING_RULE = 'WIRING RULE (mandatory): If a task creates or modifies a file under server/utils/, server/engines/, lib/, or runner/, that SAME task MUST also create the corresponding API route (server/api/**), barrel export (index.ts), or page import in its file scope. Never create a separate "wiring" task — the engine and its surface are one atomic deliverable. If the engine needs a new API route, include both files in ONE task. A task that creates an engine without its route is malformed and will be rejected at merge by wiring_check.py.'

# Appended to a task prompt that creates logic with no surface in scope.
WIRING_REMINDER = (
    "⚠️ WIRING REMINDER: This task creates logic modules. You MUST also create "
    "or update the corresponding API route / page import / barrel export in the "
    "SAME task. Do NOT leave modules unwired."
)

# Basenames that are wiring by definition, so they are never "unwired logic".
_INDEX_NAMES = {"index", "__init__", "main", "mod"}

# Directories that are never scanned for logic modules.
_SKIP_DIRS = {"_dormant", "__tests__", "node_modules", ".git", "__pycache__",
              "dist", "build", ".nuxt", ".output", "coverage"}

_CODE_SUFFIXES = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".vue", ".py")

# Reading whole surface files is unnecessary and slow; imports live at the top.
_SURFACE_HEAD_CHARS = 4000


def _is_code(name: str) -> bool:
    return name.endswith(_CODE_SUFFIXES)


def _basename_stem(name: str) -> str:
    return os.path.splitext(os.path.basename(name))[0]


def _collect_logic_modules(repo: str) -> list:
    """[(stem, relpath)] for every logic module under `repo`. [] on any error.

    Index-style files are skipped: `index.ts` IS the barrel export, so counting
    it as unwired logic would report every package root as an orphan.
    """
    found = []
    for logic_dir in LOGIC_DIRS:
        root = os.path.join(repo, logic_dir)
        if not os.path.isdir(root):
            continue
        try:
            for dirpath, dirnames, filenames in os.walk(root):
                dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
                for filename in filenames:
                    if not _is_code(filename):
                        continue
                    stem = _basename_stem(filename)
                    if stem in _INDEX_NAMES or stem.startswith("."):
                        continue
                    full = os.path.join(dirpath, filename)
                    try:
                        rel = os.path.relpath(full, repo)
                    except Exception:
                        rel = full
                    found.append((stem, rel))
        except Exception:
            # One unreadable subtree must not lose the directories already walked.
            continue
    return found


def _read_surface_text(repo: str) -> str:
    """Concatenated heads of every surface file. "" on any error."""
    chunks = []
    for surface_dir in SURFACE_DIRS:
        root = os.path.join(repo, surface_dir)
        if not os.path.isdir(root):
            continue
        try:
            for dirpath, dirnames, filenames in os.walk(root):
                dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
                for filename in filenames:
                    if not _is_code(filename):
                        continue
                    try:
                        with open(os.path.join(dirpath, filename), "r",
                                  encoding="utf-8", errors="replace") as handle:
                            chunks.append(handle.read(_SURFACE_HEAD_CHARS))
                    except Exception:
                        # An unreadable surface file is not evidence of anything.
                        continue
        except Exception:
            continue
    return "\n".join(chunks)


def _build_import_context(repo, max_chars: int = 2000) -> str:
    """A snapshot of which logic modules currently have no surface reference.

    Returned as prompt text, so the planner is told what is ALREADY unwired in
    this repo rather than only being warned in general terms. Capped at
    `max_chars` because this is prepended to every plan prompt.

    Returns "" for a missing/None repo or any error: no context is a worse plan,
    but a raised exception is no plan at all.
    """
    try:
        if not repo or not isinstance(repo, str) or not os.path.isdir(repo):
            return ""

        modules = _collect_logic_modules(repo)
        if not modules:
            return ""

        surface = _read_surface_text(repo)

        unwired, wired = [], 0
        for stem, rel in modules:
            # Substring match on the basename. Deliberately loose: an import may
            # be written a dozen ways (relative, aliased, barrel re-export), and
            # a false "wired" is much cheaper here than a false "orphan" that
            # sends the planner chasing a module that is fine.
            if stem and stem in surface:
                wired += 1
            else:
                unwired.append(rel)

        lines = ["# IMPORT GRAPH (auto-scanned):",
                 f"# {len(unwired)} UNWIRED modules (no surface references):"]
        for rel in sorted(unwired):
            lines.append(f"  UNWIRED  {rel}")
        lines.append(f"# {wired} wired modules (OK)")

        text = "\n".join(lines)
        if len(text) > max_chars:
            # Truncate on a line boundary so the prompt never ends mid-path.
            text = text[:max_chars].rsplit("\n", 1)[0] + "\n#  … truncated"
        return text
    except Exception:
        return ""


def _apply_wiring_reminders(tasks) -> list:
    """Append the reminder to tasks that create logic with no surface in scope.

    Mutates and returns the same list the caller passed, so it can be used
    inline. Returns the input unchanged on any error — a task list that reaches
    the fleet without a reminder is a smaller problem than one that never
    reaches it at all.
    """
    try:
        if not tasks:
            return tasks
        for task in tasks:
            try:
                prompt = task.get("prompt") or ""
            except Exception:
                # Not a dict. Leave it for whoever validates task shape.
                continue
            if not isinstance(prompt, str):
                continue
            touches_logic = any(d in prompt for d in LOGIC_DIRS)
            touches_surface = any(d in prompt for d in SURFACE_DIRS)
            if touches_logic and not touches_surface and WIRING_REMINDER not in prompt:
                task["prompt"] = prompt.rstrip() + "\n\n" + WIRING_REMINDER
        return tasks
    except Exception:
        return tasks


def augment_plan(tasks, repo=None):
    """`(import_context, tasks)` — the planner's single entry point.

    Returns a 2-tuple in every case, including failure, so the caller's tuple
    unpacking cannot raise.
    """
    try:
        return (_build_import_context(repo), _apply_wiring_reminders(tasks))
    except Exception:
        return ("", tasks)
