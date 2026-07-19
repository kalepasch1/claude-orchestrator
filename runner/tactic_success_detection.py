#!/usr/bin/env python3
"""
tactic_success_detection.py - identify "proven" growth tactics from A/B test results.

Queries recent A/B test metrics (via ab_test_framework), computes effect size
(Cohen's d) and a two-sample Welch t-test p-value for treatment vs control,
and returns tactics where lift > configured threshold and p < significance level.

Env vars (all optional, with defaults):
  ORCH_TACTIC_LOOKBACK_DAYS   - days of metrics to consider (default: 30)
  ORCH_TACTIC_MIN_LIFT        - minimum relative lift to qualify (default: 0.10 = 10%)
  ORCH_TACTIC_P_THRESHOLD     - max p-value for significance (default: 0.05)
  ORCH_TACTIC_MIN_SAMPLES     - minimum observations per variant (default: 30)
"""
import os, sys, math, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
LOOKBACK_DAYS = int(os.environ.get("ORCH_TACTIC_LOOKBACK_DAYS", "30"))
MIN_LIFT = float(os.environ.get("ORCH_TACTIC_MIN_LIFT", "0.10"))
P_THRESHOLD = float(os.environ.get("ORCH_TACTIC_P_THRESHOLD", "0.05"))
MIN_SAMPLES = int(os.environ.get("ORCH_TACTIC_MIN_SAMPLES", "30"))

# Module-level counters
_stats_queries = 0
_stats_proven = 0
_stats_errors = 0


# ---------------------------------------------------------------------------
# Statistics helpers (stdlib-only, no scipy dependency)
# ---------------------------------------------------------------------------
def _mean(values: List[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _variance(values: List[float], ddof: int = 1) -> float:
    if len(values) < 2:
        return 0.0
    m = _mean(values)
    return sum((x - m) ** 2 for x in values) / (len(values) - ddof)


def _welch_t_test(values_a: List[float], values_b: List[float]) -> float:
    """
    Two-sample Welch t-test.  Returns approximate two-tailed p-value using
    the normal approximation (valid for n >= 30 per group).
    Falls back to 1.0 on degenerate input.
    """
    n_a, n_b = len(values_a), len(values_b)
    if n_a < 2 or n_b < 2:
        return 1.0

    mean_a, mean_b = _mean(values_a), _mean(values_b)
    var_a, var_b = _variance(values_a), _variance(values_b)

    se = math.sqrt(var_a / n_a + var_b / n_b) if (var_a + var_b) > 0 else 0.0
    if se == 0.0:
        return 1.0

    t_stat = (mean_b - mean_a) / se

    # Normal CDF approximation (Abramowitz & Stegun 26.2.17) for |z|
    z = abs(t_stat)
    p = 0.5 * math.erfc(z / math.sqrt(2))  # one-tail
    return 2 * p  # two-tailed


def _cohens_d(values_a: List[float], values_b: List[float]) -> float:
    """Cohen's d effect size (pooled std)."""
    n_a, n_b = len(values_a), len(values_b)
    if n_a < 2 or n_b < 2:
        return 0.0
    var_a, var_b = _variance(values_a), _variance(values_b)
    pooled_std = math.sqrt(((n_a - 1) * var_a + (n_b - 1) * var_b) / (n_a + n_b - 2))
    if pooled_std == 0:
        return 0.0
    return (_mean(values_b) - _mean(values_a)) / pooled_std


# ---------------------------------------------------------------------------
# Core: fetch metrics from ab_test_framework
# ---------------------------------------------------------------------------
def _fetch_test_metrics(test_name: str, metric_name: str,
                        lookback_days: int = None) -> Dict[str, List[float]]:
    """
    Pull metric values per variant from ab_test_framework's in-memory store.

    Returns {"control": [v, ...], "variant_a": [v, ...], ...}
    """
    import ab_test_framework

    lookback = lookback_days if lookback_days is not None else LOOKBACK_DAYS
    cutoff = time.time() - lookback * 86400

    all_metrics = ab_test_framework.get_metrics(test_name)
    if metric_name not in all_metrics:
        return {}

    by_variant: Dict[str, List[float]] = {}
    for record in all_metrics[metric_name]:
        ts = record.get("timestamp", 0)
        if ts < cutoff:
            continue
        variant = record.get("variant", "")
        if variant not in by_variant:
            by_variant[variant] = []
        by_variant[variant].append(float(record.get("value", 0)))

    return by_variant


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def detect_proven_tactics(
    test_names: List[str],
    metric_name: str = "conversion_rate",
    control_variant: str = "control",
    lookback_days: Optional[int] = None,
    min_lift: Optional[float] = None,
    p_threshold: Optional[float] = None,
    min_samples: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    Scan a list of A/B tests and return tactics whose treatment variants
    show statistically significant lift over control.

    Returns a list of dicts:
      {"test_name", "variant", "control_mean", "treatment_mean",
       "lift", "p_value", "effect_size", "n_control", "n_treatment"}
    """
    global _stats_queries, _stats_proven, _stats_errors
    _stats_queries += 1

    _lift = min_lift if min_lift is not None else MIN_LIFT
    _pval = p_threshold if p_threshold is not None else P_THRESHOLD
    _min_n = min_samples if min_samples is not None else MIN_SAMPLES

    proven: List[Dict[str, Any]] = []

    for test_name in test_names:
        try:
            by_variant = _fetch_test_metrics(test_name, metric_name, lookback_days)
            control_values = by_variant.get(control_variant, [])
            if len(control_values) < _min_n:
                continue

            for variant, treatment_values in by_variant.items():
                if variant == control_variant:
                    continue
                if len(treatment_values) < _min_n:
                    continue

                c_mean = _mean(control_values)
                t_mean = _mean(treatment_values)

                # Relative lift (guard against zero control mean)
                if c_mean == 0:
                    lift = float("inf") if t_mean > 0 else 0.0
                else:
                    lift = (t_mean - c_mean) / abs(c_mean)

                p_value = _welch_t_test(control_values, treatment_values)
                effect = _cohens_d(control_values, treatment_values)

                if lift >= _lift and p_value < _pval:
                    _stats_proven += 1
                    proven.append({
                        "test_name": test_name,
                        "variant": variant,
                        "control_mean": round(c_mean, 6),
                        "treatment_mean": round(t_mean, 6),
                        "lift": round(lift, 6),
                        "p_value": round(p_value, 6),
                        "effect_size": round(effect, 4),
                        "n_control": len(control_values),
                        "n_treatment": len(treatment_values),
                    })
        except Exception:
            _stats_errors += 1
            continue  # fail-soft: skip this test

    return proven


def stats() -> Dict[str, Any]:
    """Return module stats for monitoring."""
    return {
        "queries": _stats_queries,
        "proven_tactics_found": _stats_proven,
        "errors": _stats_errors,
        "config": {
            "lookback_days": LOOKBACK_DAYS,
            "min_lift": MIN_LIFT,
            "p_threshold": P_THRESHOLD,
            "min_samples": MIN_SAMPLES,
        },
    }


if __name__ == "__main__":
    # Quick self-test: list any proven tactics across all recorded tests
    import ab_test_framework
    s = ab_test_framework.stats()
    print(f"tactic_success_detection: ab store has {s['total_records']} records")
    # No tests to scan in standalone mode; module is meant to be called programmatically.
    print("tactic_success_detection: module loaded OK")
