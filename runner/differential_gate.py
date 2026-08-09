"""PROPRIETARY -- Apparently Inc. Trade Secret. Protected under DTSA (18 U.S.C. 1836).

Differential re-derivation + assumptions-ledger gate (shadow round-2 winner).

The one gap no other objective gate closes is *intent-correctness*: a change +
a confidently-wrong-but-self-consistent test passes every sensitivity gate. This
gate attacks it by independence: N decorrelated re-derivations implement the SAME
spec and emit outputs over a shared probe-input set plus an assumptions ledger.
The primary implementation is ACCEPTED only if it agrees with the panel consensus
on every probe input AND its ledger matches the panel's; any divergence ROUTES TO
HUMAN with the concrete counterexample -- converting silent bad-merges into loud,
adjudicable events. Under-determined specs (all readers diverge) surface here too.
Pure; panel outputs/ledgers are injected so it is unit-tested without models.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any, List, Sequence, Set


@dataclass
class Disagreement:
    probe_index: int
    primary: Any
    consensus: Any


@dataclass
class DiffVerdict:
    verdict: str  # "accept" | "route_to_human"
    reason: str
    agreement: float
    disagreements: List[Disagreement] = field(default_factory=list)
    ledger_divergence: List[str] = field(default_factory=list)


def _consensus(values: Sequence[Any]) -> Any:
    # Most common value; ties resolve to the first-seen most-common (deterministic).
    counts = Counter(repr(v) for v in values)
    best_repr, _ = counts.most_common(1)[0]
    for v in values:
        if repr(v) == best_repr:
            return v
    return values[0]


def differential_adjudicate(
    primary_outputs: Sequence[Any],
    panel_outputs_by_impl: Sequence[Sequence[Any]],
    primary_ledger: Set[str],
    panel_ledgers: Sequence[Set[str]],
    *,
    agreement_threshold: float = 1.0,
) -> DiffVerdict:
    n = len(primary_outputs)
    if n == 0 or not panel_outputs_by_impl:
        return DiffVerdict("route_to_human", "no probe outputs to adjudicate", 0.0)

    disagreements: List[Disagreement] = []
    for i in range(n):
        panel_vals = [impl[i] for impl in panel_outputs_by_impl if i < len(impl)]
        if not panel_vals:
            continue
        cons = _consensus(panel_vals)
        if repr(primary_outputs[i]) != repr(cons):
            disagreements.append(Disagreement(i, primary_outputs[i], cons))

    agreement = (n - len(disagreements)) / n

    # Ledger divergence: assumptions the panel-majority holds vs the primary's.
    panel_union: Counter = Counter()
    for led in panel_ledgers:
        for a in set(led):
            panel_union[a] += 1
    majority = {a for a, c in panel_union.items() if c > len(panel_ledgers) / 2}
    divergence = sorted(majority.symmetric_difference(set(primary_ledger)))

    if disagreements or divergence or agreement < agreement_threshold:
        reasons = []
        if disagreements:
            reasons.append(f"{len(disagreements)} probe disagreement(s) vs independent panel")
        if divergence:
            reasons.append(f"assumptions-ledger divergence: {', '.join(divergence)}")
        if agreement < agreement_threshold and not disagreements:
            reasons.append(f"agreement {agreement:.2f} < threshold {agreement_threshold:.2f}")
        return DiffVerdict("route_to_human", "; ".join(reasons), agreement, disagreements, divergence)

    return DiffVerdict("accept", "primary matches independent panel consensus and ledger", agreement)
