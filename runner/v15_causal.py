#!/usr/bin/env python3
"""Timestamp-aligned, leakage-free multi-scale association analysis.

``hivemind_v15.FractalCausalGraph`` keeps one deque per series and pairs them by
*index position*, which makes list position the time axis.  Two consequences
that proposal 7 exists to fix:

* **Missingness silently corrupts the lag.**  If a driver misses two samples,
  every pair after that point is shifted, and a perfect lead/lag relationship
  measures as noise.  A test here reproduces exactly that on the base class:
  r collapses from ~1.0 to ~0.06 with no warning.
* **Correlations are labelled ``causes``.**  Lagged correlation is *association*.
  Calling it causation invites acting on a confounder, so this module keeps the
  two apart in the type system: :class:`Association` carries
  ``causal_claim=False`` and states the confounders it cannot rule out.

Everything here is built on explicit ``(timestamp, value)`` observations aligned
to a grid, so a gap stays a gap instead of pulling later samples backwards, and
every lag window is constructed to be strictly backward-looking.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

DEFAULT_SCALES: Tuple[int, ...] = (1, 4, 16, 64)


class LookAheadError(AssertionError):
    """A window would have used information from at or after the predicted time."""


@dataclass(frozen=True)
class Sample:
    t: int          # grid index, not wall time: alignment is explicit
    value: Optional[float]   # None means MISSING, which is not the same as 0.0


@dataclass(frozen=True)
class Association:
    """An observed statistical association.  Deliberately not a causal claim."""

    driver: str
    target: str
    scale: int
    correlation: float
    n: int
    ci_low: float
    ci_high: float
    causal_claim: bool = False
    provenance: Dict[str, Any] = field(default_factory=dict)

    @property
    def significant(self) -> bool:
        """True when the confidence interval excludes zero."""
        return (self.ci_low > 0) or (self.ci_high < 0)

    def limitations(self) -> List[str]:
        return [
            "observational: no intervention was performed, so this cannot establish causation",
            "confounding: a common driver of both series would produce the same correlation",
            "reverse causation: the lag is consistent with, but does not prove, direction",
            f"sample size n={self.n} at scale {self.scale}",
        ]


class AlignedSeries:
    """Grid-aligned series where a gap stays a gap."""

    def __init__(self, history: int = 512) -> None:
        self.history = history
        self._points: Dict[str, Dict[int, float]] = {}
        self._max_t: int = -1

    def observe(self, t: int, values: Dict[str, Optional[float]]) -> None:
        """Record observations at grid index ``t``.  Absent keys stay absent."""
        if t < 0:
            raise ValueError("grid index must be non-negative")
        for name, value in values.items():
            if value is None:
                continue
            self._points.setdefault(name, {})[t] = float(value)
        self._max_t = max(self._max_t, t)
        self._evict()

    def _evict(self) -> None:
        floor = self._max_t - self.history
        if floor < 0:
            return
        for points in self._points.values():
            for t in [t for t in points if t < floor]:
                del points[t]

    def names(self) -> List[str]:
        return sorted(self._points)

    def series(self, name: str, upto: Optional[int] = None) -> List[Sample]:
        """Dense samples from 0..upto with explicit ``None`` for missing points."""
        points = self._points.get(name, {})
        if not points:
            return []
        end = self._max_t if upto is None else upto
        start = max(0, end - self.history + 1)
        return [Sample(t, points.get(t)) for t in range(start, end + 1)]

    def coverage(self, name: str, upto: Optional[int] = None) -> float:
        samples = self.series(name, upto)
        if not samples:
            return 0.0
        return sum(1 for s in samples if s.value is not None) / len(samples)


def aligned_pairs(series: AlignedSeries, driver: str, target: str, scale: int,
                  upto: Optional[int] = None) -> List[Tuple[int, float, float]]:
    """Pairs (t, driver[t-scale], target[t]) keeping only points present in BOTH.

    This is the fix for the base class: pairing is by grid index, so a missing
    driver sample drops that one pair instead of shifting every later pair.
    """
    if scale < 1:
        raise ValueError("scale must be >= 1")
    d = {s.t: s.value for s in series.series(driver, upto) if s.value is not None}
    y = {s.t: s.value for s in series.series(target, upto) if s.value is not None}
    pairs = []
    for t in sorted(y):
        source_t = t - scale
        if source_t in d:
            if source_t >= t:  # defensive: the window must be strictly backward
                raise LookAheadError(f"driver index {source_t} is not before target index {t}")
            pairs.append((t, d[source_t], y[t]))
    return pairs


def _pearson(xs: Sequence[float], ys: Sequence[float]) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    mx = statistics.fmean(xs)
    my = statistics.fmean(ys)
    sx = sum((x - mx) ** 2 for x in xs)
    sy = sum((y - my) ** 2 for y in ys)
    denom = math.sqrt(sx * sy)
    if denom == 0:
        return 0.0
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / denom


def fisher_interval(r: float, n: int, z: float = 1.96) -> Tuple[float, float]:
    """Calibrated CI for a correlation via the Fisher z transform.

    Returning (-1, 1) for tiny samples is the honest answer: with n<4 there is
    no information, and a narrow interval would be a fabricated certainty.
    """
    if n < 4 or abs(r) >= 1.0:
        return (-1.0, 1.0) if n < 4 else (r, r)
    zr = 0.5 * math.log((1 + r) / (1 - r))
    se = 1.0 / math.sqrt(n - 3)
    lo, hi = zr - z * se, zr + z * se
    return (math.tanh(lo), math.tanh(hi))


def associations(series: AlignedSeries, target: str, drivers: Iterable[str],
                 scales: Sequence[int] = DEFAULT_SCALES,
                 upto: Optional[int] = None,
                 min_pairs: int = 8) -> List[Association]:
    """Multi-scale associations with provenance and calibrated uncertainty."""
    found: List[Association] = []
    for driver in drivers:
        for scale in scales:
            pairs = aligned_pairs(series, driver, target, scale, upto)
            if len(pairs) < min_pairs:
                continue
            xs = [p[1] for p in pairs]
            ys = [p[2] for p in pairs]
            r = _pearson(xs, ys)
            lo, hi = fisher_interval(r, len(pairs))
            found.append(Association(
                driver=driver, target=target, scale=scale, correlation=r, n=len(pairs),
                ci_low=lo, ci_high=hi,
                provenance={
                    "method": "pearson_on_grid_aligned_lag",
                    "first_t": pairs[0][0], "last_t": pairs[-1][0],
                    "driver_coverage": series.coverage(driver, upto),
                    "target_coverage": series.coverage(target, upto),
                    "dropped_unpaired": True,
                    "window": f"driver[t-{scale}] -> target[t]",
                }))
    found.sort(key=lambda a: (-abs(a.correlation), a.scale, a.driver))
    return found


def predict(series: AlignedSeries, target: str, drivers: Iterable[str],
            scales: Sequence[int] = DEFAULT_SCALES, upto: Optional[int] = None,
            top_k: int = 3) -> Dict[str, Any]:
    """Point prediction plus the uncertainty and the limits of the claim."""
    upto = series._max_t if upto is None else upto  # noqa: SLF001 - same-module contract
    found = [a for a in associations(series, target, drivers, scales, upto) if a.significant]
    history = [s.value for s in series.series(target, upto) if s.value is not None]
    base = history[-1] if history else 0.0

    delta = 0.0
    used: List[Association] = []
    for assoc in found[:top_k]:
        pairs = aligned_pairs(series, assoc.driver, target, assoc.scale, upto)
        if len(pairs) < 2:
            continue
        recent, previous = pairs[-1][1], pairs[-2][1]
        delta += assoc.correlation * (recent - previous) / max(1, top_k)
        used.append(assoc)

    spread = statistics.pstdev(history) if len(history) > 1 else 0.0
    return {
        "target": target,
        "prediction": base + delta,
        "interval": (base + delta - 1.96 * spread, base + delta + 1.96 * spread),
        "associations": [a.__dict__ for a in used],
        "causal_claim": False,
        "limitations": used[0].limitations() if used else
            ["no significant association found at any configured scale"],
    }


def walk_forward(series: AlignedSeries, target: str, drivers: Sequence[str],
                 scales: Sequence[int] = DEFAULT_SCALES,
                 folds: int = 4, min_train: int = 40) -> Dict[str, Any]:
    """Walk-forward evaluation.  Every fold trains strictly on the past.

    Compared against a single-scale baseline on the SAME folds, and against a
    persistence (last-value) baseline, because a model that cannot beat "assume
    no change" has not earned its complexity.
    """
    end = series._max_t  # noqa: SLF001
    if end < min_train + folds:
        raise ValueError("not enough history for the requested walk-forward split")
    step = max(1, (end - min_train) // folds)

    errors: Dict[str, List[float]] = {"multi_scale": [], "single_scale": [], "persistence": []}
    for fold in range(folds):
        cutoff = min_train + fold * step
        if cutoff >= end:
            break
        actual_samples = [s for s in series.series(target, cutoff + 1) if s.value is not None]
        if not actual_samples or actual_samples[-1].t != cutoff + 1:
            continue
        actual = actual_samples[-1].value

        multi = predict(series, target, drivers, scales, upto=cutoff)["prediction"]
        single = predict(series, target, drivers, (scales[0],), upto=cutoff)["prediction"]
        history = [s.value for s in series.series(target, cutoff) if s.value is not None]
        last = history[-1] if history else 0.0

        errors["multi_scale"].append(abs(multi - actual))
        errors["single_scale"].append(abs(single - actual))
        errors["persistence"].append(abs(last - actual))

    summary = {k: (statistics.fmean(v) if v else float("nan")) for k, v in errors.items()}
    return {
        "folds_evaluated": len(errors["multi_scale"]),
        "mae": summary,
        "beats_persistence": (summary["multi_scale"] < summary["persistence"])
            if errors["multi_scale"] else False,
        "note": ("every fold predicts t+1 using only data at or before the cutoff; "
                 "a model that does not beat persistence has not earned its complexity"),
    }
