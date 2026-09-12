"""Scan merged-diff memory memos written under ~/.claude/projects.

`merged_diff_memory._save_to_memory` writes one rollup memo per day into a
project's memory directory. Nothing read them back, so the rules and
frameworks harvested from merges were write-only -- captured, indexed, and
never consulted.

This module is the read side. It globs `merged_diff_*.md` under
`~/.claude/projects/{project_id}/memory/`, parses the frontmatter and the two
sections the writer emits, and returns plain dicts.

Fail-soft throughout, per the convention in this package: a malformed memo, an
unreadable file or a missing directory yields fewer results and a logged
warning, never an exception to the caller.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any, Iterable

logger = logging.getLogger(__name__)

#: Root that holds one directory per project.
PROJECTS_ROOT = Path(
    os.environ.get("CLAUDE_PROJECTS_ROOT", Path.home() / ".claude" / "projects")
)

#: Memos live in this subdirectory of a project directory.
MEMORY_SUBDIR = "memory"

#: Only these files are memos. Keep in sync with `_save_to_memory`.
MEMO_GLOB = "merged_diff_*.md"

#: Cap on files read per project so a runaway directory cannot stall a sweep.
MAX_MEMOS_PER_PROJECT = int(os.environ.get("ORCH_MEMO_SCAN_LIMIT", "500") or 500)

_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_RULES_HEADING = "## Learned Conventions & Do/Avoid Rules"
_FRAMEWORKS_HEADING = "## Frameworks in Use"
_PLACEHOLDER = "(no new rules extracted today)"
_TRAILER_PREFIX = "See also:"


def _parse_frontmatter(text: str) -> dict[str, Any]:
    """Parse the flat + one-level-nested YAML the writer emits.

    Deliberately not a YAML parser: the writer emits a fixed shape, and taking
    a dependency here would make the scanner fail closed on import when the
    rest of the package fails soft.
    """
    match = _FRONTMATTER_RE.search(text or "")
    if not match:
        return {}

    out: dict[str, Any] = {}
    nested_key: str | None = None
    for raw in match.group(1).splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indented = raw[:1].isspace()
        if ":" not in raw:
            continue
        key, _, value = raw.partition(":")
        key = key.strip()
        value = value.strip()

        if indented and nested_key:
            bucket = out.setdefault(nested_key, {})
            if isinstance(bucket, dict):
                bucket[key] = value
            continue

        if not value:
            nested_key = key
            out.setdefault(key, {})
        else:
            nested_key = None
            out[key] = value
    return out


def _section(text: str, heading: str) -> list[str]:
    """Return the non-empty lines under ``heading`` up to the next heading.

    The last section in a memo is followed by the writer's ``See also:``
    wikilink trailer with no heading in between, so that trailer terminates a
    section too -- otherwise it is read as section content.
    """
    lines = (text or "").splitlines()
    try:
        start = next(i for i, ln in enumerate(lines) if ln.strip() == heading)
    except StopIteration:
        return []

    body: list[str] = []
    for ln in lines[start + 1:]:
        stripped = ln.strip()
        if ln.startswith("## ") or stripped.startswith(_TRAILER_PREFIX):
            break
        if stripped:
            body.append(stripped)
    return body


def parse_memo(path: str | os.PathLike) -> dict[str, Any] | None:
    """Parse one memo file. Returns ``None`` if it cannot be read or parsed."""
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except (OSError, ValueError) as exc:
        logger.warning("merged-diff memo unreadable: %s (%s)", p, exc)
        return None

    try:
        front = _parse_frontmatter(text)
        meta = front.get("metadata")
        meta = meta if isinstance(meta, dict) else {}

        rules = [
            ln.lstrip("-* ").strip()
            for ln in _section(text, _RULES_HEADING)
            if ln.lstrip("-* ").strip() and _PLACEHOLDER not in ln
        ]

        frameworks: list[str] = []
        for ln in _section(text, _FRAMEWORKS_HEADING):
            for part in ln.split(","):
                part = part.strip()
                if part and part.lower() != "none":
                    frameworks.append(part)

        commits = [
            c.strip() for c in str(meta.get("commits", "")).split(",") if c.strip()
        ]

        return {
            "path": str(p),
            "name": front.get("name", p.stem),
            "description": front.get("description", ""),
            "date": meta.get("date", ""),
            "commits": commits,
            "rules": rules,
            "frameworks": frameworks,
        }
    except Exception as exc:  # fail soft: a bad memo must not stop the sweep
        logger.warning("merged-diff memo unparseable: %s (%s)", p, exc)
        return None


def memory_dir(project_id: str) -> Path:
    """Memory directory for ``project_id`` (not guaranteed to exist)."""
    return PROJECTS_ROOT / project_id / MEMORY_SUBDIR


def scan_project(project_id: str) -> list[dict[str, Any]]:
    """Scan one project's memos, newest filename first.

    Returns ``[]`` for a missing project, an unreadable directory, or a
    project with no memos.
    """
    if not project_id or not str(project_id).strip():
        return []

    directory = memory_dir(str(project_id).strip())
    try:
        if not directory.is_dir():
            return []
        paths = sorted(directory.glob(MEMO_GLOB), reverse=True)
    except OSError as exc:
        logger.warning("merged-diff memory dir unreadable: %s (%s)", directory, exc)
        return []

    if len(paths) > MAX_MEMOS_PER_PROJECT:
        logger.warning(
            "merged-diff memos truncated for %s: %d found, reading %d",
            project_id, len(paths), MAX_MEMOS_PER_PROJECT,
        )
        paths = paths[:MAX_MEMOS_PER_PROJECT]

    memos: list[dict[str, Any]] = []
    for path in paths:
        memo = parse_memo(path)
        if memo is not None:
            memo["project_id"] = str(project_id).strip()
            memos.append(memo)
    return memos


def list_project_ids() -> list[str]:
    """Every project directory under :data:`PROJECTS_ROOT`."""
    try:
        return sorted(p.name for p in PROJECTS_ROOT.iterdir() if p.is_dir())
    except OSError as exc:
        logger.warning("projects root unreadable: %s (%s)", PROJECTS_ROOT, exc)
        return []


def scan_all(project_ids: Iterable[str] | None = None) -> list[dict[str, Any]]:
    """Scan every project (or just ``project_ids``) and return all memos."""
    ids = list(project_ids) if project_ids is not None else list_project_ids()
    memos: list[dict[str, Any]] = []
    for pid in ids:
        memos.extend(scan_project(pid))
    return memos


def collect_rules(project_id: str | None = None) -> list[str]:
    """Deduplicated, sorted rules across memos.

    Scans one project when ``project_id`` is given, otherwise every project.
    """
    memos = scan_project(project_id) if project_id else scan_all()
    return sorted({rule for memo in memos for rule in memo.get("rules", [])})


def collect_frameworks(project_id: str | None = None) -> list[str]:
    """Deduplicated, sorted frameworks across memos."""
    memos = scan_project(project_id) if project_id else scan_all()
    return sorted({fw for memo in memos for fw in memo.get("frameworks", [])})


def stats(project_id: str | None = None) -> dict[str, int]:
    """Counts for operator monitoring: memos, rules, frameworks, commits."""
    memos = scan_project(project_id) if project_id else scan_all()
    return {
        "memos": len(memos),
        "rules": len({r for m in memos for r in m.get("rules", [])}),
        "frameworks": len({f for m in memos for f in m.get("frameworks", [])}),
        "commits": len({c for m in memos for c in m.get("commits", [])}),
    }


__all__ = [
    "PROJECTS_ROOT",
    "MEMO_GLOB",
    "memory_dir",
    "parse_memo",
    "scan_project",
    "scan_all",
    "list_project_ids",
    "collect_rules",
    "collect_frameworks",
    "stats",
]
