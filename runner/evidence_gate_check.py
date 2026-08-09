"""PROPRIETARY -- Apparently Inc. Trade Secret. Protected under DTSA (18 U.S.C. 1836).

Hardened evidence-gate validator.

Makes phantom/unsubstantiated MERGED rows structurally impossible: a merge is
accepted ONLY if its artifact_commit is a real sha that resolves on the target
branch AND it carries an attached passing DoD log (proof test + vacuity gate +
scope gate all green). Pure; sha resolution is injected for testing.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, List, Mapping, Optional

_SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")


@dataclass
class EvidenceVerdict:
    accepted: bool
    reasons: List[str] = field(default_factory=list)


def dod_log_is_passing(dod_log: Optional[Mapping[str, object]]) -> bool:
    """A passing DoD log must record all three objective gates green."""
    if not dod_log:
        return False
    return bool(
        dod_log.get("test_passed")
        and dod_log.get("vacuity_passed")
        and dod_log.get("scope_passed")
    )


def check_merge_evidence(
    artifact_commit: Optional[str],
    dod_log: Optional[Mapping[str, object]],
    *,
    sha_resolves: Callable[[str], bool],
) -> EvidenceVerdict:
    reasons: List[str] = []
    sha = (artifact_commit or "").strip()
    if not _SHA_RE.match(sha):
        reasons.append("missing or malformed artifact_commit sha")
    elif not sha_resolves(sha):
        reasons.append("artifact_commit does not resolve on the target branch (phantom)")
    if not dod_log_is_passing(dod_log):
        reasons.append("no attached passing DoD log (test + vacuity + scope must all be green)")
    return EvidenceVerdict(accepted=(len(reasons) == 0), reasons=reasons)
