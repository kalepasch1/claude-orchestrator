#!/usr/bin/env python3
"""Gated, reversible distillation of V15 topology clusters.

``hivemind_v15.DistilledNode`` is honest about being an exact-replay cache with
teacher fallback -- it never claims to have learned anything.  Proposal 4 asks
for real compression of eligible subgraphs, and the only safe way to ship that
is to make promotion *conditional* and *reversible*.  This module supplies the
machinery the base class deliberately left out:

* **Opt-in.**  Nothing is distilled unless a caller passes a policy saying so.
* **Eligibility.**  A cluster must be hot enough and stable enough to be worth
  compressing; the reasons for refusal are returned, not swallowed.
* **Fixtures + parity.**  A candidate student is scored against frozen fixtures
  captured from the teacher.  Below tolerance it is refused outright.
* **Shadow period.**  A student that passes fixtures still runs *beside* the
  teacher on live traffic before it is trusted, and any disagreement or tail
  latency regression aborts promotion.
* **Immutable lineage.**  Every manifest is content-addressed and names its
  parent, so a recursively compressed node can be traced back to the original
  teacher and reproduced.
* **Rollback.**  Promotion is never destructive: the teacher is retained and
  :meth:`DistillationRegistry.rollback` restores it with the manifest intact.

The refusal path is the feature.  A distillation that silently degrades quality
is worse than no distillation at all, so every tolerance breach raises or
returns a refusal rather than shipping a quietly worse node.
"""
from __future__ import annotations

import hashlib
import json
import statistics
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

try:  # pragma: no cover - import shape depends on caller
    from hivemind_v15 import DistilledNode, QueryCluster, value_key
except ImportError:  # pragma: no cover
    from .hivemind_v15 import DistilledNode, QueryCluster, value_key  # type: ignore


MANIFEST_VERSION = 1


class DistillationRefused(RuntimeError):
    """A candidate failed a safety or quality gate and was not promoted."""


def _digest(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.blake2b(raw.encode(), digest_size=16).hexdigest()


@dataclass(frozen=True)
class Policy:
    """Configured tolerances.  Every field is a refusal threshold, not a target."""

    enabled: bool = False              # opt-in: distillation is off unless asked for
    min_hits: int = 10                 # a cluster must be genuinely hot
    min_fixtures: int = 8              # too few fixtures cannot prove parity
    min_parity: float = 1.0            # exact agreement by default
    max_calibration_error: float = .05
    max_tail_latency_ratio: float = 1.5   # student p95 vs teacher p95
    shadow_calls: int = 20             # live comparisons before promotion
    max_lineage_depth: int = 3         # bound recursive compression
    max_fixture_bytes: int = 1 << 20   # resource bound on retained fixtures
    latency_floor_s: float = 1e-3      # below this, a p95 ratio is scheduler noise

    def digest(self) -> str:
        return _digest(self.__dict__)


@dataclass(frozen=True)
class Fixture:
    query: Any
    expected: Any

    def key(self) -> str:
        return value_key(self.query)


@dataclass(frozen=True)
class Manifest:
    """Immutable, content-addressed provenance for one distillation."""

    version: int
    node_id: str
    app: str
    pattern: str
    parent_id: Optional[str]
    depth: int
    fixture_digest: str
    policy_digest: str
    teacher_digest: str
    parity: float
    calibration_error: float
    tail_latency_ratio: float
    created_at: float

    @property
    def id(self) -> str:
        return self.node_id

    def as_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class ShadowReport:
    calls: int = 0
    agreements: int = 0
    disagreements: List[dict] = field(default_factory=list)
    teacher_latencies: List[float] = field(default_factory=list)
    student_latencies: List[float] = field(default_factory=list)

    @property
    def parity(self) -> float:
        return (self.agreements / self.calls) if self.calls else 0.0

    def tail_ratio(self, floor_s: float = 0.0) -> float:
        """Student p95 over teacher p95, or 1.0 when the timings are noise.

        Comparing p95 of sub-millisecond calls measures the scheduler, not the
        student: two identical functions routinely differ by 1.5-2x at that
        scale.  Below ``floor_s`` there is no signal, and reporting a ratio
        anyway would refuse good students at random -- worse than no gate.
        """
        if not self.teacher_latencies or not self.student_latencies:
            return 1.0
        t = _p95(self.teacher_latencies)
        s = _p95(self.student_latencies)
        if max(t, s) < floor_s:
            return 1.0
        return (s / t) if t > 0 else 1.0


def _p95(values: Sequence[float]) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * .95))]


def capture_fixtures(teacher: Callable[[Any], Any], queries: Sequence[Any],
                     policy: Policy) -> List[Fixture]:
    """Freeze teacher behaviour, bounded by the policy's byte budget."""
    fixtures: List[Fixture] = []
    used = 0
    for query in queries:
        expected = teacher(query)
        size = len(json.dumps([query, expected], default=str, separators=(",", ":")).encode())
        if used + size > policy.max_fixture_bytes:
            break
        used += size
        fixtures.append(Fixture(query, expected))
    return fixtures


def eligibility(cluster: QueryCluster, fixtures: Sequence[Fixture],
                policy: Policy, depth: int = 0) -> Tuple[bool, List[str]]:
    """Return (eligible, reasons).  Reasons are always returned, never swallowed."""
    reasons: List[str] = []
    if not policy.enabled:
        reasons.append("policy_disabled")
    if cluster.hits < policy.min_hits:
        reasons.append(f"cold_cluster:{cluster.hits}<{policy.min_hits}")
    if len(fixtures) < policy.min_fixtures:
        reasons.append(f"insufficient_fixtures:{len(fixtures)}<{policy.min_fixtures}")
    if depth >= policy.max_lineage_depth:
        reasons.append(f"lineage_depth_exceeded:{depth}>={policy.max_lineage_depth}")
    return (not reasons), reasons


def score_parity(student: Callable[[Any], Any], fixtures: Sequence[Fixture]) -> Tuple[float, List[dict]]:
    """Fraction of fixtures the student reproduces exactly, plus the failures."""
    if not fixtures:
        return 0.0, [{"error": "no fixtures"}]
    misses = []
    ok = 0
    for fixture in fixtures:
        try:
            actual = student(fixture.query)
        except Exception as exc:  # a student that raises is a failed fixture
            misses.append({"fixture": fixture.key(), "error": type(exc).__name__})
            continue
        if actual == fixture.expected:
            ok += 1
        else:
            misses.append({"fixture": fixture.key(), "expected": fixture.expected, "actual": actual})
    return ok / len(fixtures), misses


def calibration_error(student: Callable[[Any], Any], fixtures: Sequence[Fixture]) -> float:
    """Mean absolute confidence gap for numeric outputs; 0.0 when non-numeric.

    Parity alone cannot see a student that is right but overconfident, which is
    what the brief means by calibration.  For non-numeric outputs there is no
    confidence to compare and this is honestly reported as 0.0 rather than
    invented.
    """
    gaps: List[float] = []
    for fixture in fixtures:
        try:
            actual = student(fixture.query)
        except Exception:
            gaps.append(1.0)
            continue
        if isinstance(actual, (int, float)) and isinstance(fixture.expected, (int, float)) \
                and not isinstance(actual, bool) and not isinstance(fixture.expected, bool):
            scale = max(1.0, abs(float(fixture.expected)))
            gaps.append(abs(float(actual) - float(fixture.expected)) / scale)
    return statistics.fmean(gaps) if gaps else 0.0


class ShadowRun:
    """Runs student beside teacher on live traffic; the teacher's answer is served."""

    def __init__(self, teacher: Callable[[Any], Any], student: Callable[[Any], Any]) -> None:
        self.teacher = teacher
        self.student = student
        self.report = ShadowReport()
        self._lock = threading.Lock()

    def __call__(self, query: Any) -> Any:
        t0 = time.perf_counter()
        expected = self.teacher(query)
        t_elapsed = time.perf_counter() - t0

        s0 = time.perf_counter()
        try:
            actual = self.student(query)
        except Exception as exc:
            actual = _StudentError(type(exc).__name__)
        s_elapsed = time.perf_counter() - s0

        with self._lock:
            r = self.report
            r.calls += 1
            r.teacher_latencies.append(t_elapsed)
            r.student_latencies.append(s_elapsed)
            if actual == expected:
                r.agreements += 1
            elif len(r.disagreements) < 32:
                r.disagreements.append({"expected": expected, "actual": repr(actual)})
        return expected  # shadow mode never serves the student's answer


@dataclass(frozen=True)
class _StudentError:
    kind: str


class DistillationRegistry:
    """Owns manifests, shadow runs and rollback artifacts."""

    def __init__(self, policy: Optional[Policy] = None) -> None:
        self.policy = policy or Policy()
        self.manifests: Dict[str, Manifest] = {}
        self._teachers: Dict[str, Callable[[Any], Any]] = {}
        self._students: Dict[str, Callable[[Any], Any]] = {}
        self._promoted: Dict[str, str] = {}   # (app, pattern) -> node_id
        self._lock = threading.RLock()

    # -- candidate -------------------------------------------------------
    def propose(self, cluster: QueryCluster, teacher: Callable[[Any], Any],
                student: Callable[[Any], Any], fixtures: Sequence[Fixture],
                parent_id: Optional[str] = None,
                policy: Optional[Policy] = None) -> Manifest:
        """Score a candidate against fixtures.  Raises rather than ship a worse node."""
        policy = policy or self.policy
        depth = (self.manifests[parent_id].depth + 1) if parent_id else 0
        eligible, reasons = eligibility(cluster, fixtures, policy, depth)
        if not eligible:
            raise DistillationRefused("; ".join(reasons))

        parity, misses = score_parity(student, fixtures)
        if parity < policy.min_parity:
            raise DistillationRefused(
                f"parity {parity:.3f} below tolerance {policy.min_parity:.3f} "
                f"({len(misses)} fixture failure(s))")
        cal = calibration_error(student, fixtures)
        if cal > policy.max_calibration_error:
            raise DistillationRefused(
                f"calibration error {cal:.3f} above tolerance {policy.max_calibration_error:.3f}")

        fixture_digest = _digest([[f.key(), f.expected] for f in fixtures])
        teacher_digest = _digest(getattr(teacher, "__qualname__", repr(teacher)))
        node_id = _digest({"v": MANIFEST_VERSION, "app": cluster.app, "pattern": cluster.pattern,
                           "parent": parent_id, "fixtures": fixture_digest,
                           "policy": policy.digest(), "teacher": teacher_digest})
        manifest = Manifest(
            version=MANIFEST_VERSION, node_id=node_id, app=cluster.app, pattern=cluster.pattern,
            parent_id=parent_id, depth=depth, fixture_digest=fixture_digest,
            policy_digest=policy.digest(), teacher_digest=teacher_digest,
            parity=parity, calibration_error=cal, tail_latency_ratio=1.0,
            created_at=time.time())
        with self._lock:
            self.manifests[node_id] = manifest
            self._teachers[node_id] = teacher
            self._students[node_id] = student
        return manifest

    # -- shadow ----------------------------------------------------------
    def shadow(self, node_id: str) -> ShadowRun:
        with self._lock:
            return ShadowRun(self._teachers[node_id], self._students[node_id])

    def promote(self, node_id: str, shadow: ShadowRun,
                policy: Optional[Policy] = None) -> Manifest:
        """Promote only after a clean shadow period.  Any regression refuses."""
        policy = policy or self.policy
        report = shadow.report
        if report.calls < policy.shadow_calls:
            raise DistillationRefused(
                f"shadow period incomplete: {report.calls}/{policy.shadow_calls} calls")
        if report.parity < policy.min_parity:
            raise DistillationRefused(
                f"shadow parity {report.parity:.3f} below tolerance {policy.min_parity:.3f}")
        ratio = report.tail_ratio(floor_s=policy.latency_floor_s)
        if ratio > policy.max_tail_latency_ratio:
            raise DistillationRefused(
                f"tail latency ratio {ratio:.2f} above tolerance {policy.max_tail_latency_ratio:.2f}")
        with self._lock:
            base = self.manifests[node_id]
            promoted = Manifest(**{**base.as_dict(), "tail_latency_ratio": ratio})
            self.manifests[node_id] = promoted
            self._promoted[f"{base.app}\x00{base.pattern}"] = node_id
        return promoted

    # -- serve / rollback ------------------------------------------------
    def resolve(self, app: str, pattern: str) -> Optional[Callable[[Any], Any]]:
        """The callable to serve: the promoted student, else nothing."""
        with self._lock:
            node_id = self._promoted.get(f"{app}\x00{pattern}")
            return self._students.get(node_id) if node_id else None

    def rollback(self, node_id: str) -> Dict[str, Any]:
        """Restore the teacher.  Non-destructive: the manifest survives for audit."""
        with self._lock:
            manifest = self.manifests.get(node_id)
            if manifest is None:
                raise KeyError(node_id)
            key = f"{manifest.app}\x00{manifest.pattern}"
            was_promoted = self._promoted.pop(key, None) == node_id
            teacher = self._teachers[node_id]
        return {"node_id": node_id, "was_promoted": was_promoted,
                "restored": teacher, "manifest_retained": node_id in self.manifests}

    def lineage(self, node_id: str) -> List[Dict[str, Any]]:
        """Full provenance chain, newest first, back to the original teacher."""
        chain: List[Dict[str, Any]] = []
        seen = set()
        current: Optional[str] = node_id
        while current and current not in seen:
            seen.add(current)
            manifest = self.manifests.get(current)
            if manifest is None:
                break
            chain.append(manifest.as_dict())
            current = manifest.parent_id
        return chain

    def reproduce(self, node_id: str, fixtures: Sequence[Fixture],
                  policy: Optional[Policy] = None) -> bool:
        """Reproducibility check: do these inputs still yield the same node id?"""
        manifest = self.manifests[node_id]
        policy = policy or self.policy
        expected = _digest({"v": MANIFEST_VERSION, "app": manifest.app,
                            "pattern": manifest.pattern, "parent": manifest.parent_id,
                            "fixtures": _digest([[f.key(), f.expected] for f in fixtures]),
                            "policy": policy.digest(), "teacher": manifest.teacher_digest})
        return expected == node_id
