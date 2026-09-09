"""orchestration_artifacts — keep the *producer* from manufacturing its own evidence.

This is the Python port of ``scripts/lib/orchestration-artifacts.mjs``. That module
landed on 2026-08-24 (commit 6805f400) and fixed the *classifier*: an orchestration
artifact never reaches a verdict. But the evidence for those verdicts is produced
somewhere else entirely — ``tools/chatgpt-bridge/local_build_audit.py`` — and that
path was never taught the policy. So the loop kept running:

  producer sweeps its own bookkeeping -> emits it as evidence -> intake files a
  ``chatgpt-local-reconcile-*`` task -> an executor runs, writes a ledger and a
  worktree -> the next sweep picks *those* up as evidence -> repeat.

Measured on 2026-09-09, sixteen days after the classifier fix shipped: 900
``chatgpt-local-reconcile-*`` tasks still QUEUED, ~660 of them created *after* the
fix, 90 of them created that same day. The classifier was declining to grade the
noise; nothing had stopped the noise being made.

THE RULE, and its one important restriction (unchanged from the JS module):

  An item is orchestration bookkeeping only when EVERY path it carries is
  bookkeeping. One real source file and it stays in the evidence universe and is
  reported normally.

That asymmetry is deliberate. Excluding a mixed item to keep the loop tidy would
discard real unshipped work, which is the exact loss this reconciliation exists to
prevent — far worse than an extra pass.

SCOPE. This applies to SWEEPS AND RESCUE REFS ONLY, matching the scoping decision
recorded on the original task. An ``agent/*`` branch tip is deliberate work by
construction, so judging one by its file list risks excluding real evidence; that
trade is not made here. (See ``docs/`` note emitted by the caller: the stub-branch
question is left open for the operator rather than decided in code.)

Excluding is never silent: every removal is returned with a reason and a
human-readable detail so the caller can list it under its own key. An unexplained
disappearance is the same bug class the coverage doctrine forbids.

Pure. No git, no filesystem, no clock — the caller supplies paths and times.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Sequence

# Paths that exist only because the fleet ran, not because anyone built anything.
# Anchored, so a real source file cannot match merely by containing the word.
ORCHESTRATION_PATH_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^\.orch/recovery-ledger-.*\.json$"),
    re.compile(r"^\.orch/[^/]*\.(json|md|txt)$"),
    re.compile(r"^docs/tasks/chatgpt-local-reconcile-.*\.md$"),
    re.compile(r"^docs/recovery-ledger/"),
    re.compile(r"^docs/recovery-ledger-[0-9a-z]+\.(json|md)$"),
    re.compile(r"^docs/recovery/"),
    re.compile(r"^scripts/reconcile-[^/]*$"),
    re.compile(r"^scripts/recovery/[^/]*$"),
    re.compile(r"^tools/reconcile_[^/]*$"),
    re.compile(r"(^|/)\.recovery-intent-[^/]*$"),
)

# Directories the fleet creates to work in, which are nobody's evidence.
SCAFFOLDING_PATH_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(^|/)[^/]+-wt/"),            # agent worktrees: {repo}-wt/{slug}
    re.compile(r"^/private/tmp/.*-baseline"),  # baseline checkouts made to compare
    re.compile(r"^/tmp/.*-baseline"),
)

REASON_BOOKKEEPING = "ORCHESTRATION_ARTIFACT"
REASON_SCAFFOLDING = "RUN_SCAFFOLDING"


def _norm(path: Any) -> str:
    p = str(path or "").strip()
    return p[2:] if p.startswith("./") else p


def is_orchestration_path(path: Any) -> bool:
    """Is this one path pure orchestration bookkeeping?"""
    p = _norm(path)
    if not p:
        return False
    return any(rx.search(p) for rx in ORCHESTRATION_PATH_PATTERNS)


def is_scaffolding_path(path: Any) -> bool:
    """Is this path inside something the fleet created to work in?"""
    p = str(path or "").strip()
    if not p:
        return False
    return any(rx.search(p) for rx in SCAFFOLDING_PATH_PATTERNS)


def all_paths_are_orchestration(paths: Iterable[Any] | None) -> bool:
    """Does this set of paths consist ENTIRELY of orchestration bookkeeping?

    An empty set is NOT bookkeeping. "We could not read what it carries" and "it
    carries only ledgers" are different claims, and treating the first as the
    second would drop evidence nobody ever looked at.
    """
    items = [_norm(p) for p in (paths or [])]
    items = [p for p in items if p]
    if not items:
        return False
    return all(is_orchestration_path(p) or is_scaffolding_path(p) for p in items)


def classify_exclusion(paths: Sequence[Any] | None) -> tuple[bool, str | None, str | None]:
    """Decide whether an evidence item should be kept out of the universe.

    Returns ``(excluded, reason, detail)``. ``detail`` is human-readable, because
    a count alone in a ledger tells the reader nothing about what vanished.
    """
    items = [_norm(p) for p in (paths or [])]
    items = [p for p in items if p]
    if not items:
        return False, None, None
    if not all_paths_are_orchestration(items):
        return False, None, None
    reason = (
        REASON_SCAFFOLDING
        if all(is_scaffolding_path(p) for p in items)
        else REASON_BOOKKEEPING
    )
    shown = ", ".join(items[:3])
    more = f" (+{len(items) - 3} more)" if len(items) > 3 else ""
    detail = f"all {len(items)} path(s) are orchestration bookkeeping: {shown}{more}"
    return True, reason, detail


def partition_evidence(
    items: Sequence[dict[str, Any]],
    paths_of,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split items into (kept, excluded) BEFORE anything downstream sees them.

    ``paths_of(item)`` supplies the paths an item carries; the caller owns all git
    and filesystem access so this module stays pure and testable. An item whose
    paths cannot be read is kept — see ``all_paths_are_orchestration``.
    """
    kept: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for item in items:
        try:
            paths = paths_of(item)
        except Exception:
            kept.append(item)
            continue
        is_excluded, reason, detail = classify_exclusion(paths)
        if is_excluded:
            excluded.append({**item, "excluded_reason": reason, "excluded_detail": detail})
        else:
            kept.append(item)
    return kept, excluded
