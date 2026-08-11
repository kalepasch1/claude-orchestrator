"""PROPRIETARY -- Apparently Inc. Trade Secret. Protected under DTSA (18 U.S.C. 1836).

Assumptions Ledger intake gate (swarm backlog rank 8, core).

Every task must arrive with a machine-resolvable referent set before it may
enter QUEUED: target_path (repo-relative path it claims to change), base_sha
(commit the spec is derived against), acceptance_ref (id of a registered check).
This blocks the ~73% of no-referent canary/boilerplate inflow at the door.

Dispositions:
  accept        -> QUEUED         (all three referents resolve)
  reject_spec   -> REJECTED_SPEC  (a referent is unresolvable; terminal, never requeued)
  human_triage  -> HUMAN_TRIAGE   (target_path UNKNOWN/absent; a human decides, bounded)

Pure; resolvers (sha_resolves / path_exists_at / acceptance_registered) are
injected so this is unit-tested against fixtures, no git and no registry.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List, Mapping, Optional


@dataclass
class LedgerVerdict:
    disposition: str   # 'accept' | 'reject_spec' | 'human_triage'
    target_state: str  # 'QUEUED' | 'REJECTED_SPEC' | 'HUMAN_TRIAGE'
    reasons: List[str] = field(default_factory=list)


def validate_assumptions(
    assumptions: Optional[Mapping[str, str]],
    *,
    sha_resolves: Callable[[str], bool],
    path_exists_at: Callable[[str, str], bool],
    acceptance_registered: Callable[[str], bool],
) -> LedgerVerdict:
    a = assumptions or {}
    target_path = str(a.get('target_path') or '').strip()
    base_sha = str(a.get('base_sha') or '').strip()
    acceptance_ref = str(a.get('acceptance_ref') or '').strip()

    # An unknown/absent target is NOT a rejection — it goes to a bounded human
    # triage lane, never straight to QUEUED (a machine can't self-certify it).
    if not target_path or target_path.upper() == 'UNKNOWN':
        return LedgerVerdict('human_triage', 'HUMAN_TRIAGE',
                             ['target_path unknown/absent -> human triage lane'])

    reasons: List[str] = []
    base_ok = bool(base_sha) and _safe(sha_resolves, base_sha)
    if not base_ok:
        reasons.append('base_sha does not resolve')
    elif not _safe2(path_exists_at, base_sha, target_path):
        reasons.append('target_path "%s" absent at base_sha' % target_path)
    if not acceptance_ref or not _safe(acceptance_registered, acceptance_ref):
        reasons.append('acceptance_ref not a registered check')

    if reasons:
        return LedgerVerdict('reject_spec', 'REJECTED_SPEC', reasons)
    return LedgerVerdict('accept', 'QUEUED', ['all referents resolve'])


def _safe(fn, x) -> bool:
    try:
        return bool(fn(x))
    except Exception:
        return False


def _safe2(fn, x, y) -> bool:
    try:
        return bool(fn(x, y))
    except Exception:
        return False
