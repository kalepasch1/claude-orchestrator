#!/usr/bin/env python3
"""Acceptance check for the dependency manifest.

Fails loudly if either
  (a) a package declared in requirements.txt / requirements-dev.txt is not
      importable, or
  (b) the primary project package (`runner`) cannot be imported.

Run after `pip install -r requirements-dev.txt`:

    python3 scripts/verify_deps.py
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Distribution name -> import name, for the cases where they differ.
IMPORT_NAME = {
    "PyYAML": "yaml",
    "python-dateutil": "dateutil",
    "python-dotenv": "dotenv",
    "prometheus-client": "prometheus_client",
    "pytest-timeout": "pytest_timeout",
}


def declared_packages(manifest: Path) -> list[str]:
    if not manifest.is_file():
        return []
    names = []
    for raw in manifest.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        for sep in (">=", "==", "<=", "~=", ">", "<", "["):
            if sep in line:
                line = line.split(sep, 1)[0]
        names.append(line.strip())
    return names


# ── the reverse direction: imported but NOT declared ──────────────────────────────────
#
# The check above only proves that what IS declared can be imported. It says nothing
# about a third-party module that `runner/` imports and the manifest never mentions —
# which is the exact failure requirements.txt's own header describes: a fresh clone ran
# `pip install -r requirements.txt` and still could not import large parts of runner/.
# That direction was never verified, so the manifest could silently rot again the moment
# anyone added an import. It is checked here.
#
# Import name -> distribution, for the cases where they differ (inverse of IMPORT_NAME).
DIST_NAME = {module: dist for dist, module in IMPORT_NAME.items()}

#: Third-party imports that are deliberately OPTIONAL — every use site guards them, so a
#: missing one degrades rather than breaks. Declaring them would force an install nobody
#: needs; leaving them unlisted is the decision, and naming them here records it.
OPTIONAL_IMPORTS = {
    "claude_agent_sdk",   # SDK path in claude_cli; falls back to the CLI subprocess
    "openai", "google", "groq", "ollama", "httpx",  # provider SDKs, lazily imported
    "supabase", "psycopg2", "numpy", "pandas",
    "pytest", "pytest_timeout", "hypothesis",       # dev-only, declared in the dev file
    "nodeenv", "dotenv",
}


def _stdlib_modules() -> set[str]:
    """Top-level stdlib module names for the running interpreter.

    `sys.stdlib_module_names` is 3.10+. On 3.9 fall back to probing the module search
    path, so this check does not silently pass by classifying everything as stdlib.
    """
    names = getattr(sys, "stdlib_module_names", None)
    if names:
        return set(names)
    import distutils.sysconfig as sysconfig  # noqa: PLC0415
    import os
    import pkgutil
    stdlib_dir = sysconfig.get_python_lib(standard_lib=True)
    # lib-dynload holds the compiled stdlib extensions (fcntl, math, select, ...). Omitting
    # it made the fallback report `math` as an undeclared third-party dependency.
    search = [stdlib_dir, os.path.join(stdlib_dir, "lib-dynload")]
    found = {m.name for m in pkgutil.iter_modules([p for p in search if os.path.isdir(p)])}
    found |= set(getattr(sys, "builtin_module_names", ()))
    if os.path.isdir(stdlib_dir):
        found |= {n for n in os.listdir(stdlib_dir) if n.endswith(".py")}
    return {n[:-3] if n.endswith(".py") else n for n in found}


_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".runtime",
              ".pytest_cache", "dist", "build", ".next", ".output", ".vercel"}


def local_module_names(package_dirs=("runner", "scripts", "tests", "tools")) -> set[str]:
    """Names that resolve to files IN THIS REPO rather than to installed packages.

    Scanned recursively. A shallow scan of each directory's top level was not enough:
    runner/tests/ and runner/tools/ put dozens of local modules one level down, and every
    one of them was reported as a missing third-party dependency.
    """
    import os
    names: set[str] = set()
    for directory in package_dirs:
        root = REPO_ROOT / directory
        if not root.is_dir():
            continue
        names.add(directory)
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
            names.update(os.path.basename(d) for d in dirnames)
            names.update(f[:-3] for f in filenames if f.endswith(".py"))
    return names


def imported_top_level(path: Path, include_guarded: bool = False) -> set[str]:
    """Top-level module names imported by one Python file. Never raises.

    Imports inside a `try:` are EXCLUDED by default. A guarded import is optional by
    construction — this repo's fail-soft convention is exactly `try: import x / except:
    fall back` — so requiring it in the manifest would force an install the code is
    written not to need. `redis` and `websocket` are both of this kind.
    """
    import ast
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return set()

    guarded: set[int] = set()
    if not include_guarded:
        for node in ast.walk(tree):
            if isinstance(node, ast.Try):
                for child in ast.walk(node):
                    guarded.add(id(child))

    found: set[str] = set()
    for node in ast.walk(tree):
        if id(node) in guarded:
            continue
        if isinstance(node, ast.Import):
            found |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            # `from . import x` has no module name to resolve — it is always local.
            if node.level == 0 and node.module:
                found.add(node.module.split(".")[0])
    return found


def undeclared_imports(package_dirs=("runner",)) -> list[str]:
    """Third-party distributions imported by the source but absent from the manifests.

    Fail-soft by construction: anything stdlib, local, optional or already declared is
    excluded, so a false positive requires a genuinely new undeclared dependency.
    """
    declared = set()
    for manifest in ("requirements.txt", "requirements-dev.txt"):
        for dist in declared_packages(REPO_ROOT / manifest):
            declared.add(dist.lower())
            declared.add(IMPORT_NAME.get(dist, dist.replace("-", "_")).lower())
    ignore = _stdlib_modules() | local_module_names() | OPTIONAL_IMPORTS
    ignore = {n.lower() for n in ignore}

    offenders: dict[str, str] = {}
    for directory in package_dirs:
        root = REPO_ROOT / directory
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.py")):
            # Test files are excluded on purpose. This check is about what the RUNTIME
            # needs to import on a fresh clone. A test importing a module that does not
            # exist is a broken test, not a missing distribution, and reporting it here
            # under "not in any requirements file" would send the reader to pip for a
            # problem pip cannot fix.
            if "__pycache__" in path.parts or "tests" in path.parts:
                continue
            for module in imported_top_level(path):
                key = module.lower()
                if key in ignore or key in declared:
                    continue
                offenders.setdefault(
                    DIST_NAME.get(module, module),
                    str(path.relative_to(REPO_ROOT)))
    return [f"{dist} (imported by {site}) is not in any requirements file"
            for dist, site in sorted(offenders.items())]


def main() -> int:
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))

    missing: list[str] = list(undeclared_imports())
    for manifest in ("requirements.txt", "requirements-dev.txt"):
        for dist in declared_packages(REPO_ROOT / manifest):
            module = IMPORT_NAME.get(dist, dist.replace("-", "_"))
            try:
                importlib.import_module(module)
            except Exception as exc:  # noqa: BLE001 - report, do not mask
                missing.append(f"{dist} (import {module}): {exc}")

    try:
        importlib.import_module("runner")
    except Exception as exc:  # noqa: BLE001
        missing.append(f"runner (primary package): {exc}")

    if missing:
        print("DEPENDENCY CHECK FAILED", file=sys.stderr)
        for item in missing:
            print(f"  - {item}", file=sys.stderr)
        print("\nRun: pip install -r requirements-dev.txt", file=sys.stderr)
        return 1

    print("ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
