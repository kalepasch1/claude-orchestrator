"""Rolling z-score detector usable for risk, filing, and department metrics."""
from __future__ import annotations
from dataclasses import dataclass
from statistics import fmean, pstdev
from typing import Iterable


@dataclass(frozen=True)
class MetricAnomaly:
    metric: str
    value: float
    baseline: float
    z_score: float
    severity: str


class CrossModuleAnomalyDetector:
    def detect(self, metric: str, values: Iterable[float], threshold: float = 3.0) -> MetricAnomaly | None:
        history = [float(v) for v in values]
        if len(history) < 4: return None
        baseline_values, value = history[:-1], history[-1]
        mean, deviation = fmean(baseline_values), pstdev(baseline_values)
        if deviation == 0:
            z = 0.0 if value == mean else float("inf")
        else:
            z = (value - mean) / deviation
        if abs(z) < threshold: return None
        return MetricAnomaly(metric, value, mean, z, "critical" if abs(z) >= threshold * 2 else "warning")
