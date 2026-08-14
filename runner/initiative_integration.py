#!/usr/bin/env python3
"""Wave C, Part 7 — initiative-level integration and disposition memory.

Two ideas from the spec, both aimed at the same waste:

* **The merge unit is the INITIATIVE, not the branch.**  Ten branches that
  together implement one coherent change currently produce ten independent
  merge decisions, each judged without the others in view.  :func:`group_into_initiatives`
  collapses them into one card, so a reviewer judges a changeset that makes
  sense on its own -- "thousands of merge decisions collapse to dozens".
* **Disposition memory.**  Today a duplicate branch is detected at merge time,
  after the work exists.  Recording *why* branches closed lets the planner
  refuse to GENERATE the duplicate in the first place, which is the only place
  the saving is real.

Both are deliberately advisory: this module groups, scores and recommends.  It
does not merge, close or enqueue anything -- the merge train and the planner
own those, and a second actor writing to them is how two systems start
disagreeing about what shipped.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

#: Closure reasons that carry a lesson worth remembering.
DISPOSITION_KINDS = (
    "merged",           # shipped: its subject is now covered
    "superseded",       # a newer branch did it better
    "duplicate",        # someone else was already doing it
    "rejected",         # judged not worth doing
    "abandoned",        # started, never finished
)

#: A slug like "backlog-batch-beethoven-2863be9-merge-changes-slice-1" carries
#: an initiative ("backlog-batch-beethoven-2863be9-merge-changes") plus a shard
#: marker. These are the shard suffixes the fleet actually emits.
_SHARD_SUFFIX = re.compile(
    r"(?:[-_](?:slice|shard|part|chunk|step)[-_]?\d+)+$", re.IGNORECASE)
_TRAILING_HASH = re.compile(r"[-_][0-9a-f]{6,40}$", re.IGNORECASE)


def initiative_key(slug: str) -> str:
    """Strip shard/slice markers to recover the initiative a branch belongs to.

    ``x-slice-1`` and ``x-slice-3-adapt-...`` must land on the same initiative
    as ``x``; a trailing content hash must not split an initiative either.
    """
    if not slug:
        return ""
    key = str(slug).strip().lower().removeprefix("agent/")
    previous = None
    while previous != key:
        previous = key
        key = _SHARD_SUFFIX.sub("", key)
    return key or str(slug).strip().lower()


@dataclass
class Branch:
    slug: str
    files: Tuple[str, ...] = ()
    additions: int = 0
    deletions: int = 0
    tests_green: Optional[bool] = None
    project: str = "orchestrator"

    @property
    def initiative(self) -> str:
        return initiative_key(self.slug)


@dataclass
class Initiative:
    """One coherent changeset: the unit a human should actually judge."""

    key: str
    branches: List[Branch] = field(default_factory=list)

    @property
    def files(self) -> List[str]:
        seen: Dict[str, None] = {}
        for branch in self.branches:
            for path in branch.files:
                seen.setdefault(path, None)
        return sorted(seen)

    @property
    def additions(self) -> int:
        return sum(b.additions for b in self.branches)

    @property
    def deletions(self) -> int:
        return sum(b.deletions for b in self.branches)

    def overlapping_files(self) -> List[str]:
        """Files touched by more than one branch: where a conflict will be."""
        counts: Counter = Counter()
        for branch in self.branches:
            counts.update(set(branch.files))
        return sorted(path for path, n in counts.items() if n > 1)

    def readiness(self) -> Dict[str, Any]:
        """An initiative is judged as a whole; one red shard holds the card.

        Unknown (``None``) test state is treated as NOT green -- an initiative
        whose shards were never verified must not present as ready.
        """
        red = sorted(b.slug for b in self.branches if b.tests_green is False)
        unknown = sorted(b.slug for b in self.branches if b.tests_green is None)
        return {
            "initiative": self.key,
            "branches": len(self.branches),
            "ready": not red and not unknown and bool(self.branches),
            "failing": red,
            "unverified": unknown,
            "overlapping_files": self.overlapping_files(),
        }


def group_into_initiatives(branches: Iterable[Branch]) -> List[Initiative]:
    """Collapse branches into initiatives, deterministically ordered."""
    grouped: Dict[str, Initiative] = {}
    for branch in branches:
        initiative = grouped.setdefault(branch.initiative, Initiative(branch.initiative))
        initiative.branches.append(branch)
    for initiative in grouped.values():
        initiative.branches.sort(key=lambda b: b.slug)
    return [grouped[k] for k in sorted(grouped)]


def collapse_ratio(branches: Sequence[Branch]) -> Dict[str, Any]:
    """How many merge decisions the grouping actually removes."""
    initiatives = group_into_initiatives(branches)
    before, after = len(branches), len(initiatives)
    return {
        "decisions_before": before,
        "decisions_after": after,
        "removed": before - after,
        "ratio": (before / after) if after else 0.0,
    }


# -- disposition memory --------------------------------------------------
def subject_fingerprint(files: Sequence[str], title: str = "") -> str:
    """Identity of what a piece of work TOUCHES, independent of its slug.

    Two branches with different names doing the same thing must collide here;
    that collision is the whole mechanism.
    """
    payload = {"files": sorted(set(files)),
               "title": " ".join(sorted(str(title).lower().split()))}
    return hashlib.blake2b(json.dumps(payload, sort_keys=True).encode(),
                           digest_size=12).hexdigest()


@dataclass(frozen=True)
class Disposition:
    slug: str
    kind: str
    fingerprint: str
    reason: str = ""
    at: float = field(default_factory=time.time)


class DispositionMemory:
    """Why branches closed, so the planner can stop generating the duplicates."""

    def __init__(self) -> None:
        self._by_fingerprint: Dict[str, List[Disposition]] = defaultdict(list)
        self._by_slug: Dict[str, Disposition] = {}

    def record(self, slug: str, kind: str, files: Sequence[str],
               title: str = "", reason: str = "",
               at: Optional[float] = None) -> Disposition:
        if kind not in DISPOSITION_KINDS:
            raise ValueError(f"unknown disposition kind {kind!r}")
        disposition = Disposition(
            slug=slug, kind=kind, fingerprint=subject_fingerprint(files, title),
            reason=reason, at=at if at is not None else time.time())
        self._by_fingerprint[disposition.fingerprint].append(disposition)
        self._by_slug[slug] = disposition
        return disposition

    def history(self, files: Sequence[str], title: str = "") -> List[Disposition]:
        return list(self._by_fingerprint.get(subject_fingerprint(files, title), ()))

    def should_generate(self, files: Sequence[str], title: str = "") -> Dict[str, Any]:
        """Advice for the planner BEFORE work is generated.

        Refuses only on evidence that the subject is already handled or was
        judged not worth doing.  An abandoned attempt is explicitly NOT a
        reason to refuse -- that would let one failed run permanently veto a
        real piece of work.
        """
        prior = self.history(files, title)
        if not prior:
            return {"generate": True, "reason": "no prior disposition", "prior": 0}
        kinds = {d.kind for d in prior}
        for blocking in ("merged", "superseded", "duplicate", "rejected"):
            if blocking in kinds:
                match = next(d for d in prior if d.kind == blocking)
                return {"generate": False, "reason": blocking, "prior": len(prior),
                        "precedent": match.slug, "detail": match.reason}
        return {"generate": True, "reason": "only abandoned attempts on record",
                "prior": len(prior)}

    def stats(self) -> Dict[str, Any]:
        counts: Counter = Counter(d.kind for d in self._by_slug.values())
        return {"recorded": len(self._by_slug),
                "subjects": len(self._by_fingerprint),
                "by_kind": dict(counts)}


def dedupe_candidates(open_branches: Sequence[Branch],
                      memory: DispositionMemory) -> List[Dict[str, Any]]:
    """Open branches whose subject the memory says is already handled."""
    flagged = []
    for branch in open_branches:
        advice = memory.should_generate(branch.files, branch.slug)
        if not advice["generate"]:
            flagged.append({"slug": branch.slug, "reason": advice["reason"],
                            "precedent": advice.get("precedent")})
    return flagged
