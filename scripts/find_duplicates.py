#!/usr/bin/env python3
"""Inventory duplicated top-level symbols across a topic cluster of Python files.

Built for the pricing-grid-reconstruction cleanup, but the topic is a CLI argument
so it works for any duplication sweep.

    python3 scripts/find_duplicates.py --topic pricing_grid_reconstruction \
        --out DUPLICATES_INVENTORY.csv

For every top-level function/class name that is defined in more than one file it
emits one CSV row per definition site:

    symbol, kind, file_path, line_number, snippet, definition_lines,
    file_lines, inbound_refs, collected_by_pytest, verdict

`verdict` marks exactly one row per symbol as `canonical`; the rest are `duplicate`.
Canonical is chosen by, in order: the file is collected by the merge gate
(runner/tests/ or tests/, or a non-test module), most inbound references, largest
definition. That ordering matters here — the largest copies of these particular
duplicates live in files pytest never collects, so "largest wins" alone would
nominate dead code as canonical.
"""
from __future__ import annotations

import argparse
import ast
import csv
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# The merge gate runs: pytest runner/tests tests
COLLECTED_DIRS = ("runner/tests", "tests")


def is_collected(rel_path: str) -> bool:
    """True if pytest actually collects this file under the merge-gate command."""
    name = Path(rel_path).name
    if not name.startswith("test_"):
        return True  # a normal module: imported by callers, not collected
    return any(rel_path.startswith(d + "/") for d in COLLECTED_DIRS)


def candidate_files(root: Path, topic: str) -> list[Path]:
    """Python files whose path or contents mention the topic."""
    pattern = re.compile(re.escape(topic).replace("_", "[_-]?"), re.IGNORECASE)
    hits = []
    for path in root.rglob("*.py"):
        rel = path.relative_to(root).as_posix()
        if rel.startswith((".git/", "node_modules/", "venv/", ".venv/")):
            continue
        if pattern.search(rel):
            hits.append(path)
            continue
        try:
            if pattern.search(path.read_text(encoding="utf-8", errors="ignore")):
                hits.append(path)
        except OSError:
            continue
    return sorted(hits)


def top_level_defs(path: Path, root: Path):
    """Yield (name, kind, lineno, end_lineno, snippet) for top-level defs."""
    try:
        source = path.read_text(encoding="utf-8", errors="ignore")
        tree = ast.parse(source)
    except (OSError, SyntaxError):
        return
    lines = source.splitlines()
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            kind = "class"
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            kind = "function"
        else:
            continue
        start = node.lineno
        end = getattr(node, "end_lineno", start) or start
        snippet = " | ".join(x.strip() for x in lines[start - 1 : start + 2] if x.strip())
        yield node.name, kind, start, end, snippet[:300]


def count_refs(root: Path, name: str, defining: set[str]) -> int:
    """How many files outside the defining set mention this symbol."""
    word = re.compile(rf"\b{re.escape(name)}\b")
    total = 0
    for path in root.rglob("*.py"):
        rel = path.relative_to(root).as_posix()
        if rel in defining or rel.startswith((".git/", "node_modules/")):
            continue
        try:
            if word.search(path.read_text(encoding="utf-8", errors="ignore")):
                total += 1
        except OSError:
            continue
    return total


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--topic", default="pricing_grid_reconstruction")
    ap.add_argument("--out", default="DUPLICATES_INVENTORY.csv")
    ap.add_argument("--root", default=str(REPO_ROOT))
    args = ap.parse_args()

    root = Path(args.root).resolve()
    files = candidate_files(root, args.topic)
    if not files:
        print(f"no files matched topic {args.topic!r}", file=sys.stderr)
        return 1

    by_symbol: dict[tuple[str, str], list[dict]] = {}
    for path in files:
        rel = path.relative_to(root).as_posix()
        for name, kind, start, end, snippet in top_level_defs(path, root):
            by_symbol.setdefault((name, kind), []).append(
                {
                    "symbol": name,
                    "kind": kind,
                    "file_path": rel,
                    "line_number": start,
                    "snippet": snippet,
                    "definition_lines": end - start + 1,
                    "file_lines": sum(1 for _ in path.open(encoding="utf-8", errors="ignore")),
                    "collected_by_pytest": "yes" if is_collected(rel) else "NO",
                }
            )

    duplicates = {k: v for k, v in by_symbol.items() if len(v) > 1}
    rows = []
    for (name, _kind), sites in sorted(duplicates.items()):
        defining = {s["file_path"] for s in sites}
        refs = count_refs(root, name, defining)
        for site in sites:
            site["inbound_refs"] = refs
        winner = max(
            sites,
            key=lambda s: (
                s["collected_by_pytest"] == "yes",
                s["inbound_refs"],
                s["definition_lines"],
            ),
        )
        for site in sites:
            site["verdict"] = "canonical" if site is winner else "duplicate"
            rows.append(site)

    fields = [
        "symbol", "kind", "file_path", "line_number", "snippet",
        "definition_lines", "file_lines", "inbound_refs",
        "collected_by_pytest", "verdict",
    ]
    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = root / out_path
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    print(f"scanned {len(files)} files matching {args.topic!r}")
    print(f"{len(duplicates)} duplicated symbols across {len(rows)} definition sites")
    print(f"wrote {out_path.relative_to(root)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
