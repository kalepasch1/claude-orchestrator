#!/usr/bin/env python3
"""Resolve committed merge-conflict markers by keeping one side per file.

Conflict markers reached master in four hisanta files, so those modules are not valid
Python at all — `import hisanta` raises SyntaxError and three test modules cannot even be
collected. This applies the resolution mechanically so the diff is auditable: for each
file, every conflict hunk keeps the SAME side, and nothing else is edited.

Usage:
    python3 scripts/resolve_conflict_markers.py [--check] [path ...]

--check reports files that still contain markers and exits non-zero — usable as a
pre-merge guard so this class of breakage cannot land again.
"""
import argparse
import os
import re
import sys

START = re.compile(r"^<<<<<<< ")
MIDDLE = re.compile(r"^=======\s*$")
END = re.compile(r"^>>>>>>> ")


def split_conflicts(lines):
    """Yield ('text', line) or ('conflict', ours, theirs) in source order.

    Unterminated hunks are yielded as plain text rather than guessed at — a truncated
    conflict is a file to look at by hand, not one to silently half-resolve.
    """
    i, n = 0, len(lines)
    while i < n:
        if not START.match(lines[i]):
            yield ("text", lines[i])
            i += 1
            continue
        mid = end = None
        for j in range(i + 1, n):
            if mid is None and MIDDLE.match(lines[j]):
                mid = j
            elif mid is not None and END.match(lines[j]):
                end = j
                break
        if mid is None or end is None:
            yield ("text", lines[i])
            i += 1
            continue
        yield ("conflict", lines[i + 1:mid], lines[mid + 1:end])
        i = end + 1


def resolve(text, side="theirs"):
    """Return `text` with every conflict hunk collapsed to one side."""
    out = []
    for item in split_conflicts(text.splitlines(keepends=True)):
        if item[0] == "text":
            out.append(item[1])
        else:
            out.extend(item[1] if side == "ours" else item[2])
    return "".join(out)


def has_markers(text):
    return any(START.match(l) or END.match(l) for l in text.splitlines())


def find_marked(root="."):
    """Every tracked-looking source file that still contains conflict markers."""
    hits = []
    skip = {".git", "node_modules", "__pycache__", ".venv", ".runtime", ".pytest_cache"}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in skip]
        for name in filenames:
            if not name.endswith((".py", ".ts", ".tsx", ".js", ".vue", ".json", ".sql")):
                continue
            path = os.path.join(dirpath, name)
            try:
                with open(path, encoding="utf-8", errors="replace") as fh:
                    if has_markers(fh.read()):
                        hits.append(path)
            except OSError:
                continue
    return sorted(hits)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="*")
    ap.add_argument("--side", choices=("ours", "theirs"), default="theirs")
    ap.add_argument("--check", action="store_true",
                    help="report files containing markers; exit 1 if any")
    args = ap.parse_args(argv)

    if args.check:
        hits = find_marked(args.paths[0] if args.paths else ".")
        for path in hits:
            print(f"conflict markers still present: {path}")
        return 1 if hits else 0

    for path in args.paths:
        with open(path, encoding="utf-8") as fh:
            original = fh.read()
        resolved = resolve(original, args.side)
        if resolved != original:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(resolved)
            print(f"resolved ({args.side}): {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
