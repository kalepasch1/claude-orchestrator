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
Canonical is chosen by, in order: the file is collected by pytest, most inbound
references, largest definition. That ordering matters — "largest wins" alone would
nominate dead code as canonical.

Which files count as collected is READ FROM `pytest.ini`'s `testpaths`, not assumed.
It was assumed once, the assumption went stale, and the resulting inventory called
~4,600 lines of live test code dead. See collected_dirs().
"""
from __future__ import annotations

import argparse
import ast
import csv
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Fallback when pytest.ini declares no testpaths. Historically this was the whole
#: answer, hardcoded — see collected_dirs() for why that produced a false inventory.
DEFAULT_COLLECTED_DIRS = ("runner/tests", "tests")


def collected_dirs(root: Path = REPO_ROOT) -> tuple:
    """Where pytest actually collects from, read from pytest.ini's `testpaths`.

    THIS USED TO BE A HARDCODED ("runner/tests", "tests") AND IT WENT STALE.

    pytest.ini now declares `testpaths = runner`, which collects the 152 test files
    at `runner/test_*.py` as well as `runner/tests/`. The constant did not, so this
    tool reported every one of those files as `collected_by_pytest = NO` — and the
    inventory it generated concluded that "29 of the 34 definition sites sit in files
    pytest never collects … ~4,600 lines of uncollected test code", with a suggested
    follow-up of deleting seven of them.

    Those files run. Acting on that report would have deleted ~4,600 lines of LIVE
    test coverage on the strength of a constant that disagreed with the config file
    six directories away. A duplication tool whose collection model is wrong does not
    produce a slightly-off inventory; it inverts the canonical-selection rule, which
    ranks "is it collected" FIRST.

    Reading the config is the fix. Fail-soft: an unreadable or testpaths-less
    pytest.ini falls back to the old pair, which is still better than nothing.
    """
    try:
        import configparser
        parser = configparser.ConfigParser()
        parser.read(root / "pytest.ini")
        raw = parser.get("pytest", "testpaths", fallback="").strip()
        paths = tuple(p.strip().rstrip("/") for p in raw.split() if p.strip())
        if not paths:
            return DEFAULT_COLLECTED_DIRS
        # Union, not replacement: `testpaths` governs a bare `pytest`, but CI also
        # names targets explicitly (`pytest runner/tests tests`). A file collected by
        # either route is collected. Narrowing to testpaths alone would just move the
        # false negative from runner/*.py onto tests/*.py.
        return tuple(dict.fromkeys(paths + DEFAULT_COLLECTED_DIRS))
    except Exception:
        return DEFAULT_COLLECTED_DIRS


def is_collected(rel_path: str, dirs=None) -> bool:
    """True if pytest actually collects this file under the merge-gate command."""
    name = Path(rel_path).name
    if not name.startswith("test_"):
        return True  # a normal module: imported by callers, not collected
    roots = collected_dirs() if dirs is None else dirs
    return any(rel_path == d or rel_path.startswith(d + "/") for d in roots)


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
