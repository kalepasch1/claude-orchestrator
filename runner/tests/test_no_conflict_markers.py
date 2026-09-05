#!/usr/bin/env python3
"""Repo-wide guard: no git conflict markers may be committed.

WHY
---
On 2026-08-24 four files were found sitting on origin/master with unresolved conflict
markers, all from one agent branch, all failing to compile. They had been there long
enough for several tasks to be opened against downstream symptoms rather than the
cause. Nothing in the repo was checking, so the only way to find them was to go
looking.

This is the check. It is deliberately the narrowest possible one — three literal
strings, anchored to the start of a line — because a broad linter over this tree would
be red on arrival for a dozen unrelated reasons, and a permanently-red check teaches
people to ignore checks. `.github/workflows/ci.yml` already makes that argument at
length about the runner test suite; the same reasoning applies here.

Scope: tracked, non-binary files, via `git ls-files`. Untracked scratch is not the
repo's problem, and asking git for the file list means generated trees (node_modules,
dist, .venv) are excluded for free rather than through a maintained ignore list.
"""
import os
import re
import subprocess

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Anchored to line start. An unanchored search matches this file's own docstring, every
# test that constructs a marker as a fixture, and any prose describing a merge — which
# is how a guard like this earns a reputation for crying wolf and gets deleted.
MARKERS = (
    re.compile(r"^<{7}(?: |$)"),
    re.compile(r"^={7}$"),
    re.compile(r"^>{7}(?: |$)"),
)

# Files that legitimately contain marker-shaped lines: tests that build a conflicted
# fixture, and docs that quote one. Kept as an explicit, short list so that adding to it
# is a visible decision rather than a silent widening of the rule.
ALLOWLIST = frozenset({
    "runner/tests/test_no_conflict_markers.py",
    "runner/tests/test_config_consumer_integrity.py",
})

# `=======` is also valid Markdown (a setext H1 underline) and shows up in ASCII table
# borders, so on its own it is not evidence of a conflict. Only flag it when the file
# also carries one of the unambiguous markers.
_UNAMBIGUOUS = (MARKERS[0], MARKERS[2])

SKIP_SUFFIXES = (
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf", ".zip", ".gz",
    ".woff", ".woff2", ".ttf", ".eot", ".mp4", ".mov", ".so", ".dylib", ".bin",
)


def tracked_files():
    out = subprocess.check_output(["git", "ls-files", "-z"], cwd=REPO, text=True,
                                  timeout=120)
    return [p for p in out.split("\0") if p]


def scan(path, base=None):
    """Return the line numbers in `path` that carry an unambiguous conflict marker.

    `base` is injectable so the guard's own behaviour can be tested against fixture
    files without the test having to re-import this module under a name that only
    exists when pytest happens to have put this directory on sys.path.
    """
    full = os.path.join(base or REPO, path)
    try:
        with open(full, encoding="utf-8", errors="replace") as handle:
            lines = handle.readlines()
    except (OSError, IsADirectoryError):
        return []

    if not any(m.search(line) for line in lines for m in _UNAMBIGUOUS):
        return []
    return [i for i, line in enumerate(lines, 1)
            if any(m.search(line) for m in MARKERS)]


def test_no_tracked_file_contains_conflict_markers():
    try:
        paths = tracked_files()
    except (subprocess.SubprocessError, OSError) as exc:
        pytest.skip(f"git unavailable: {exc}")

    offenders = {}
    for path in paths:
        if path in ALLOWLIST or path.lower().endswith(SKIP_SUFFIXES):
            continue
        hits = scan(path)
        if hits:
            offenders[path] = hits

    assert not offenders, (
        "Committed git conflict markers found:\n"
        + "\n".join(f"  {p}: lines {v}" for p, v in sorted(offenders.items()))
        + "\nResolve the merge. Do not delete the markers without picking a side.")


# ── the guard's own behaviour ───────────────────────────────────────────────

def test_scan_finds_a_real_conflict(tmp_path):
    (tmp_path / "conflicted.py").write_text(
        "a = 1\n" + "<" * 7 + " HEAD\nb = 2\n" + "=" * 7 + "\nb = 3\n" +
        ">" * 7 + " agent/x\n")
    assert scan("conflicted.py", base=str(tmp_path)) == [2, 4, 6]


def test_scan_ignores_a_markdown_setext_heading(tmp_path):
    """`=======` under a line is Markdown, not a conflict. Flagging it is crying wolf."""
    (tmp_path / "README.md").write_text("Title\n" + "=" * 7 + "\n\nbody\n")
    assert scan("README.md", base=str(tmp_path)) == []


def test_scan_ignores_prose_mentioning_markers(tmp_path):
    (tmp_path / "notes.md").write_text(
        "A bad merge leaves <<<<<<< and >>>>>>> in the file.\n")
    assert scan("notes.md", base=str(tmp_path)) == []


def test_scan_ignores_an_ascii_table_border(tmp_path):
    (tmp_path / "t.md").write_text("| a | b |\n" + "=" * 7 + "\n")
    assert scan("t.md", base=str(tmp_path)) == []


def test_scan_is_fail_soft_on_a_missing_file(tmp_path):
    assert scan("does-not-exist.py", base=str(tmp_path)) == []


def test_scan_is_fail_soft_on_a_directory(tmp_path):
    (tmp_path / "adir").mkdir()
    assert scan("adir", base=str(tmp_path)) == []
