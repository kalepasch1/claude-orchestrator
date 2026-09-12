"""Enumerate evidence items out of a free-form recovery snapshot.

Recovery/reconcile snapshots pasted by an operator (or emitted by a crashed
session) are semi-structured at best: a few FAILURE/SLOG lines, some paths,
stash names, worktree directories, ref names and digest ids, and frequently a
truncated tail where the "live source" enumeration was supposed to be.

This module extracts every token that *looks like* evidence and emits a
machine-readable JSON report. Critically, it never invents evidence: when the
input is truncated or a section is announced but absent, the corresponding
item is emitted with ``status="MISSING_IN_INPUT"`` so a downstream consumer
can see the gap instead of silently assuming the snapshot was complete.

Fail-soft by convention: every public function returns a sensible default
(empty list / empty report) rather than raising on bad input.

CLI::

    python -m tools.enumerate_evidence_items --input snapshot.txt
    cat snapshot.txt | python -m tools.enumerate_evidence_items
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from typing import Any, Dict, Iterable, List, Optional

__all__ = [
    "EVIDENCE_PATTERNS",
    "TRUNCATION_MARKERS",
    "extract_evidence_items",
    "build_report",
    "main",
]

# Maximum characters of surrounding line kept as ``sample`` on each item.
SAMPLE_MAX_CHARS = 240

# Ordered so that the most specific pattern wins for a given span of text.
# Each entry is (inferred_type, compiled regex with a single capturing group).
EVIDENCE_PATTERNS = (
    ("failure", re.compile(r"^\s*(?:FAILURE|SLOG|ERROR)\b.*$", re.MULTILINE)),
    ("stash", re.compile(r"\bstash@\{\d+\}")),
    ("remote_ref", re.compile(r"\b(?:refs/remotes/[\w./-]+|origin/[\w./-]+)")),
    ("ref", re.compile(r"\brefs/[\w./-]+")),
    ("branch_ref", re.compile(r"\b(?:agent|chatgpt|hotfix|recover)/[\w./-]+")),
    ("worktree", re.compile(r"\b[\w./-]*-wt/[\w./-]+")),
    ("path", re.compile(r"(?:/[\w.@-]+){2,}/?")),
    ("digest", re.compile(r"\b[0-9a-f]{7,40}\b")),
)

# If any of these appear (or the text simply stops mid-sentence) we record that
# the enumeration of live sources was never delivered.
TRUNCATION_MARKERS = (
    "enumerate the live source",
    "enumerate the live sources",
    "...",
    "<truncated>",
    "[truncated]",
)


def _item_id(kind: str, value: str) -> str:
    """Stable short id for an evidence item. Never raises."""
    try:
        digest = hashlib.sha1(f"{kind}:{value}".encode("utf-8", "replace")).hexdigest()
        return f"{kind}-{digest[:12]}"
    except Exception:
        return f"{kind}-unknown"


def _line_containing(text: str, index: int) -> str:
    """Return the (trimmed) source line containing ``index``. Fail-soft."""
    try:
        start = text.rfind("\n", 0, index) + 1
        end = text.find("\n", index)
        if end == -1:
            end = len(text)
        return text[start:end].strip()[:SAMPLE_MAX_CHARS]
    except Exception:
        return ""


def _looks_truncated(text: str) -> bool:
    """True when the snapshot appears to stop before the live-source list."""
    if not text:
        return True
    lowered = text.lower()
    for marker in TRUNCATION_MARKERS:
        if marker in lowered:
            return True
    # A snapshot that ends without terminal punctuation or a newline is a
    # strong signal that the capture was cut short.
    tail = text.rstrip()
    return bool(tail) and tail[-1] not in ".!?)]}\"'"


def extract_evidence_items(text: Optional[str]) -> List[Dict[str, Any]]:
    """Extract evidence items from ``text``.

    Returns a list of dicts with keys ``id``, ``source_path``, ``digest``,
    ``sample``, ``inferred_type`` and ``status``. Returns ``[]`` for None or
    non-string input rather than raising.
    """
    if not isinstance(text, str) or not text.strip():
        return []

    items: List[Dict[str, Any]] = []
    seen: set = set()
    # Spans already consumed by a more specific pattern.
    claimed: List[tuple] = []

    def _overlaps(span: tuple) -> bool:
        return any(span[0] < end and start < span[1] for start, end in claimed)

    for inferred_type, pattern in EVIDENCE_PATTERNS:
        try:
            matches = list(pattern.finditer(text))
        except Exception:
            continue
        for match in matches:
            span = match.span()
            if _overlaps(span):
                continue
            value = match.group(0).strip()
            if not value:
                continue
            key = (inferred_type, value)
            if key in seen:
                claimed.append(span)
                continue
            seen.add(key)
            claimed.append(span)
            item: Dict[str, Any] = {
                "id": _item_id(inferred_type, value),
                "source_path": value,
                "inferred_type": inferred_type,
                "sample": _line_containing(text, span[0]),
                "status": "EXTRACTED",
            }
            if inferred_type == "digest":
                item["digest"] = value
            items.append(item)

    return items


def _missing_placeholder(reason: str) -> Dict[str, Any]:
    return {
        "id": _item_id("live-source-enumeration", reason),
        "source_path": "UNKNOWN",
        "digest": "UNKNOWN",
        "sample": "UNKNOWN",
        "inferred_type": "live_source_enumeration",
        "status": "MISSING_IN_INPUT",
        "reason": reason,
    }


def build_report(text: Optional[str]) -> List[Dict[str, Any]]:
    """Full evidence report: extracted items plus explicit MISSING markers.

    The report is a JSON-serializable list. When the snapshot is truncated or
    the live-source enumeration is absent, a ``MISSING_IN_INPUT`` placeholder
    is appended so no consumer can mistake silence for completeness.
    """
    items = extract_evidence_items(text)
    if _looks_truncated(text or ""):
        items.append(
            _missing_placeholder(
                "snapshot ends before the live source enumeration was provided"
            )
        )
    elif not items:
        items.append(_missing_placeholder("no evidence tokens found in input"))
    return items


def _read_input(path: Optional[str]) -> str:
    """Read the snapshot from a path or stdin. Returns '' on any failure."""
    try:
        if path:
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                return handle.read()
        if not sys.stdin.isatty():
            return sys.stdin.read()
    except FileNotFoundError:
        return ""
    except Exception:
        return ""
    return ""


def main(argv: Optional[Iterable[str]] = None) -> int:
    """CLI entry point. Always exits 0 — the report carries the status."""
    parser = argparse.ArgumentParser(
        description="Enumerate evidence items from a recovery snapshot."
    )
    parser.add_argument("--input", "-i", default=None, help="Snapshot file (default: stdin)")
    parser.add_argument("--indent", type=int, default=2, help="JSON indent")
    try:
        args = parser.parse_args(list(argv) if argv is not None else None)
    except SystemExit:
        return 0

    report = build_report(_read_input(args.input))
    try:
        print(json.dumps(report, indent=args.indent, sort_keys=False))
    except Exception:
        print("[]")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
