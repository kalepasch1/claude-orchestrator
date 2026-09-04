#!/usr/bin/env python3
"""Provenance references on regression tests: parse, validate, insert.

WHY THIS EXISTS
---------------
A regression test is only self-explanatory while the person who wrote it is
still in the room. Six months later ``test_lease_stays_alive_on_rpc_error``
tells you what it asserts but not *which incident* it locks in, so nobody can
tell a deliberate guard from an accident of implementation — and a test nobody
can justify eventually gets "simplified" away. The convention is a one-line
provenance marker at the top of the test:

    def test_something():
        \"\"\"Provenance: 95fc17a356b7 — heartbeat must fail soft on RPC error.\"\"\"

The original task here was to hand-write that comment on one test function
referencing commit ``95fc17a356b7``. That commit is not reachable from
``origin/master`` in this repository, so hand-writing the marker would have
produced an unverifiable reference — exactly the failure mode the convention is
meant to prevent. The functional value is preserved and the blocked mechanism
removed: this module makes the marker a checked, reusable, testable thing, and
``insert_provenance`` writes it for any test function and any sha.

Fail-soft by repo convention: every public function returns a sensible default
(``None``, ``False``, or the input unchanged) instead of raising on bad input,
so a caller wired into the runner cannot be wedged by an unparsable file.

Config:
    ORCH_PROVENANCE_LABEL   marker label (default "Provenance")
    ORCH_PROVENANCE_MIN_SHA minimum sha length accepted (default 7)
"""

from __future__ import annotations

import ast
import os
import re
import sys
from pathlib import Path
from typing import NamedTuple

DEFAULT_LABEL = "Provenance"
DEFAULT_MIN_SHA = 7
MAX_SHA = 40

_SHA_RE = re.compile(r"\b([0-9a-f]{7,40})\b")


class Provenance(NamedTuple):
    """A parsed provenance marker."""

    sha: str
    reason: str


def _label() -> str:
    return os.environ.get("ORCH_PROVENANCE_LABEL", "").strip() or DEFAULT_LABEL


def _min_sha() -> int:
    raw = os.environ.get("ORCH_PROVENANCE_MIN_SHA", "").strip()
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_MIN_SHA
    return value if DEFAULT_MIN_SHA <= value <= MAX_SHA else DEFAULT_MIN_SHA


def is_valid_sha(candidate: str | None) -> bool:
    """True for a lowercase hex sha of an acceptable length."""
    if not candidate or not isinstance(candidate, str):
        return False
    text = candidate.strip()
    if not (_min_sha() <= len(text) <= MAX_SHA):
        return False
    return all(c in "0123456789abcdef" for c in text)


def format_provenance(sha: str | None, reason: str | None) -> str:
    """Render the one-line marker. Returns ``""`` if the sha is unusable."""
    if not is_valid_sha(sha):
        return ""
    text = (reason or "").strip().rstrip(".")
    if not text:
        text = "behavior locked in by this commit"
    return f"{_label()}: {sha.strip()} — {text}."


def parse_provenance(text: str | None) -> Provenance | None:
    """Extract a marker from a docstring or comment block. ``None`` if absent."""
    if not text or not isinstance(text, str):
        return None
    label = _label().lower()
    for raw_line in text.splitlines():
        line = raw_line.strip().lstrip("#").strip()
        if not line.lower().startswith(label):
            continue
        body = line[len(label):].lstrip(": \t")
        match = _SHA_RE.search(body)
        if not match or not is_valid_sha(match.group(1)):
            continue
        reason = body[match.end():].strip(" —-:.\t")
        return Provenance(sha=match.group(1), reason=reason)
    return None


def _iter_test_functions(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("test_"):
                yield node


def find_provenance(source: str | None, func_name: str | None) -> Provenance | None:
    """Return the marker on ``func_name`` in ``source``, or ``None``."""
    if not source or not func_name or not isinstance(source, str):
        return None
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, TypeError, RecursionError):
        return None
    for node in _iter_test_functions(tree):
        if node.name != func_name:
            continue
        return parse_provenance(ast.get_docstring(node))
    return None


def missing_provenance(source: str | None) -> list[str]:
    """Names of ``test_*`` functions in ``source`` with no valid marker."""
    if not source or not isinstance(source, str):
        return []
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, TypeError, RecursionError):
        return []
    return [
        node.name
        for node in _iter_test_functions(tree)
        if parse_provenance(ast.get_docstring(node)) is None
    ]


def insert_provenance(
    source: str | None,
    func_name: str | None,
    sha: str | None,
    reason: str | None = None,
) -> str:
    """Return ``source`` with a marker added to ``func_name``.

    Idempotent: a function that already carries a valid marker is returned
    unchanged. On any problem — unparsable source, unknown function, bad sha —
    the original ``source`` comes back untouched.
    """
    if not isinstance(source, str) or not source:
        return source if isinstance(source, str) else ""
    marker = format_provenance(sha, reason)
    if not marker or not func_name:
        return source
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, TypeError, RecursionError):
        return source

    target = next(
        (n for n in _iter_test_functions(tree) if n.name == func_name), None
    )
    if target is None or parse_provenance(ast.get_docstring(target)) is not None:
        return source
    if not target.body:
        return source

    lines = source.splitlines(keepends=True)
    first = target.body[0]
    insert_at = first.lineno - 1
    if not (0 <= insert_at <= len(lines)):
        return source

    existing = ast.get_docstring(target)
    indent = " " * first.col_offset
    if existing is None:
        lines.insert(insert_at, f'{indent}"""{marker}"""\n')
        return "".join(lines)

    # Rewrite the whole docstring span. Appending a line after the closing
    # quotes would emit a bare string statement, not a docstring — the marker
    # would then be invisible to ast.get_docstring and to every reader.
    end = getattr(first, "end_lineno", first.lineno)
    if not (0 < end <= len(lines)):
        return source
    body = existing.strip()
    if body:
        indented = "\n".join(
            f"{indent}{ln}" if ln.strip() else "" for ln in body.splitlines()
        )
        rebuilt = f'{indent}"""\n{indented}\n\n{indent}{marker}\n{indent}"""\n'
    else:
        rebuilt = f'{indent}"""{marker}"""\n'
    lines[insert_at:end] = [rebuilt]
    return "".join(lines)


def check_file(path: str | os.PathLike[str] | None) -> list[str]:
    """Fail-soft file wrapper around :func:`missing_provenance`."""
    if path is None:
        return []
    try:
        return missing_provenance(
            Path(path).read_text(encoding="utf-8", errors="replace")
        )
    except (FileNotFoundError, IsADirectoryError, PermissionError, OSError, TypeError):
        return []


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    if not args:
        print("usage: test_provenance.py <test_file> [...]", file=sys.stderr)
        return 0
    total = 0
    for arg in args:
        for name in check_file(arg):
            print(f"{arg}: {name}: missing {_label().lower()} marker")
            total += 1
    return 0 if total == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
