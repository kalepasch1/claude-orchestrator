#!/usr/bin/env python3
"""risk_assessment.py — numeric merge-risk score for a pull request.

Slice 3 of "streamline merge workflow with AI-based review": give the merge train a
single number it can gate on, instead of every caller re-deriving "is this scary?"
from raw diff stats.

Contract
--------
    score_pull_request(metrics) -> float in [0, 100]   (higher = riskier)
    classify(score)             -> "low" | "medium" | "high"
    assess(metrics)             -> {"score", "band", "components"}

Five components, each weighted and each SATURATING (see risk_config.yaml):

    files_changed        breadth of the diff
    lines_churn          added + deleted
    coverage_delta       only the DROP counts; a coverage gain is not risk
    contributor_history  recent reverts, damped by a track record of merges
    material_paths       count of touched paths the materiality classifier flags

Saturation is the point: without it a 4000-line reformat would pin the score at 100
and drown out a two-line change to server/utils/policy/, which is the change that
actually needs a human.

Conventions (CLAUDE.md)
-----------------------
* Fail-soft: every public function returns a sensible default on bad input — None,
  a string where a number belongs, a missing/corrupt config file. Nothing here
  raises at a caller, because this sits in the merge path and must not wedge it.
* Module-level singleton: `get_config()` delegates to one cached instance;
  `invalidate_config()` drops it (tests and operators need that).
* Env-var configuration: ORCH_RISK_CONFIG_PATH overrides the config location.
"""
from __future__ import annotations

import logging
import os
import threading

logger = logging.getLogger(__name__)

_DEFAULT_CONFIG_FILENAME = "risk_config.yaml"

DEFAULT_CONFIG = {
    "thresholds": {"low_risk_max": 30.0, "high_risk_min": 70.0},
    "weights": {
        "files_changed": 20.0,
        "lines_churn": 25.0,
        "coverage_delta": 25.0,
        "contributor_history": 15.0,
        "material_paths": 15.0,
    },
    "saturation": {
        "files_changed": 25,
        "lines_churn": 800,
        "coverage_drop_pct": 5.0,
        "contributor_reverts": 3,
        "material_paths": 3,
    },
}

_COMPONENTS = tuple(DEFAULT_CONFIG["weights"])


# --------------------------------------------------------------------------- config


def _num(value, default=0.0):
    """Coerce *value* to float, falling back to *default*. Never raises."""
    if isinstance(value, bool):  # bool is an int; treat it as "not a measurement"
        return default
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    if out != out or out in (float("inf"), float("-inf")):  # NaN / inf
        return default
    return out


def _merge(base, override):
    """Shallow-per-section merge so a partial config file only overrides what it sets."""
    merged = {section: dict(values) for section, values in base.items()}
    if not isinstance(override, dict):
        return merged
    for section, values in override.items():
        if section in merged and isinstance(values, dict):
            for key, value in values.items():
                if key in merged[section]:
                    merged[section][key] = _num(value, merged[section][key])
    return merged


def default_config_path():
    """Where the config lives: ORCH_RISK_CONFIG_PATH, else beside this module."""
    env = os.environ.get("ORCH_RISK_CONFIG_PATH")
    if env:
        return env
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), _DEFAULT_CONFIG_FILENAME)


def load_config(path=None):
    """Read the YAML config, merged over DEFAULT_CONFIG.

    Fail-soft by design: a missing file, unreadable file, bad YAML, or a PyYAML that
    is not installed all return the defaults with a diagnostic. A broad except that
    logs before it swallows is the documented convention here — a silent `pass` is
    the defect, not the catch.
    """
    path = path or default_config_path()
    try:
        import yaml  # imported lazily so the module works without PyYAML
    except ImportError:
        logger.warning("risk_assessment: PyYAML unavailable; using DEFAULT_CONFIG")
        return _merge(DEFAULT_CONFIG, {})
    try:
        with open(path, encoding="utf-8") as handle:
            loaded = yaml.safe_load(handle)
    except FileNotFoundError:
        logger.info("risk_assessment: no config at %s; using DEFAULT_CONFIG", path)
        return _merge(DEFAULT_CONFIG, {})
    except Exception as exc:  # noqa: BLE001 - logged, then degraded (fail-soft)
        logger.warning("risk_assessment: could not read %s (%s); using DEFAULT_CONFIG",
                       path, exc)
        return _merge(DEFAULT_CONFIG, {})
    return _merge(DEFAULT_CONFIG, loaded)


_config_lock = threading.Lock()
_config_cache = None


def get_config():
    """Module-level singleton accessor. Thread-safe; disk I/O happens once."""
    global _config_cache
    if _config_cache is None:
        with _config_lock:
            if _config_cache is None:
                _config_cache = load_config()
    return _config_cache


def invalidate_config():
    """Drop the cached config so the next get_config() re-reads from disk."""
    global _config_cache
    with _config_lock:
        _config_cache = None


# --------------------------------------------------------------------------- scoring


def _ratio(value, saturation):
    """value/saturation clamped to [0, 1]. A non-positive saturation means 'off'."""
    if saturation <= 0:
        return 0.0
    return max(0.0, min(1.0, value / saturation))


def component_scores(metrics, config=None):
    """Per-component risk points. Returns a dict keyed by _COMPONENTS.

    *metrics* is any mapping; unknown keys are ignored and missing keys read as 0,
    so a caller that only has diff stats still gets a usable score.
    """
    cfg = config or get_config()
    weights, sat = cfg["weights"], cfg["saturation"]
    if not isinstance(metrics, dict):
        logger.warning("risk_assessment: metrics is %s, expected a mapping",
                       type(metrics).__name__)
        metrics = {}

    files = max(0.0, _num(metrics.get("files_changed")))
    churn = max(0.0, _num(metrics.get("lines_added"))) + max(0.0, _num(metrics.get("lines_deleted")))
    # Only a DROP is risk. A coverage gain earns no credit either — this is a risk
    # score, not a quality score, and letting gains subtract would let a test-only
    # file mask a material change bundled into the same PR.
    coverage_drop = max(0.0, -_num(metrics.get("coverage_delta")))
    reverts = max(0.0, _num(metrics.get("contributor_reverts")))
    merges = max(0.0, _num(metrics.get("contributor_prior_merges")))
    material = max(0.0, _num(metrics.get("material_paths")))

    # A contributor with a long clean record is damped, but never to zero: the
    # reverts happened.
    trust_damping = 1.0 if merges <= 0 else max(0.4, 1.0 - min(0.6, merges / 50.0))

    return {
        "files_changed": weights["files_changed"] * _ratio(files, sat["files_changed"]),
        "lines_churn": weights["lines_churn"] * _ratio(churn, sat["lines_churn"]),
        "coverage_delta": weights["coverage_delta"] * _ratio(coverage_drop,
                                                             sat["coverage_drop_pct"]),
        "contributor_history": weights["contributor_history"] * trust_damping
        * _ratio(reverts, sat["contributor_reverts"]),
        "material_paths": weights["material_paths"] * _ratio(material,
                                                             sat["material_paths"]),
    }


def score_pull_request(metrics, config=None):
    """Numeric merge-risk score in [0, 100]. Higher is riskier. Never raises."""
    try:
        components = component_scores(metrics, config)
    except Exception as exc:  # noqa: BLE001 - logged, then degraded (fail-soft)
        logger.warning("risk_assessment: scoring failed (%s); returning 0.0", exc)
        return 0.0
    return round(max(0.0, min(100.0, sum(components.values()))), 2)


def classify(score, config=None):
    """Map a score onto a band. Unscoreable input reads as the safest band."""
    cfg = config or get_config()
    value = _num(score, 0.0)
    if value >= cfg["thresholds"]["high_risk_min"]:
        return "high"
    if value <= cfg["thresholds"]["low_risk_max"]:
        return "low"
    return "medium"


def assess(metrics, config=None):
    """One call for the merge train: score, band and the per-component breakdown.

    The breakdown is not decoration — when the train holds a PR, the operator needs
    to see WHICH signal held it, or the gate is unactionable.
    """
    cfg = config or get_config()
    components = {}
    try:
        components = component_scores(metrics, cfg)
    except Exception as exc:  # noqa: BLE001 - logged, then degraded (fail-soft)
        logger.warning("risk_assessment: assess failed (%s); reporting zero risk", exc)
    score = round(max(0.0, min(100.0, sum(components.values()))), 2)
    return {
        "score": score,
        "band": classify(score, cfg),
        "components": {name: round(components.get(name, 0.0), 2) for name in _COMPONENTS},
    }
