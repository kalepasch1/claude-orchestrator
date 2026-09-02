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
    "GitPython": "git",
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


def main() -> int:
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))

    missing: list[str] = []
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
