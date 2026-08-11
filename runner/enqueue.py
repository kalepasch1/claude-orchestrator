"""PROPRIETARY -- Apparently Inc. Trade Secret. Protected under DTSA (18 U.S.C. 1836).

Idempotent enqueue chokepoint (swarm backlog ranks 5 + 7, core).

Every task insert SHOULD route through enqueue_task so retries, absorption
re-routes and decomposition slices coalesce onto ONE open row instead of minting
the -slice-N / duplicate-intent fan-out that is ~42% of the table. The dedup key
is deterministic (rank 7): normalize the slug (strip slice/item/file/group/part
-N and trailing version/numeric suffixes) and scope by project + declared
target_path, so parallel subtasks with DISTINCT targets are not over-collapsed.

Pure dedup logic; store ops (find/insert/bump) are injected, so it is unit-tested
without a database. Non-terminal-only matching is the caller's contract for
find_open_by_intent: a finished intent may legitimately recur.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional

# Repeatable decomposition/fan-out suffixes, and trailing version/numeric tails.
_FANOUT_SUFFIX = re.compile(r'([-_](?:slice|item|file|group|part|chunk)[-_]?\d+)+$', re.IGNORECASE)
_TRAILING_VER = re.compile(r'[-_]v?\d+$', re.IGNORECASE)

# Terminal states — a task here is finished; its intent may legitimately recur.
TERMINAL_STATES = frozenset({
    'MERGED', 'CLOSED', 'SUPERSEDED', 'DEPLOYED_AND_VERIFIED', 'DONE', 'QUARANTINED',
})


def normalize_slug(slug: str) -> str:
    """Collapse a slug to its base intent by repeatedly stripping fan-out and
    version suffixes (handles stacked suffixes like '-slice-3-slice-4')."""
    s = (slug or '').strip().lower()
    prev = None
    while s != prev:
        prev = s
        s = _FANOUT_SUFFIX.sub('', s)
        s = _TRAILING_VER.sub('', s)
    return s


def intent_key(project_id: Optional[str], slug: str, target_path: Optional[str] = None) -> str:
    """Deterministic dedup key. target_path is part of the key so distinct
    targets under the same base intent are NOT merged (avoids over-collapse)."""
    base = normalize_slug(slug)
    tp = (target_path or '').strip()
    return '%s::%s::%s' % (project_id or '', base, tp)


@dataclass
class EnqueueResult:
    action: str  # 'created' | 'coalesced'
    intent_key: str
    task_id: Optional[str]


def _target_path_of(record: Mapping[str, Any]) -> Optional[str]:
    tp = record.get('target_path')
    if tp:
        return tp
    assumptions = record.get('assumptions')
    if isinstance(assumptions, Mapping):
        return assumptions.get('target_path')
    return None


def enqueue_task(
    record: Mapping[str, Any],
    *,
    find_open_by_intent: Callable[[str], Optional[Mapping[str, Any]]],
    insert: Callable[[Mapping[str, Any], str], Any],
    bump: Callable[[Mapping[str, Any]], None],
) -> EnqueueResult:
    """Insert `record` unless an OPEN (non-terminal) task with the same intent_key
    already exists, in which case bump that row instead of minting a duplicate.

    find_open_by_intent(key) MUST return only non-terminal rows (or None).
    insert(record, key) returns the new id. bump(existing) increments
    attempt/updated_at on the existing row. Both are injected for testability."""
    key = intent_key(record.get('project_id'), record.get('slug', ''), _target_path_of(record))
    existing = find_open_by_intent(key)
    if existing is not None:
        bump(existing)
        return EnqueueResult('coalesced', key, str(existing.get('id') or existing.get('slug') or ''))
    new_id = insert(record, key)
    return EnqueueResult('created', key, None if new_id is None else str(new_id))
