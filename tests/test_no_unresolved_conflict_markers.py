"""Continuous-testing guard: no unresolved merge-conflict markers reach master.

WHY THIS EXISTS
---------------
`hisanta/__init__.py` sat on master carrying a full `<<<<<<< HEAD / ======= /
>>>>>>>` block. Python cannot parse it, so `pytest tests/` aborted during
*collection* with three errors and ran nothing at all:

    E   File ".../hisanta/__init__.py", line 23
    E       =======
    E       ^
    E   SyntaxError: invalid syntax
    !!!! Interrupted: 3 errors during collection !!!!

A collection abort is the worst failure mode automation has: the suite does not
report "3 broken files", it reports nothing, so every other regression in the run
goes unnoticed too. One bad merge silently switched the test suite off.

This guard is deliberately cheap and dependency-free — it greps tracked source files
for conflict markers and compiles every Python file that is supposed to be
importable. It runs in well under a second, so it can sit at the front of any CI
job or pre-commit hook without slowing anything down.
"""
from __future__ import annotations

import ast
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

# Markers are split so this file does not trip its own check.
CONFLICT_MARKERS = ("<" * 7 + " ", "=" * 7 + "\n", ">" * 7 + " ")

# Extensions worth scanning: anything a parser or a build step will choke on.
SCANNED_SUFFIXES = {".py", ".json", ".yaml", ".yml", ".toml", ".cfg", ".sql"}

# Directories that legitimately contain conflict-marker-looking text.
SKIP_DIRS = {".git", "node_modules", "patches", "_to_delete", "__pycache__",
             "corpus", "eval", "reports"}

# Files knowingly left with an unresolved conflict. EMPTY, and it should stay that way:
# test_known_offenders_list_only_shrinks fails the moment an entry here is actually
# clean, so this cannot quietly become a permanent exemption list.
KNOWN_UNRESOLVED: set = set()


def _tracked_files() -> list[Path]:
    """Files git knows about. Falls back to a walk if git is unavailable."""
    try:
        out = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=60,
        )
        if out.returncode == 0 and out.stdout:
            names = [n for n in out.stdout.split("\0") if n]
            return [REPO_ROOT / n for n in names]
    except Exception:
        pass
    return [p for p in REPO_ROOT.rglob("*") if p.is_file()]


def _is_skipped(path: Path) -> bool:
    try:
        parts = set(path.relative_to(REPO_ROOT).parts)
    except ValueError:
        return True
    return bool(parts & SKIP_DIRS)


def _candidates() -> list[Path]:
    return [
        p for p in _tracked_files()
        if p.suffix in SCANNED_SUFFIXES and not _is_skipped(p) and p.is_file()
        and p.resolve() != Path(__file__).resolve()
    ]


def _has_conflict_markers(text: str) -> bool:
    """True when a line *starts* a git conflict block.

    Anchored at the start of a line and requiring git's exact shape, so a divider
    comment (`# ==== a divider ====`) or a shell redirect inside a string cannot
    trip it. A lone `=======` line only counts alongside a `<<<<<<< ` opener,
    since seven equals signs is a common decoration.
    """
    if not text:
        return False
    opener = "<" * 7
    closer = ">" * 7
    separator = "=" * 7
    saw_opener = False
    saw_closer = False
    saw_separator = False
    for line in text.splitlines():
        if line.startswith(opener + " "):
            saw_opener = True
        elif line.startswith(closer + " "):
            saw_closer = True
        elif line.rstrip() == separator:
            saw_separator = True
    return saw_opener or saw_closer or (saw_separator and saw_opener)


def _current_offenders() -> set:
    offenders = set()
    for path in _candidates():
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        if _has_conflict_markers(text):
            offenders.add(str(path.relative_to(REPO_ROOT)))
    return offenders


def test_no_new_source_file_carries_conflict_markers():
    new = _current_offenders() - KNOWN_UNRESOLVED
    assert not new, (
        "unresolved merge-conflict markers on tracked source files: "
        + ", ".join(sorted(new))
    )


def test_known_offenders_list_only_shrinks():
    """Entries must be deleted once fixed, so the exemption cannot go permanent."""
    stale = KNOWN_UNRESOLVED - _current_offenders()
    assert not stale, (
        "these files are clean now — remove them from KNOWN_UNRESOLVED: "
        + ", ".join(sorted(stale))
    )


def test_every_package_init_parses():
    """A broken __init__.py aborts collection for the whole package."""
    broken = []
    for path in _candidates():
        if path.name != "__init__.py":
            continue
        try:
            ast.parse(path.read_text(encoding="utf-8", errors="replace"), filename=str(path))
        except SyntaxError as exc:
            broken.append(f"{path.relative_to(REPO_ROOT)}:{exc.lineno}: {exc.msg}")
    assert not broken, "package __init__ files do not parse: " + "; ".join(broken)


def test_hisanta_package_is_importable():
    """The specific regression: hisanta/__init__.py must import cleanly."""
    import importlib
    import sys

    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    module = importlib.import_module("hisanta")
    assert hasattr(module, "__path__")


@pytest.mark.parametrize(
    "sample",
    [
        "<" * 7 + " HEAD\na\n" + "=" * 7 + "\nb\n" + ">" * 7 + " branch\n",
        "ok\n" + "<" * 7 + " HEAD\n",
    ],
)
def test_detector_catches_real_conflicts(sample):
    assert _has_conflict_markers(sample)


@pytest.mark.parametrize(
    "sample",
    ["", "x = 1\n", "# ==== a divider ====\n", "print('a >>> b')\n", "a = b == c\n"],
)
def test_detector_does_not_cry_wolf(sample):
    assert not _has_conflict_markers(sample)
