"""Repository guard: no unresolved git conflict markers may be committed.

A merge that is committed while still carrying `<<<<<<<` / `=======` / `>>>>>>>`
lines produces a file that is syntactically broken but often still importable
(Python comments, Markdown, JSON-with-comments), so it survives review and
wedges the runner at import time much later. This test scans the tracked tree
and fails loudly instead.

The marker strings are assembled at runtime from a character and a repeat count
so that this file itself never contains a literal marker (which would make the
check fail on itself, and would also break `git merge` on this file).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Assembled, never literal. "<" * 7, "=" * 7, ">" * 7 followed by a space or EOL.
_OURS = "<" * 7
_SEP = "=" * 7
_THEIRS = ">" * 7
CONFLICT_PREFIXES = (_OURS, _SEP, _THEIRS)

# Binary/vendored trees that are never hand-merged.
SKIP_DIR_PARTS = {
    ".git",
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
    ".mypy_cache",
    ".pytest_cache",
    "dist",
    "build",
    ".next",
    ".nuxt",
}

TEXT_SUFFIXES = {
    ".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".vue",
    ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg",
    ".md", ".txt", ".sh", ".sql", ".html", ".css",
}

# This file legitimately talks about markers; it never contains literal ones,
# but keep it out of the scan so a future docstring edit cannot self-trip.
SELF = Path(__file__).resolve()


def _tracked_files() -> list[Path]:
    """Tracked files per git; falls back to a walk when git is unavailable."""
    try:
        out = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "ls-files", "-z"],
            capture_output=True,
            check=True,
            timeout=60,
        ).stdout.decode("utf-8", errors="replace")
        names = [n for n in out.split("\0") if n]
        return [REPO_ROOT / n for n in names]
    except Exception:  # fail-soft: never let the guard itself wedge the suite
        found: list[Path] = []
        for dirpath, dirnames, filenames in os.walk(REPO_ROOT):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIR_PARTS]
            for name in filenames:
                found.append(Path(dirpath) / name)
        return found


def find_conflict_markers(paths=None) -> list[str]:
    """Return "path:lineno: marker" strings for every conflict marker found."""
    hits: list[str] = []
    for path in _tracked_files() if paths is None else paths:
        try:
            resolved = path.resolve()
        except OSError:
            continue
        if resolved == SELF:
            continue
        if SKIP_DIR_PARTS.intersection(resolved.parts):
            continue
        if path.suffix and path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except (FileNotFoundError, IsADirectoryError, PermissionError, OSError):
            continue
        rel = path.relative_to(REPO_ROOT) if REPO_ROOT in path.parents else path
        pending: list[str] = []
        saw_ours = False
        for lineno, line in enumerate(text.splitlines(), start=1):
            for prefix in CONFLICT_PREFIXES:
                # A real marker is the 7 chars alone on the line, or followed
                # by a space and a ref name. Eight-plus of the same char is not.
                if not line.startswith(prefix):
                    continue
                rest = line[len(prefix):]
                if rest != "" and not rest.startswith(" "):
                    continue
                if prefix is _OURS:
                    saw_ours = True
                    hits.append(f"{rel}:{lineno}: {prefix}")
                elif prefix is _THEIRS:
                    hits.append(f"{rel}:{lineno}: {prefix}")
                else:
                    # A bare row of '=' is also a Markdown setext underline.
                    # Only a separator that follows an ours-marker is a conflict.
                    if saw_ours:
                        hits.append(f"{rel}:{lineno}: {prefix}")
                    else:
                        pending.append(f"{rel}:{lineno}: {prefix}")
                break
        if saw_ours and pending:
            hits.extend(pending)
    return hits


def test_no_conflict_markers_in_tracked_files():
    hits = find_conflict_markers()
    assert not hits, (
        "Unresolved git conflict markers found in tracked files:\n  "
        + "\n  ".join(hits)
    )


def test_detector_flags_a_synthetic_conflict(tmp_path):
    """Proof the check works without leaving markers in the tree."""
    victim = tmp_path / "victim.py"
    victim.write_text(
        "\n".join(
            [
                "x = 1",
                _OURS + " HEAD",
                "y = 2",
                _SEP,
                "y = 3",
                _THEIRS + " agent/branch",
            ]
        ),
        encoding="utf-8",
    )
    hits = find_conflict_markers([victim])
    assert len(hits) == 3, hits


def test_detector_ignores_lookalike_lines(tmp_path):
    """Six angle brackets, or markers mid-line, are not conflicts."""
    ok = tmp_path / "ok.md"
    ok.write_text(
        "\n".join(
            [
                "<" * 6,
                "a " + _OURS + " b",
                "=" * 5,
                "normal text",
            ]
        ),
        encoding="utf-8",
    )
    assert find_conflict_markers([ok]) == []
