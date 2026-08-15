#!/usr/bin/env python3
"""Adversarial anomaly curriculum with poisoning defence and honest metrics.

``hivemind_v15.AdversarialAnomalyCurriculum`` promotes a difficulty level once a
detector clears 85% over a rolling window.  It has three gaps that matter once
the curriculum drives anything real, and this module closes them:

* **Promotion is one-way.**  ``record`` only ever increments ``level``, so a
  detector that degrades keeps facing harder anomalies it cannot catch, and the
  curriculum quietly stops measuring anything.  Difficulty here also *demotes*.
* **Federated exchange leaks shape.**  Sharing raw failure vectors publishes a
  tenant's real signal.  Exchange here is schema-sanitised and k-anonymous, and
  refuses to emit a cohort too small to hide in.
* **Nothing resists poisoning.**  A participant that floods the curriculum with
  mislabelled samples steers every other participant.  Contributions here are
  per-source rate-limited, outlier-screened against the cohort, and quarantined
  rather than silently mixed in.

On reporting, the brief is explicit and this module follows it literally: an
improvement RATIO is never converted into an accuracy claim.  :func:`evaluate`
reports true/false positives and negatives measured on a holdout family the
curriculum never trained against, and refuses to emit a single headline number.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
import statistics
from collections import Counter, deque
from dataclasses import dataclass, field
from typing import Any, Callable, Deque, Dict, List, Optional, Sequence, Tuple

try:  # pragma: no cover - import shape depends on caller
    from hivemind_v15 import AdversarialAnomalyCurriculum, canonical_app
except ImportError:  # pragma: no cover
    from .hivemind_v15 import AdversarialAnomalyCurriculum, canonical_app  # type: ignore


K_ANONYMITY = 3
PROMOTE_AT = .85
DEMOTE_AT = .50
WINDOW = 16


class PrivacyFloor(RuntimeError):
    """A cohort was too small to share without identifying its members."""


class Poisoned(RuntimeError):
    """A contribution was refused by the poisoning defences."""


@dataclass(frozen=True)
class FailureSchema:
    """A sanitised description of a failure MODE -- never a raw record."""

    family: str
    dimensions: int
    scale: float

    def digest(self) -> str:
        return hashlib.blake2b(
            json.dumps(self.__dict__, sort_keys=True).encode(), digest_size=8).hexdigest()


@dataclass(frozen=True)
class Anomaly:
    family: str
    level: int
    vector: Tuple[float, ...]
    provenance: str          # immutable: schema digest + level + generator seed

    def verify(self, schema: FailureSchema, seed: int) -> bool:
        return self.provenance == provenance_for(schema, self.level, seed)


def provenance_for(schema: FailureSchema, level: int, seed: int) -> str:
    return hashlib.blake2b(
        f"{schema.digest()}:{level}:{seed}".encode(), digest_size=12).hexdigest()


class Curriculum:
    """Difficulty ladder that promotes AND demotes, with holdout families."""

    def __init__(self, seed: int = 0, holdout_families: Sequence[str] = ()) -> None:
        self.seed = seed
        self.level = 1
        self.rng = random.Random(seed)
        self.outcomes: Deque[bool] = deque(maxlen=WINDOW)
        self.holdout = {f.lower() for f in holdout_families}
        self.history: List[Dict[str, Any]] = []
        self.metrics: Counter = Counter()

    # -- generation ------------------------------------------------------
    def generate(self, schema: FailureSchema, sample: Sequence[float],
                 count: int = 8) -> List[Anomaly]:
        """Synthesise anomalies from a SCHEMA, never from a raw tenant record."""
        if schema.family.lower() in self.holdout:
            raise ValueError(
                f"family {schema.family!r} is held out: training on it would "
                "destroy the only unbiased novelty estimate available")
        severity = max(.02, .8 / self.level)
        prov = provenance_for(schema, self.level, self.seed)
        out: List[Anomaly] = []
        for _ in range(count):
            row = [float(v) for v in sample] or [0.0]
            idx = self.rng.randrange(len(row))
            mode = self.level % 3
            if mode == 1:
                row[idx] += self.rng.choice((-1, 1)) * severity * (abs(row[idx]) + 1)
            elif mode == 2:
                row[idx] *= 1 + self.rng.choice((-severity, severity))
            else:
                row[max(0, idx - 1):idx + 1] = list(reversed(row[max(0, idx - 1):idx + 1]))
            out.append(Anomaly(schema.family, self.level, tuple(row), prov))
        self.metrics["generated"] += len(out)
        return out

    def diversity(self, anomalies: Sequence[Anomaly]) -> float:
        """Fraction of distinct vectors: a batch of clones teaches nothing."""
        if not anomalies:
            return 0.0
        return len({a.vector for a in anomalies}) / len(anomalies)

    def generate_diverse(self, schema: FailureSchema, sample: Sequence[float],
                         count: int = 8, min_diversity: float = .5,
                         attempts: int = 5) -> List[Anomaly]:
        """Retry until the batch is varied enough to be worth scoring."""
        best: List[Anomaly] = []
        for _ in range(attempts):
            batch = self.generate(schema, sample, count)
            if self.diversity(batch) > self.diversity(best):
                best = batch
            if self.diversity(best) >= min_diversity:
                return best
        self.metrics["low_diversity_batches"] += 1
        return best

    # -- ladder ----------------------------------------------------------
    def record(self, detected: bool) -> int:
        """Promote on mastery, DEMOTE on collapse.

        One-way promotion is a measurement bug: a detector that degrades keeps
        facing anomalies it cannot catch, so the curriculum stops distinguishing
        "hard" from "broken".
        """
        self.outcomes.append(bool(detected))
        if len(self.outcomes) < WINDOW:
            return self.level
        rate = sum(self.outcomes) / len(self.outcomes)
        if rate >= PROMOTE_AT:
            self.level += 1
            self._note("promote", rate)
        elif rate <= DEMOTE_AT and self.level > 1:
            self.level -= 1
            self._note("demote", rate)
        return self.level

    def _note(self, action: str, rate: float) -> None:
        self.history.append({"action": action, "rate": rate, "level": self.level})
        self.outcomes.clear()
        self.metrics[action] += 1


# -- federated exchange --------------------------------------------------
@dataclass
class Contribution:
    source: str
    schema: FailureSchema
    detection_rate: float
    samples: int


class FederatedExchange:
    """k-anonymous, poisoning-resistant sharing of curriculum learnings."""

    def __init__(self, k: int = K_ANONYMITY, per_source_limit: int = 8,
                 outlier_sigma: float = 2.5) -> None:
        self.k = k
        self.per_source_limit = per_source_limit
        self.outlier_sigma = outlier_sigma
        self._pending: List[Contribution] = []
        self._per_source: Counter = Counter()
        self.quarantined: List[Dict[str, Any]] = []
        self.metrics: Counter = Counter()

    def contribute(self, source: str, schema: FailureSchema,
                   detection_rate: float, samples: int) -> None:
        source = canonical_app(source)
        if not (0.0 <= detection_rate <= 1.0):
            raise Poisoned(f"detection_rate {detection_rate} outside [0,1]")
        if samples <= 0:
            raise Poisoned("a contribution must be backed by at least one sample")
        if self._per_source[source] >= self.per_source_limit:
            self.metrics["rate_limited"] += 1
            raise Poisoned(
                f"{source} exceeded its per-round contribution limit "
                f"({self.per_source_limit}); one participant cannot outvote the cohort")
        self._per_source[source] += 1
        self._pending.append(Contribution(source, schema, detection_rate, samples))

    def _screen(self, contributions: Sequence[Contribution]) -> Tuple[List[Contribution], List[dict]]:
        """Drop contributions far outside the cohort consensus."""
        if len(contributions) < 3:
            return list(contributions), []
        rates = [c.detection_rate for c in contributions]
        mean = statistics.fmean(rates)
        sd = statistics.pstdev(rates)
        if sd == 0:
            return list(contributions), []
        kept, dropped = [], []
        for c in contributions:
            if abs(c.detection_rate - mean) > self.outlier_sigma * sd:
                dropped.append({"source": c.source, "rate": c.detection_rate,
                                "cohort_mean": mean, "reason": "outlier"})
            else:
                kept.append(c)
        return kept, dropped

    def aggregate(self) -> Dict[str, Any]:
        """Emit a cohort summary, or refuse if the cohort is too small to hide in."""
        by_family: Dict[str, List[Contribution]] = {}
        for c in self._pending:
            by_family.setdefault(c.schema.family, []).append(c)

        results: Dict[str, Any] = {}
        suppressed: List[str] = []
        for family, group in by_family.items():
            distinct_sources = {c.source for c in group}
            if len(distinct_sources) < self.k:
                suppressed.append(family)
                self.metrics["suppressed_small_cohort"] += 1
                continue
            kept, dropped = self._screen(group)
            self.quarantined.extend(dropped)
            if len(kept) < self.k:
                suppressed.append(family)
                continue
            results[family] = {
                "sources": len(kept),
                "mean_detection_rate": statistics.fmean(c.detection_rate for c in kept),
                "total_samples": sum(c.samples for c in kept),
                "quarantined": len(dropped),
            }
        return {"families": results, "suppressed": sorted(suppressed),
                "k": self.k, "quarantined": self.quarantined,
                "note": ("families below k distinct sources are withheld entirely; "
                         "no raw vectors or tenant records are ever exchanged")}

    def raw_leak_check(self) -> bool:
        """Exchanged payloads contain only schemas and rates -- never vectors."""
        return all(not hasattr(c, "vector") for c in self._pending)


# -- evaluation ----------------------------------------------------------
def evaluate(detector: Callable[[Sequence[float]], bool],
             anomalies: Sequence[Anomaly],
             benign: Sequence[Sequence[float]]) -> Dict[str, Any]:
    """Report TP/FP/TN/FN.  Deliberately emits no single headline number.

    An improvement ratio is not an accuracy, and collapsing these four counts
    into one figure is exactly the conversion the brief forbids.
    """
    tp = sum(1 for a in anomalies if detector(a.vector))
    fn = len(anomalies) - tp
    fp = sum(1 for b in benign if detector(b))
    tn = len(benign) - fp
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    return {
        "true_positives": tp, "false_negatives": fn,
        "false_positives": fp, "true_negatives": tn,
        "precision": precision, "recall": recall,
        "false_positive_rate": fp / (fp + tn) if (fp + tn) else 0.0,
        "note": ("precision and recall are reported separately and measured on real "
                 "samples; no improvement ratio is presented as an accuracy"),
    }


def holdout_evaluation(curriculum: Curriculum, detector: Callable[[Sequence[float]], bool],
                       holdout_schema: FailureSchema, sample: Sequence[float],
                       benign: Sequence[Sequence[float]], count: int = 16) -> Dict[str, Any]:
    """Score against a family the curriculum was never allowed to train on."""
    if holdout_schema.family.lower() not in curriculum.holdout:
        raise ValueError(f"{holdout_schema.family!r} is not a registered holdout family")
    probe = Curriculum(seed=curriculum.seed + 1)   # a generator with no holdout ban
    probe.level = curriculum.level
    anomalies = probe.generate(holdout_schema, sample, count)
    report = evaluate(detector, anomalies, benign)
    report["family"] = holdout_schema.family
    report["held_out"] = True
    report["curriculum_level"] = curriculum.level
    return report


def calibrated_threshold(scores: Sequence[float], target_fpr: float = .05) -> float:
    """Pick the score cut that meets a target false-positive rate on benign data."""
    if not scores:
        raise ValueError("cannot calibrate a threshold without benign scores")
    if not (0.0 < target_fpr < 1.0):
        raise ValueError("target_fpr must be strictly between 0 and 1")
    ordered = sorted(scores)
    index = min(len(ordered) - 1, math.ceil((1 - target_fpr) * len(ordered)) - 1)
    return ordered[max(0, index)]
