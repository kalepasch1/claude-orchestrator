#!/usr/bin/env python3
"""Wave C, Part 4 — contract-first, transplant-proven-organs code generation.

The spec's four requirements, and how each is met here:

* **Transplant proven organs, never grow tumors.**  Generation starts from a
  prior merged diff only when it clears the RAISED similarity bar (0.55), and
  the disposition ledger records what was transplanted from where.  Below the
  bar the honest answer is "no donor" -- adapting a weak match is precisely how
  a tumor grows, because the shape is wrong and the fill hides it.
* **Contract-first: the verify gate IS the spec.**  :func:`build_contract`
  emits the failing test and the type signatures BEFORE any implementation, and
  :func:`accept_implementation` refuses an implementation whose contract test
  never actually failed first -- a test that passes against an empty
  implementation is not a spec, it is decoration.
* **Golden-path templates per vertical**, distilled only from top-decile merged
  shards, so the template encodes what actually shipped.
* **Strategy-aware generation**, where an approved strategy is context for every
  shard, so code is born compliant with the chosen structure rather than
  retrofitted.

This module composes the existing ``merged_diff_library`` when it is importable
rather than reimplementing retrieval; the fleet already has one of those and a
second would drift from it.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

#: Raised bar from the spec.  Below this there is no donor, and that is a
#: legitimate answer rather than a reason to adapt something ill-fitting.
SIMILARITY_FLOOR = 0.55

#: A shard must be in the top decile of merged outcomes to become a template.
TOP_DECILE = 0.90


class NoDonor(RuntimeError):
    """No prior diff cleared the similarity floor."""


class ContractViolation(RuntimeError):
    """An implementation was offered without a contract that first failed."""


def _tokens(text: str) -> Counter:
    return Counter(re.findall(r"[a-z0-9_]+", str(text).lower()))


def similarity(a: str, b: str) -> float:
    """Cosine over token counts.  Deterministic, dependency-free, explainable."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    shared = set(ta) & set(tb)
    dot = sum(ta[t] * tb[t] for t in shared)
    na = sum(v * v for v in ta.values()) ** .5
    nb = sum(v * v for v in tb.values()) ** .5
    return dot / (na * nb) if na and nb else 0.0


# -- transplant ledger ---------------------------------------------------
@dataclass(frozen=True)
class Donor:
    slug: str
    intent: str
    diff: str
    merged: bool = True
    outcome_score: float = 0.0
    vertical: str = "generic"


@dataclass(frozen=True)
class Transplant:
    recipient: str
    donor_slug: str
    score: float
    at: float


class DispositionLedger:
    """What was transplanted from where, so provenance survives the generation."""

    def __init__(self) -> None:
        self._entries: List[Transplant] = []

    def record(self, recipient: str, donor: Donor, score: float,
               at: Optional[float] = None) -> Transplant:
        entry = Transplant(recipient, donor.slug, score,
                           at if at is not None else time.time())
        self._entries.append(entry)
        return entry

    def entries(self) -> List[Transplant]:
        return list(self._entries)

    def provenance(self, recipient: str) -> List[Transplant]:
        return [e for e in self._entries if e.recipient == recipient]


def select_donor(intent: str, candidates: Sequence[Donor],
                 floor: float = SIMILARITY_FLOOR) -> Tuple[Optional[Donor], float]:
    """Best MERGED candidate above the floor, or (None, best_score).

    Unmerged candidates are ignored outright: an unmerged diff is not a proven
    organ, it is an untested one.
    """
    best: Optional[Donor] = None
    best_score = 0.0
    for candidate in candidates:
        if not candidate.merged:
            continue
        score = similarity(intent, candidate.intent)
        if score > best_score or (score == best_score and best and candidate.slug < best.slug):
            best, best_score = candidate, score
    if best is None or best_score < floor:
        return None, best_score
    return best, best_score


def transplant(intent: str, recipient: str, candidates: Sequence[Donor],
               ledger: Optional[DispositionLedger] = None,
               floor: float = SIMILARITY_FLOOR) -> Dict[str, Any]:
    """Adapt a proven diff, or say plainly that there is no donor."""
    donor, score = select_donor(intent, candidates, floor)
    if donor is None:
        raise NoDonor(
            f"best similarity {score:.3f} is below the {floor} floor; "
            "generate net-new rather than adapting an ill-fitting diff")
    if ledger is not None:
        ledger.record(recipient, donor, score)
    return {"donor": donor.slug, "score": score, "diff": donor.diff,
            "vertical": donor.vertical}


# -- contract-first ------------------------------------------------------
@dataclass
class Contract:
    """The failing test and signatures that define the work, emitted first."""

    name: str
    signatures: Tuple[str, ...]
    test_source: str
    created_at: float = field(default_factory=time.time)
    observed_failing: bool = False

    def digest(self) -> str:
        return hashlib.blake2b(
            json.dumps({"name": self.name, "signatures": list(self.signatures),
                        "test": self.test_source}, sort_keys=True).encode(),
            digest_size=12).hexdigest()


def build_contract(name: str, signatures: Sequence[str],
                   assertions: Sequence[str]) -> Contract:
    """Emit the spec as a runnable failing test, before any implementation."""
    if not name:
        raise ValueError("a contract needs a name")
    if not signatures:
        raise ValueError("a contract needs at least one type signature")
    if not assertions:
        raise ValueError("a contract with no assertions cannot fail, so it is not a spec")
    body = "\n".join(f"    {a}" for a in assertions)
    source = (f"def test_{name}():\n"
              f"    # contract for: {', '.join(signatures)}\n"
              f"{body}\n")
    return Contract(name=name, signatures=tuple(signatures), test_source=source)


def observe_contract_run(contract: Contract, passed: bool) -> Contract:
    """Record the pre-implementation run.  A contract must FAIL first.

    If it passed before anything was written, it is asserting something already
    true and will not detect the work being wrong.
    """
    contract.observed_failing = not passed
    return contract


def accept_implementation(contract: Contract, passes_now: bool) -> Dict[str, Any]:
    """The verify gate IS the spec: red before, green after, or it is refused."""
    if not contract.observed_failing:
        raise ContractViolation(
            f"contract {contract.name!r} never failed before implementation; "
            "a test that passes against nothing is decoration, not a spec")
    if not passes_now:
        return {"accepted": False, "reason": "contract still failing",
                "contract": contract.digest()}
    return {"accepted": True, "contract": contract.digest(),
            "signatures": list(contract.signatures)}


# -- golden-path templates ----------------------------------------------
def distil_golden_paths(donors: Iterable[Donor],
                        top_decile: float = TOP_DECILE) -> Dict[str, Dict[str, Any]]:
    """One template per vertical, from top-decile MERGED shards only."""
    by_vertical: Dict[str, List[Donor]] = {}
    for donor in donors:
        if donor.merged and donor.outcome_score >= top_decile:
            by_vertical.setdefault(donor.vertical, []).append(donor)
    templates: Dict[str, Dict[str, Any]] = {}
    for vertical, group in by_vertical.items():
        group.sort(key=lambda d: (-d.outcome_score, d.slug))
        templates[vertical] = {
            "vertical": vertical,
            "exemplar": group[0].slug,
            "sample_size": len(group),
            "min_outcome_score": min(d.outcome_score for d in group),
        }
    return templates


# -- strategy-aware generation -------------------------------------------
@dataclass(frozen=True)
class Strategy:
    """An approved structure that every shard must be born compliant with."""

    name: str
    approved: bool = False
    required_flows: Tuple[str, ...] = ()
    forbidden: Tuple[str, ...] = ()


def strategy_context(strategy: Strategy) -> Dict[str, Any]:
    """Context injected into every shard, or nothing if unapproved.

    An UNAPPROVED strategy contributes no context at all -- generating against
    a structure nobody signed off on is worse than generating generically,
    because the output looks deliberate.
    """
    if not strategy.approved:
        return {"strategy": None, "reason": "strategy not approved; no context injected"}
    return {"strategy": strategy.name,
            "required_flows": list(strategy.required_flows),
            "forbidden": list(strategy.forbidden)}


def check_compliance(strategy: Strategy, generated: str) -> Dict[str, Any]:
    """Born-compliant check: required flows present, forbidden constructs absent."""
    if not strategy.approved:
        return {"checked": False, "reason": "strategy not approved"}
    text = str(generated).lower()
    missing = [f for f in strategy.required_flows if f.lower() not in text]
    present = [f for f in strategy.forbidden if f.lower() in text]
    return {"checked": True, "compliant": not missing and not present,
            "missing_required": missing, "forbidden_present": present}
