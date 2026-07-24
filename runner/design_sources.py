#!/usr/bin/env python3
"""Discover and enforce the repository's authoritative Markdown design sources.

Design documents are executable inputs to the build pipeline, not passive prose:
their digest participates in result caching, their requirements are injected into
planner/coder prompts, and a task cannot complete after changing a design document
without also changing implementation.
"""
from __future__ import annotations

import dataclasses
import hashlib
import os
import re
import subprocess
from typing import Iterable


DESIGN_NAME = re.compile(
    r"(?:^|[-_])(spec|design|blueprint|architecture|requirements)(?:[-_.]|$)|^adr-",
    re.IGNORECASE,
)
EXCLUDED_PREFIXES = (
    "intake/processed/",
    "memory/",
    "reports/",
    "node_modules/",
    ".pytest_cache/",
    "docs/tasks/",
)
ADVISORY_STATUSES = {"proposed", "proposal", "draft", "superseded", "rejected", "archived"}
PENDING_MARKERS = re.compile(
    r"\bpending implementation\b|\bnot implemented\b|\bimplementation pending\b",
    re.IGNORECASE,
)
REQUIREMENT_LINE = re.compile(
    r"^\s*(?:[-*+]\s+(?:\[[ xX]\]\s*)?|\d+[.)]\s+|#{1,4}\s+).+"
    r"|\b(?:must|shall|required|invariant|acceptance criteria)\b",
    re.IGNORECASE,
)
MAX_SOURCE_EXCERPT = int(os.environ.get("ORCH_DESIGN_SOURCE_EXCERPT", "1400"))
MAX_CONTRACT_CHARS = int(os.environ.get("ORCH_DESIGN_CONTRACT_CHARS", "12000"))


@dataclasses.dataclass(frozen=True)
class DesignSource:
    path: str
    title: str
    status: str
    digest: str
    requirements: tuple[str, ...]

    @property
    def active(self) -> bool:
        return self.status not in ADVISORY_STATUSES


def _tracked_markdown(repo: str) -> list[str]:
    try:
        out = subprocess.check_output(
            ["git", "ls-files", "*.md"], cwd=repo, text=True, stderr=subprocess.DEVNULL
        )
        return [line.strip() for line in out.splitlines() if line.strip()]
    except (OSError, subprocess.SubprocessError):
        # Managed application repositories are git checkouts. Avoid recursively
        # interpreting arbitrary parent/temp directories as design corpora.
        if not os.path.isdir(os.path.join(repo, ".git")):
            return []
        paths = []
        for root, dirs, files in os.walk(repo):
            dirs[:] = [d for d in dirs if d not in {".git", "node_modules", ".nuxt", ".next"}]
            for filename in files:
                if filename.lower().endswith(".md"):
                    paths.append(os.path.relpath(os.path.join(root, filename), repo))
        return paths


def is_design_path(path: str) -> bool:
    normalized = path.replace(os.sep, "/").lstrip("./")
    if any(normalized.startswith(prefix) for prefix in EXCLUDED_PREFIXES):
        return False
    return bool(DESIGN_NAME.search(os.path.basename(normalized)))


def _parse(path: str, text: str) -> DesignSource:
    title_match = re.search(r"^\s*#\s+(.+?)\s*$", text, re.MULTILINE)
    status_match = re.search(
        r"^\s*(?:\*\*)?Status\s*:\s*(?:\*\*)?\s*(.+?)\s*$", text, re.I | re.M
    )
    status = (status_match.group(1).strip(" *_`").split()[0].lower()
              if status_match else "active")
    lines = []
    for line in text.splitlines():
        clean = line.strip()
        if clean and REQUIREMENT_LINE.search(line):
            lines.append(clean)
        if sum(len(item) + 1 for item in lines) >= MAX_SOURCE_EXCERPT:
            break
    return DesignSource(
        path=path,
        title=title_match.group(1).strip() if title_match else os.path.basename(path),
        status=status,
        digest=hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest(),
        requirements=tuple(lines),
    )


def inventory(repo: str) -> list[DesignSource]:
    """Return every tracked, non-archived Markdown design source."""
    sources = []
    for path in sorted(set(_tracked_markdown(repo))):
        if not is_design_path(path):
            continue
        try:
            with open(os.path.join(repo, path), encoding="utf-8", errors="replace") as handle:
                sources.append(_parse(path, handle.read()))
        except OSError:
            continue
    return sources


def fingerprint(repo: str) -> str:
    """Digest the complete design corpus so cache hits cannot cross design revisions."""
    material = "\n".join(f"{source.path}:{source.digest}" for source in inventory(repo))
    return hashlib.sha256(material.encode()).hexdigest()


def contract(repo: str) -> dict:
    """Build the bounded design contract injected into planning and coding prompts."""
    sources = inventory(repo)
    active = [source for source in sources if source.active]
    advisory = [source for source in sources if not source.active]
    lines = [
        "# Markdown design-source contract (auto-discovered)",
        "Treat every ACTIVE source below as authoritative. Implement its applicable "
        "requirements and verify the resulting behavior; do not complete with documentation-only changes.",
    ]
    for source in active:
        lines.append(f"\n## ACTIVE: {source.path} — {source.title}")
        lines.extend(source.requirements or ("(Read the source directly before changing its subsystem.)",))
    if advisory:
        lines.append("\n## Advisory/proposed sources (inspect when relevant; not completion gates)")
        lines.extend(f"- {source.path} [{source.status}]" for source in advisory)
    text = "\n".join(lines)
    if len(text) > MAX_CONTRACT_CHARS:
        text = text[:MAX_CONTRACT_CHARS].rstrip() + "\n[design contract truncated; read listed files directly]"
    return {
        "text": text + "\n\n" if sources else "",
        "paths": [source.path for source in active],
        "all_paths": [source.path for source in sources],
        "fingerprint": fingerprint(repo),
    }


def changed_files(repo: str, base: str) -> list[str]:
    try:
        out = subprocess.check_output(
            ["git", "diff", "--name-only", f"{base}...HEAD"],
            cwd=repo,
            text=True,
            stderr=subprocess.DEVNULL,
        )
        return [line.strip() for line in out.splitlines() if line.strip()]
    except (OSError, subprocess.SubprocessError):
        return []


def completion_check(
    repo: str,
    changed: Iterable[str],
    assembled_paths: Iterable[str] | None,
) -> dict:
    """Validate design coverage immediately before the canonical integration path."""
    active_paths = {source.path for source in inventory(repo) if source.active}
    assembled = set(assembled_paths or ())
    missing = sorted(active_paths - assembled)
    changed_set = {path.replace(os.sep, "/").lstrip("./") for path in changed}
    design_changes = sorted(path for path in changed_set if is_design_path(path))
    implementation_changes = sorted(path for path in changed_set if not path.lower().endswith(".md"))

    reasons = []
    if missing:
        reasons.append("active design sources absent from assembled prompt: " + ", ".join(missing))
    if design_changes and not implementation_changes:
        reasons.append(
            "design source changed without implementation: " + ", ".join(design_changes)
        )
    return {
        "pass": not reasons,
        "notes": "; ".join(reasons) or f"{len(active_paths)} active design source(s) covered",
        "active_paths": sorted(active_paths),
        "design_changes": design_changes,
        "implementation_changes": implementation_changes,
    }


def audit(repo: str) -> dict:
    """Report unresolved implementation markers in active design documents."""
    pending = []
    sources = inventory(repo)
    for source in sources:
        if not source.active:
            continue
        try:
            with open(
                os.path.join(repo, source.path), encoding="utf-8", errors="replace"
            ) as handle:
                text = handle.read()
        except OSError:
            continue
        if PENDING_MARKERS.search(text):
            pending.append(source.path)
    return {
        "ok": not pending,
        "sources": len(sources),
        "active": sum(1 for source in sources if source.active),
        "pending": pending,
        "fingerprint": fingerprint(repo),
    }


if __name__ == "__main__":
    import json
    import sys

    print(json.dumps(audit(os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else ".")), indent=2))
