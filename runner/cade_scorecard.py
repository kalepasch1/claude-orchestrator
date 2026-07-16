"""
cade_scorecard.py - Fleet-wide CADE scorecard aggregation.

Pure functions that take per-app CADE telemetry (win-rate lift, calibration gap,
alignment recall/surprise, override failure-rate) and produce:
  (a) a normalized fleet scorecard (0-100 per dimension per app)
  (b) a weakest_app + recommended_next_capability hint for the scheduler

No live HTTP — all data passed in.
"""
from __future__ import annotations
from typing import Any


# ── dimension weights (sum to 1.0) ──────────────────────────────
DIMENSION_WEIGHTS: dict[str, float] = {
    "win_rate_lift": 0.30,
    "calibration_gap": 0.25,
    "alignment_recall": 0.20,
    "alignment_surprise": 0.10,
    "override_failure_rate": 0.15,
}

# Capabilities the scheduler can recommend
CAPABILITIES = [
    "calibration_tuning",
    "alignment_expansion",
    "override_hardening",
    "win_rate_optimization",
    "surprise_reduction",
]

# Maps each dimension to the capability that improves it
_DIM_TO_CAPABILITY: dict[str, str] = {
    "win_rate_lift": "win_rate_optimization",
    "calibration_gap": "calibration_tuning",
    "alignment_recall": "alignment_expansion",
    "alignment_surprise": "surprise_reduction",
    "override_failure_rate": "override_hardening",
}


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def normalize_dimension(name: str, raw: float) -> float:
    """Convert a raw CADE metric to a 0-100 score (higher = better).

    - win_rate_lift: raw is a fraction (e.g. 0.12 = 12% lift). Scale: *100, clamped.
    - calibration_gap: raw is abs error (lower is better). Score = 100 - gap*100.
    - alignment_recall: raw is 0-1 recall. Score = raw*100.
    - alignment_surprise: raw is 0-1 surprise rate (lower is better). Score = (1-raw)*100.
    - override_failure_rate: raw is 0-1 failure rate (lower is better). Score = (1-raw)*100.
    """
    if name == "win_rate_lift":
        return _clamp(raw * 100)
    elif name == "calibration_gap":
        return _clamp(100.0 - raw * 100)
    elif name == "alignment_recall":
        return _clamp(raw * 100)
    elif name == "alignment_surprise":
        return _clamp((1.0 - raw) * 100)
    elif name == "override_failure_rate":
        return _clamp((1.0 - raw) * 100)
    return _clamp(raw * 100)


def score_app(telemetry: dict[str, float]) -> dict[str, Any]:
    """Score a single app across all CADE dimensions.

    Args:
        telemetry: dict with keys from DIMENSION_WEIGHTS, values are raw metrics.

    Returns:
        dict with 'dimensions' (per-dim normalized scores), 'composite' (weighted avg),
        and 'weakest_dimension' (name of lowest-scoring dimension).
    """
    dims: dict[str, float] = {}
    for dim in DIMENSION_WEIGHTS:
        raw = telemetry.get(dim, 0.0)
        dims[dim] = normalize_dimension(dim, raw)

    composite = sum(dims[d] * DIMENSION_WEIGHTS[d] for d in DIMENSION_WEIGHTS)
    weakest = min(dims, key=lambda d: dims[d] * DIMENSION_WEIGHTS[d])

    return {
        "dimensions": dims,
        "composite": round(composite, 2),
        "weakest_dimension": weakest,
    }


def fleet_scorecard(fleet_telemetry: dict[str, dict[str, float]]) -> dict[str, Any]:
    """Produce a normalized fleet scorecard from per-app CADE telemetry.

    Args:
        fleet_telemetry: {app_name: {dim: raw_value, ...}, ...}

    Returns:
        dict with 'apps' (per-app scores), 'weakest_app', and
        'recommended_next_capability'.
    """
    if not fleet_telemetry:
        return {
            "apps": {},
            "weakest_app": None,
            "recommended_next_capability": None,
        }

    apps: dict[str, dict[str, Any]] = {}
    for app_name, telemetry in fleet_telemetry.items():
        apps[app_name] = score_app(telemetry)

    # Weakest app = lowest composite; ties broken alphabetically
    weakest_app = min(
        apps,
        key=lambda a: (apps[a]["composite"], a),
    )
    weakest_dim = apps[weakest_app]["weakest_dimension"]
    recommended = _DIM_TO_CAPABILITY.get(weakest_dim, CAPABILITIES[0])

    return {
        "apps": apps,
        "weakest_app": weakest_app,
        "recommended_next_capability": recommended,
    }
