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

import subprocess

from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional, Sequence, Set, Tuple


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


# ─── Per-task commit-containment evidence PRODUCER (swarm backlog rank 1) ──────
#
# The missing primitive underneath every merge claim: does the commit a task
# cites as its artifact ACTUALLY contain that task's declared change? Today a
# borrowed/shared SHA passes evidence_gate, so ~58% of daily merges are proven
# by a commit that never touched the task's files. This produces the per-(task,
# sha) containment fact that a rewritten evidence_gate consumes. Pure git via
# subprocess so it is unit-tested against a throwaway tmp repo, no network.


@dataclass
class ContainmentEvidence:
    task_id: str
    artifact_commit: str
    evaluable: bool          # False => fail-closed: cannot prove, write NOTHING
    contains_task_paths: bool
    changed_paths: List[str]
    task_paths: List[str]
    reason: str


def _git(repo_dir: str, *args: str) -> Tuple[int, str]:
    proc = subprocess.run(
        ["git", "-C", repo_dir, *args],
        capture_output=True, text=True,
    )
    return proc.returncode, proc.stdout.strip()


def _commit_changed_paths(repo_dir: str, sha: str) -> List[str]:
    rc, out = _git(repo_dir, "show", "--name-only", "--pretty=format:", sha)
    if rc != 0:
        return []
    return [ln.strip() for ln in out.splitlines() if ln.strip()]


def _task_path_set(
    repo_dir: str,
    artifact_branch: Optional[str],
    base: Optional[str],
    declared_paths: Optional[Sequence[str]],
) -> List[str]:
    # Prefer the branch diff (the task's real footprint); fall back to the paths
    # the task declared. Order-stable, de-duplicated.
    paths: List[str] = []
    if base and artifact_branch:
        rc, out = _git(repo_dir, "diff", "%s...%s" % (base, artifact_branch), "--name-only")
        if rc == 0 and out:
            paths = [ln.strip() for ln in out.splitlines() if ln.strip()]
    if not paths and declared_paths:
        paths = [p.strip() for p in declared_paths if p and p.strip()]
    seen: Set[str] = set()
    ordered: List[str] = []
    for p in paths:
        if p not in seen:
            seen.add(p)
            ordered.append(p)
    return ordered


def verify_commit_contains_task(
    repo_dir: str,
    task_id: str,
    sha: str,
    artifact_branch: str,
    *,
    base: Optional[str] = None,
    declared_paths: Optional[Sequence[str]] = None,
) -> ContainmentEvidence:
    """Fact: does `sha` (an ancestor of `artifact_branch`) touch any path the
    task claims to change? Fail-closed (evaluable=False) when the task declares
    no paths and no branch diff exists -- then callers write NO evidence row."""
    task_paths = _task_path_set(repo_dir, artifact_branch, base, declared_paths)
    if not task_paths:
        return ContainmentEvidence(
            task_id, sha, False, False, [], [],
            "fail-closed: task declares no paths and no branch diff to derive them",
        )
    rc_sha, _ = _git(repo_dir, "rev-parse", "--verify", "%s^{commit}" % sha)
    if rc_sha != 0:
        return ContainmentEvidence(
            task_id, sha, True, False, [], task_paths,
            "sha does not resolve to a commit",
        )
    rc_anc, _ = _git(repo_dir, "merge-base", "--is-ancestor", sha, artifact_branch)
    if rc_anc != 0:
        return ContainmentEvidence(
            task_id, sha, True, False, [], task_paths,
            "sha is not an ancestor of %s (borrowed/foreign commit)" % artifact_branch,
        )
    changed = _commit_changed_paths(repo_dir, sha)
    task_set = set(task_paths)
    intersect = [p for p in changed if p in task_set]
    contains = len(intersect) > 0
    reason = (
        "commit touches task path(s): " + ", ".join(intersect)
        if contains else
        "commit touches none of the task's declared paths"
    )
    return ContainmentEvidence(task_id, sha, True, contains, changed, task_paths, reason)


def verify_and_record(
    evidence: ContainmentEvidence,
    write_row: Callable[[ContainmentEvidence], Any],
    *,
    verified_by: str = "differential_gate.verify_commit_contains_task",
) -> Optional[Any]:
    """Persist exactly one evidence row when the fact is evaluable; write NOTHING
    on the fail-closed path. `write_row` is injected (an upsert keyed on
    unique(task_id, artifact_commit)) so this is unit-tested without a database."""
    if not evidence.evaluable:
        return None
    return write_row(evidence)
