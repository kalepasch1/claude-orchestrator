#!/usr/bin/env python3
"""Ensure a test file exists for the module named in ``test-module-info.json``.

Canary/scaffolding helper: agents repeatedly hand-rolled "read the module path,
derive the module name, make sure ``tests/test_<name>.py`` exists" inline. This
centralises it so the behaviour is one implementation with one test.

Fail-soft by contract (repo convention): every public function returns a
sensible default rather than raising on bad input — a missing info file, a
malformed JSON body, or an unwritable path all yield ``""`` instead of a
traceback, so callers embedded in the runner never wedge.

Config is env-var driven:
    ORCH_TEST_INFO_FILE  name of the info file        (default test-module-info.json)
    ORCH_TEST_DIRS       ':'-separated candidate dirs  (default "tests:test")
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

DEFAULT_INFO_FILE = "test-module-info.json"
DEFAULT_TEST_DIRS = ("tests", "test")


def _info_file_name() -> str:
    return os.environ.get("ORCH_TEST_INFO_FILE", "").strip() or DEFAULT_INFO_FILE


def _candidate_test_dirs() -> tuple[str, ...]:
    raw = os.environ.get("ORCH_TEST_DIRS", "").strip()
    if not raw:
        return DEFAULT_TEST_DIRS
    parts = tuple(p.strip() for p in raw.split(":") if p.strip())
    return parts or DEFAULT_TEST_DIRS


def read_module_path(repo_root: str | os.PathLike[str] | None) -> str:
    """Return ``module_path`` from the info file, or ``""`` if unavailable."""
    if repo_root is None:
        return ""
    try:
        path = Path(repo_root) / _info_file_name()
        raw = path.read_text(encoding="utf-8", errors="replace")
    except (FileNotFoundError, NotADirectoryError, PermissionError, OSError, TypeError):
        return ""
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return ""
    if not isinstance(data, dict):
        return ""
    value = data.get("module_path")
    return value.strip() if isinstance(value, str) else ""


def module_name_from_path(module_path: str | None) -> str:
    """``src/utils.py`` -> ``utils``. Returns ``""`` on anything unusable."""
    if not module_path or not isinstance(module_path, str):
        return ""
    stem = Path(module_path.strip()).stem
    # A trailing separator or a bare "." leaves an empty/dot stem.
    if not stem or stem in {".", ".."}:
        return ""
    return stem


def resolve_test_dir(repo_root: str | os.PathLike[str] | None) -> str:
    """Pick the existing test directory; fall back to the first candidate."""
    candidates = _candidate_test_dirs()
    if repo_root is None:
        return candidates[0]
    try:
        root = Path(repo_root)
        for name in candidates:
            if (root / name).is_dir():
                return name
    except (OSError, TypeError):
        pass
    return candidates[0]


def ensure_test_file(repo_root: str | os.PathLike[str] | None) -> str:
    """Create ``<testdir>/test_<module>.py`` if missing.

    Returns the repo-relative path of the file that exists afterwards, or ``""``
    if nothing could be determined or written. Idempotent: an existing file is
    left byte-for-byte untouched.
    """
    module_name = module_name_from_path(read_module_path(repo_root))
    if not module_name:
        return ""
    try:
        root = Path(repo_root)  # type: ignore[arg-type]
        rel = Path(resolve_test_dir(repo_root)) / f"test_{module_name}.py"
        target = root / rel
        if target.exists():
            return str(rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.touch()
        return str(rel)
    except (OSError, TypeError, ValueError):
        return ""


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    repo_root = args[0] if args else os.getcwd()
    result = ensure_test_file(repo_root)
    if not result:
        print("ensure_test_file: no test file resolved (fail-soft)", file=sys.stderr)
        return 0
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
