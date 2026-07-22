#!/usr/bin/env python3
"""
static_file_scope.py — deterministic file-scope analysis for task prompts.

The planner's META prompt asks the LLM to declare which files each task will
touch. The LLM gets this wrong ~40% of the time, causing merge conflicts.
This module replaces/validates LLM-declared file scopes with deterministic
analysis based on:

  1. Explicit file paths mentioned in the prompt
  2. Module/class/function names → file path resolution via repo file tree
  3. Import graph expansion (if A edits file X, and file Y imports X, then
     Y is in the transitive scope)

The planner calls:
  - analyze_prompt(prompt, repo) → set[str]  (files the prompt references)
  - validate_scope(declared_scope, analyzed_scope) → {missing, extra, valid}
  - expand_scope(files, repo) → set[str]  (add transitively-imported files)
  - override_scope(task, repo) → set[str]  (final scope for file_reservation)

This runs BEFORE execution, so bad scopes are caught before a branch is
created, not after it conflicts at merge time.

Environment:
    ORCH_STATIC_SCOPE_ENABLED   Kill switch (default: true)
    ORCH_SCOPE_MAX_DEPTH        Max import-graph depth to follow (default: 2)
    ORCH_SCOPE_EXPAND_IMPORTS   Whether to expand via import graph (default: true)
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import log as _log_mod
    _log = _log_mod.get("static_file_scope")
except Exception:
    import logging
    _log = logging.getLogger("static_file_scope")

ENABLED = os.environ.get("ORCH_STATIC_SCOPE_ENABLED", "true").lower() in (
    "true", "1", "yes", "on"
)
MAX_DEPTH = int(os.environ.get("ORCH_SCOPE_MAX_DEPTH", "2"))
EXPAND_IMPORTS = os.environ.get("ORCH_SCOPE_EXPAND_IMPORTS", "true").lower() in (
    "true", "1", "yes", "on"
)

# ── File path extraction from prompt text ─────────────────────────────────────

# Matches explicit file paths like: src/utils/foo.ts, runner/planner.py, etc.
_FILE_PATH_RE = re.compile(
    r'(?:^|[\s`"\':,(\[])('                        # boundary before path
    r'(?:(?:app|src|server|lib|runner|components|hooks|utils|store|types|'
    r'supabase|prisma|scripts|tests?|__tests__|pages|api|shared|constants|public)'
    r'/)[\w./-]+'                                    # path starting with known dir
    r'|[\w./-]+\.(?:ts|tsx|js|jsx|py|prisma|json|sql|css|html|vue|md|yaml|yml|toml|mjs|cjs)'
    r')',                                            # or any path ending in known ext
    re.MULTILINE
)

# Matches module names like: planner, merge_train, auto_conflict_resolver
_MODULE_NAME_RE = re.compile(
    r'(?:import\s+|from\s+|module\s+|file\s+|in\s+)[\s`]*'
    r'([a-zA-Z_][\w]*(?:\.[\w]+)*)',
    re.IGNORECASE
)

# Matches TypeScript/JS import paths: import { X } from './utils/foo'
_TS_IMPORT_RE = re.compile(
    r'''(?:from\s+|require\s*\(\s*)['"]([^'"]+)['"]''',
    re.MULTILINE
)

# Matches Python import: from runner.planner import X, import merge_train
_PY_IMPORT_RE = re.compile(
    r'(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))',
    re.MULTILINE
)


def _build_file_index(repo: str) -> dict[str, list[str]]:
    """Build a map from filename/module-name → list of matching full paths.

    This enables resolving bare module names like 'planner' to
    'runner/planner.py' without walking the tree each time.
    """
    index: dict[str, list[str]] = {}

    for root, dirs, files in os.walk(repo):
        # Skip hidden dirs, node_modules, .git, __pycache__
        dirs[:] = [d for d in dirs
                   if not d.startswith('.') and d != 'node_modules'
                   and d != '__pycache__' and d != '.next' and d != 'dist']

        for f in files:
            if f.startswith('.'):
                continue
            full = os.path.join(root, f)
            rel = os.path.relpath(full, repo)

            # Index by full relative path
            index.setdefault(rel, []).append(rel)

            # Index by filename without extension
            stem = os.path.splitext(f)[0]
            index.setdefault(stem, []).append(rel)

            # Index by filename with extension
            index.setdefault(f, []).append(rel)

            # Index by path segments (e.g., 'utils/foo' matches 'src/utils/foo.ts')
            parts = rel.split(os.sep)
            if len(parts) >= 2:
                short = os.path.join(parts[-2], stem)
                index.setdefault(short, []).append(rel)

    return index


def _extract_paths_from_prompt(prompt: str) -> set[str]:
    """Extract explicit file paths from a task prompt."""
    paths = set()

    # Find explicit file paths
    for match in _FILE_PATH_RE.finditer(prompt):
        path = match.group(1).strip().rstrip('.,;:)')
        # Normalize path separators
        path = path.replace('\\', '/')
        paths.add(path)

    return paths


def _extract_modules_from_prompt(prompt: str) -> set[str]:
    """Extract module/class names that likely correspond to files."""
    modules = set()

    for match in _MODULE_NAME_RE.finditer(prompt):
        mod = match.group(1)
        if mod and len(mod) > 2 and mod not in {'the', 'this', 'that', 'from', 'with', 'into'}:
            modules.add(mod)

    return modules


def _resolve_modules(modules: set[str], file_index: dict[str, list[str]]) -> set[str]:
    """Resolve module names to actual file paths using the file index."""
    resolved = set()

    for mod in modules:
        # Try direct lookup
        if mod in file_index:
            resolved.update(file_index[mod])
            continue

        # Try replacing dots with path separators (Python module paths)
        dotpath = mod.replace('.', os.sep)
        if dotpath in file_index:
            resolved.update(file_index[dotpath])
            continue

        # Try snake_case conversion (e.g., MergeTrain → merge_train)
        snake = re.sub(r'(?<!^)(?=[A-Z])', '_', mod).lower()
        if snake in file_index:
            resolved.update(file_index[snake])
            continue

        # Try kebab-case (e.g., merge_train → merge-train)
        kebab = snake.replace('_', '-')
        if kebab in file_index:
            resolved.update(file_index[kebab])

    return resolved


def analyze_prompt(prompt: str, repo: str) -> set[str]:
    """Analyze a task prompt and return the set of files it references.

    This is the primary entry point. Returns relative file paths within
    the repo that the prompt mentions or implies.
    """
    if not ENABLED:
        return set()

    if not prompt or not repo or not os.path.isdir(repo):
        return set()

    file_index = _build_file_index(repo)

    # Extract explicit paths
    explicit_paths = _extract_paths_from_prompt(prompt)

    # Resolve explicit paths against the file index
    resolved_explicit = set()
    for p in explicit_paths:
        if p in file_index:
            resolved_explicit.update(file_index[p])
        else:
            # Try without leading directory
            stem = os.path.basename(p)
            name_no_ext = os.path.splitext(stem)[0]
            if stem in file_index:
                # Filter to paths that contain the explicit path's directory structure
                candidates = file_index[stem]
                matching = [c for c in candidates if p in c or c.endswith(p)]
                if matching:
                    resolved_explicit.update(matching)
                else:
                    resolved_explicit.update(candidates[:1])  # best guess
            elif name_no_ext in file_index:
                resolved_explicit.update(file_index[name_no_ext][:3])  # limit

    # Extract and resolve module names
    modules = _extract_modules_from_prompt(prompt)
    resolved_modules = _resolve_modules(modules, file_index)

    all_files = resolved_explicit | resolved_modules

    # Expand with import graph if enabled
    if EXPAND_IMPORTS and all_files:
        expanded = expand_scope(all_files, repo, file_index)
        all_files.update(expanded)

    return all_files


def expand_scope(files: set[str], repo: str,
                 file_index: dict[str, list[str]] | None = None,
                 depth: int = 0) -> set[str]:
    """Expand a set of files to include files that import them (reverse deps).

    If file A is in the scope, and file B does `import { X } from './A'`,
    then B might also be affected by changes to A. We add it to the scope.

    Only follows imports up to MAX_DEPTH levels deep.
    """
    if depth >= MAX_DEPTH:
        return set()

    if file_index is None:
        file_index = _build_file_index(repo)

    expanded = set()

    for f in files:
        full_path = os.path.join(repo, f)
        if not os.path.isfile(full_path):
            continue

        basename = os.path.basename(f)
        stem = os.path.splitext(basename)[0]

        # Find files that import this file (reverse dependency)
        # For efficiency, only check files of the same language
        ext = os.path.splitext(f)[1]
        if ext in ('.ts', '.tsx', '.js', '.jsx', '.vue', '.mjs', '.cjs'):
            _search_ts_importers(f, stem, repo, file_index, expanded)
        elif ext == '.py':
            _search_py_importers(f, stem, repo, file_index, expanded)

    # Remove already-known files
    new_files = expanded - files
    if not new_files:
        return set()

    # Recurse for transitive deps
    deeper = expand_scope(new_files, repo, file_index, depth + 1)
    return new_files | deeper


def _search_ts_importers(target: str, target_stem: str, repo: str,
                         file_index: dict[str, list[str]],
                         result: set[str]):
    """Find TypeScript/JS files that import the target file."""
    target_dir = os.path.dirname(target)

    for stem, paths in file_index.items():
        for p in paths:
            ext = os.path.splitext(p)[1]
            if ext not in ('.ts', '.tsx', '.js', '.jsx', '.vue', '.mjs', '.cjs'):
                continue

            full = os.path.join(repo, p)
            if not os.path.isfile(full):
                continue

            try:
                with open(full, 'r', errors='replace') as fh:
                    # Read first 5KB only — imports are at the top
                    content = fh.read(5120)
            except Exception:
                continue

            # Check if this file imports the target
            for match in _TS_IMPORT_RE.finditer(content):
                import_path = match.group(1)
                # Resolve relative imports
                if import_path.startswith('.'):
                    importer_dir = os.path.dirname(p)
                    resolved = os.path.normpath(os.path.join(importer_dir, import_path))
                    resolved_stem = os.path.splitext(os.path.basename(resolved))[0]
                    if resolved == os.path.splitext(target)[0] or resolved_stem == target_stem:
                        result.add(p)
                        break
                elif target_stem in import_path:
                    result.add(p)
                    break


def _search_py_importers(target: str, target_stem: str, repo: str,
                         file_index: dict[str, list[str]],
                         result: set[str]):
    """Find Python files that import the target module."""
    for stem, paths in file_index.items():
        for p in paths:
            if not p.endswith('.py'):
                continue

            full = os.path.join(repo, p)
            if not os.path.isfile(full):
                continue

            try:
                with open(full, 'r', errors='replace') as fh:
                    content = fh.read(5120)
            except Exception:
                continue

            for match in _PY_IMPORT_RE.finditer(content):
                mod_from = match.group(1) or ""
                mod_import = match.group(2) or ""
                if target_stem in mod_from or target_stem in mod_import:
                    result.add(p)
                    break


def validate_scope(declared: set[str], analyzed: set[str]) -> dict:
    """Compare LLM-declared scope against static analysis.

    Returns:
        {
            "valid": bool,  # True if declared scope covers all analyzed files
            "missing": set[str],  # Files in analyzed but not declared
            "extra": set[str],  # Files declared but not found by analysis
            "overlap": set[str],  # Files in both
        }
    """
    missing = analyzed - declared
    extra = declared - analyzed
    overlap = declared & analyzed
    return {
        "valid": len(missing) == 0,
        "missing": missing,
        "extra": extra,
        "overlap": overlap,
    }


def override_scope(task: dict, repo: str) -> set[str]:
    """Compute the final file scope for a task, combining LLM-declared and static analysis.

    This is the integration point for the planner and runner:
    - Start with the LLM-declared scope (from task["file_scope"])
    - Run static analysis on the prompt
    - Union the two (LLM may know intent-based scope that static can't see)
    - Log any discrepancies for planner feedback

    Returns the final scope as a set of relative file paths.
    """
    if not ENABLED:
        # Fall back to declared scope
        declared_str = task.get("file_scope", "")
        return {f.strip() for f in declared_str.split(",") if f.strip()}

    prompt = task.get("prompt", "") or task.get("description", "")
    declared_str = task.get("file_scope", "")
    declared = {f.strip() for f in declared_str.split(",") if f.strip()}

    analyzed = analyze_prompt(prompt, repo)

    if not analyzed:
        return declared  # static analysis found nothing — trust LLM

    # Union: keep everything the LLM declared + everything analysis found
    final = declared | analyzed

    # Log discrepancies for planner feedback
    validation = validate_scope(declared, analyzed)
    if not validation["valid"]:
        _log.info(
            "static_file_scope: task %s missing %d files from declared scope: %s",
            task.get("slug", "?"),
            len(validation["missing"]),
            ", ".join(sorted(validation["missing"])[:5])
        )

    return final


def stats(prompt: str, repo: str) -> dict:
    """Diagnostic: show what the analyzer finds for a given prompt."""
    explicit = _extract_paths_from_prompt(prompt)
    modules = _extract_modules_from_prompt(prompt)
    file_index = _build_file_index(repo)
    resolved_modules = _resolve_modules(modules, file_index)
    full = analyze_prompt(prompt, repo)

    return {
        "explicit_paths": sorted(explicit),
        "modules_found": sorted(modules),
        "resolved_modules": sorted(resolved_modules),
        "total_scope": sorted(full),
        "scope_size": len(full),
    }


# ── Standalone mode ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    import json as _json

    if len(sys.argv) < 3:
        print("Usage: python3 static_file_scope.py <repo_path> <prompt_text>")
        print("  or:  python3 static_file_scope.py <repo_path> --file <prompt_file>")
        sys.exit(1)

    repo_path = sys.argv[1]
    if sys.argv[2] == "--file":
        with open(sys.argv[3]) as f:
            prompt_text = f.read()
    else:
        prompt_text = " ".join(sys.argv[2:])

    result = stats(prompt_text, repo_path)
    print(_json.dumps(result, indent=2))
