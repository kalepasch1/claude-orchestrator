#!/usr/bin/env python3
"""filing_optimizer_calibration.py — a calibrated, explainable optimizer, or an honest fallback.

WHAT THE ROUND 8 AUDIT FOUND
----------------------------
`runner/filing_optimizer_v2.py` is 27 lines of hardcoded arithmetic:

    amendment_risk = 0.08 + prior_amendments * 0.16 + (1 - evidence_completeness) * 0.5
    estimated_volume_discount = (len(filings) - len(groups)) * 0.02

Nobody fitted 0.08, 0.16, 0.5 or 0.02 to anything. The last of those is the worst of the
four: `estimated_volume_discount` is a SAVINGS CLAIM presented in the output of a function
that has never observed a single price. This module replaces the estimate with one trained
from approved historical outcomes — and, crucially, refuses to when the data cannot carry it.

PRIOR ART: `filing_optimizer_v2.SmartFilingOptimizer` is KEPT and is the declared fallback.
It is not deleted, because a heuristic that is honestly labelled a heuristic is strictly
better than a model fitted on nine samples. `recommend()` returns `method='heuristic'` and
says why whenever the calibration gate is not met.

DESIGN COMMITMENTS
  1. FEATURES CARRY PROVENANCE. Every feature value records which historical outcomes
     produced it and how many. A coefficient whose provenance is empty is reported, not
     silently used.
  2. VALIDATION SPLIT, deterministically seeded on the outcome ids — a split that moves
     between runs makes "the model got better" unfalsifiable.
  3. THE CALIBRATION GATE. The model ships only if it beats the incumbent heuristic on the
     HELD-OUT split by a margin, on Brier score. Not on training loss, and not on "the
     numbers look reasonable".
  4. NO SAVINGS CLAIM UNLESS MEASURED. `savings_usd` is None unless realised cost deltas
     are supplied. This is the direct fix for `estimated_volume_discount`.
  5. REPRODUCIBLE. Same inputs -> byte-identical recommendations. No clock, no RNG that is
     not seeded, deterministic tie-breaks.

Pure Python, no external dependencies (numpy and sklearn are not installed on the fleet;
a module that cannot import is a module that never runs).

Fail-soft per CLAUDE.md: every public entry point degrades to the heuristic rather than
raising, because a filing queue that stops moving is worse than one ordered by heuristic.
"""
from __future__ import annotations

import hashlib
import math
import os
from datetime import date

try:
    from filing_optimizer_v2 import SmartFilingOptimizer
except Exception:  # pragma: no cover - import shape differs under some test runners
    from runner.filing_optimizer_v2 import SmartFilingOptimizer  # type: ignore


# ─── Configuration (ORCH_-prefixed, fleet-pushable) ─────────────────────────

def _int_env(name, default):
    try:
        return int(os.environ.get(name, str(default)))
    except Exception:
        return default


def _float_env(name, default):
    try:
        return float(os.environ.get(name, str(default)))
    except Exception:
        return default


def min_training_samples():
    """Below this the model is not fitted at all. A curve through nine points is decoration."""
    return _int_env("ORCH_FILING_MIN_SAMPLES", 60)


def required_brier_margin():
    """How much better than the incumbent heuristic the model must be on held-out data."""
    return _float_env("ORCH_FILING_BRIER_MARGIN", 0.01)


def validation_fraction():
    return _float_env("ORCH_FILING_VALIDATION_FRACTION", 0.3)


# ─── 1. Features with provenance ────────────────────────────────────────────

FEATURES = (
    "prior_amendments",
    "evidence_incompleteness",
    "days_to_deadline_inv",
    "jurisdiction_amendment_rate",
    "type_amendment_rate",
)

FEATURE_MEANING = {
    "prior_amendments": "how many times this filing has already been amended",
    "evidence_incompleteness": "1 - evidence_completeness at submission",
    "days_to_deadline_inv": "urgency: 1/(1+days to deadline), so a nearer deadline scores higher",
    "jurisdiction_amendment_rate": "observed amendment rate for this jurisdiction",
    "type_amendment_rate": "observed amendment rate for this filing type",
}


def _rate_table(outcomes, key):
    """Observed amendment rate per key, WITH the ids that produced it."""
    agg = {}
    for o in outcomes:
        k = str(o.get(key, "unknown"))
        entry = agg.setdefault(k, {"n": 0, "amended": 0, "ids": []})
        entry["n"] += 1
        entry["amended"] += 1 if o.get("amended") else 0
        oid = o.get("id")
        if oid is not None:
            entry["ids"].append(str(oid))
    return {k: {"rate": (v["amended"] / v["n"]) if v["n"] else 0.0,
                "n": v["n"], "ids": sorted(v["ids"])}
            for k, v in agg.items()}


def build_feature_store(outcomes):
    """Feature tables plus the provenance of every value.

    `global_rate` is the fallback for an unseen jurisdiction or type and is recorded with
    its own provenance so an unseen key never looks like a measured one.
    """
    outcomes = [o for o in (outcomes or []) if isinstance(o, dict)]
    total = len(outcomes)
    amended = sum(1 for o in outcomes if o.get("amended"))
    return {
        "jurisdiction": _rate_table(outcomes, "jurisdiction"),
        "type": _rate_table(outcomes, "type"),
        "global_rate": (amended / total) if total else 0.0,
        "provenance": {
            "source": "approved_historical_filing_outcomes",
            "sample_size": total,
            "amended": amended,
            "outcome_ids": sorted(str(o.get("id")) for o in outcomes if o.get("id") is not None),
        },
    }


def extract_features(filing, store, today=None):
    """Feature vector for one filing, each value tagged with where it came from."""
    today = today or date(2026, 1, 1)  # explicit default: no hidden clock dependency
    store = store or {}

    try:
        deadline = date.fromisoformat(str(filing.get("deadline"))) if filing.get("deadline") else None
        days = (deadline - today).days if deadline else 999
    except Exception:
        days = 999

    j_key = str(filing.get("jurisdiction", "unknown"))
    t_key = str(filing.get("type", "general"))
    j = (store.get("jurisdiction") or {}).get(j_key)
    t = (store.get("type") or {}).get(t_key)
    fallback = float(store.get("global_rate", 0.0))

    values = {
        "prior_amendments": float(filing.get("prior_amendments", 0) or 0),
        "evidence_incompleteness": max(0.0, 1.0 - float(filing.get("evidence_completeness", 1) or 0)),
        "days_to_deadline_inv": 1.0 / (1.0 + max(0, days)),
        "jurisdiction_amendment_rate": j["rate"] if j else fallback,
        "type_amendment_rate": t["rate"] if t else fallback,
    }
    provenance = {
        "prior_amendments": {"source": "filing", "n": 1, "ids": []},
        "evidence_incompleteness": {"source": "filing", "n": 1, "ids": []},
        "days_to_deadline_inv": {"source": "filing", "n": 1, "ids": []},
        "jurisdiction_amendment_rate": ({"source": "history", "n": j["n"], "ids": j["ids"]} if j
                                        else {"source": "global_fallback", "n": 0, "ids": []}),
        "type_amendment_rate": ({"source": "history", "n": t["n"], "ids": t["ids"]} if t
                                else {"source": "global_fallback", "n": 0, "ids": []}),
    }
    return values, provenance


# ─── 2. Deterministic validation split ──────────────────────────────────────

def split_outcomes(outcomes, fraction=None):
    """Deterministic hash split on the outcome id.

    Hashing the id rather than shuffling means the same outcome always lands on the same
    side, so a metric change between runs is a change in the MODEL, not in the split.
    """
    fraction = validation_fraction() if fraction is None else fraction
    train, validate = [], []
    for o in outcomes or []:
        key = str(o.get("id", "")) or repr(sorted(o.items()))
        bucket = int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:8], 16) % 1000
        (validate if bucket < fraction * 1000 else train).append(o)
    return train, validate


# ─── 3. The model ───────────────────────────────────────────────────────────

def _sigmoid(z):
    if z < -60:
        return 0.0
    if z > 60:
        return 1.0
    return 1.0 / (1.0 + math.exp(-z))


def fit_logistic(rows, labels, epochs=400, lr=0.3, l2=1e-3):
    """Plain gradient descent. Deterministic: zero init, fixed epochs, no shuffling."""
    weights = {f: 0.0 for f in FEATURES}
    bias = 0.0
    n = len(rows)
    if n == 0:
        return weights, bias
    for _ in range(epochs):
        gw = {f: 0.0 for f in FEATURES}
        gb = 0.0
        for row, y in zip(rows, labels):
            z = bias + sum(weights[f] * row.get(f, 0.0) for f in FEATURES)
            err = _sigmoid(z) - (1.0 if y else 0.0)
            for f in FEATURES:
                gw[f] += err * row.get(f, 0.0)
            gb += err
        for f in FEATURES:
            weights[f] -= lr * (gw[f] / n + l2 * weights[f])
        bias -= lr * (gb / n)
    return weights, bias


def predict(weights, bias, row):
    return _sigmoid(bias + sum(weights.get(f, 0.0) * row.get(f, 0.0) for f in FEATURES))


def brier(predictions, labels):
    if not predictions:
        return 1.0
    return sum((p - (1.0 if y else 0.0)) ** 2 for p, y in zip(predictions, labels)) / len(predictions)


def heuristic_risk(filing):
    """The incumbent, extracted verbatim from filing_optimizer_v2 so it is the real baseline."""
    history = int(filing.get("prior_amendments", 0) or 0)
    completeness = float(filing.get("evidence_completeness", 1) or 0)
    return round(min(1.0, 0.08 + history * 0.16 + (1 - completeness) * 0.5), 3)


# ─── 4. The calibration gate ────────────────────────────────────────────────

def train(outcomes, today=None):
    """Fit and evaluate. Returns a model dict whose `calibrated` flag is the gate.

    The gate is deliberately hostile: too few samples, no positives, no negatives, or a
    held-out Brier score that does not beat the incumbent heuristic by the margin, and the
    model does NOT ship. Each refusal names itself.
    """
    outcomes = [o for o in (outcomes or []) if isinstance(o, dict)]
    reasons = []

    if len(outcomes) < min_training_samples():
        reasons.append("only %d approved outcome(s); the floor is %d. A curve through this "
                       "many points is decoration, not calibration."
                       % (len(outcomes), min_training_samples()))

    labels_all = [1 if o.get("amended") else 0 for o in outcomes]
    if outcomes and (sum(labels_all) == 0 or sum(labels_all) == len(labels_all)):
        reasons.append("the outcome set is single-class (%d/%d amended); a model fitted on it "
                       "predicts a constant." % (sum(labels_all), len(labels_all)))

    store = build_feature_store(outcomes)
    if reasons:
        return {"calibrated": False, "reasons": reasons, "store": store,
                "weights": None, "bias": None, "metrics": {}, "sample_size": len(outcomes)}

    train_rows, validate_rows = split_outcomes(outcomes)
    if not train_rows or not validate_rows:
        return {"calibrated": False,
                "reasons": ["the deterministic split left one side empty; cannot validate"],
                "store": store, "weights": None, "bias": None, "metrics": {},
                "sample_size": len(outcomes)}

    # The store is built from the TRAINING half only. Building it from everything leaks the
    # validation labels into the jurisdiction/type rate features and inflates the score.
    train_store = build_feature_store(train_rows)

    X = [extract_features(o, train_store, today)[0] for o in train_rows]
    y = [1 if o.get("amended") else 0 for o in train_rows]
    weights, bias = fit_logistic(X, y)

    Xv = [extract_features(o, train_store, today)[0] for o in validate_rows]
    yv = [1 if o.get("amended") else 0 for o in validate_rows]
    model_brier = brier([predict(weights, bias, r) for r in Xv], yv)
    heuristic_brier = brier([heuristic_risk(o) for o in validate_rows], yv)
    improvement = heuristic_brier - model_brier

    calibrated = improvement >= required_brier_margin()
    if not calibrated:
        reasons.append("held-out Brier %.4f vs heuristic %.4f (improvement %.4f) does not meet "
                       "the %.4f margin. The incumbent heuristic is not beaten, so it stays."
                       % (model_brier, heuristic_brier, improvement, required_brier_margin()))

    return {
        "calibrated": calibrated,
        "reasons": reasons,
        "store": train_store,
        "weights": weights,
        "bias": bias,
        "metrics": {
            "model_brier": round(model_brier, 6),
            "heuristic_brier": round(heuristic_brier, 6),
            "improvement": round(improvement, 6),
            "train_n": len(train_rows),
            "validate_n": len(validate_rows),
        },
        "sample_size": len(outcomes),
    }


# ─── 5. Explainable recommendations ─────────────────────────────────────────

def explain(model, filing, today=None):
    """Per-feature contribution to the predicted risk. Sorted, so it is reproducible."""
    values, provenance = extract_features(filing, model.get("store"), today)
    weights = model.get("weights") or {}
    contributions = [
        {"feature": f,
         "value": round(values.get(f, 0.0), 6),
         "weight": round(weights.get(f, 0.0), 6),
         "contribution": round(weights.get(f, 0.0) * values.get(f, 0.0), 6),
         "meaning": FEATURE_MEANING[f],
         "provenance": provenance.get(f)}
        for f in FEATURES
    ]
    contributions.sort(key=lambda c: (-abs(c["contribution"]), c["feature"]))
    return contributions


def recommend(filings, outcomes=None, model=None, today=None, realised_costs=None):
    """Ordered, explained filing recommendations.

    `method` is either 'calibrated_model' or 'heuristic', and the caller is told which and
    why. Falling back silently is what let a heuristic be described as an optimizer for
    eight rounds.
    """
    filings = [dict(f) for f in (filings or []) if isinstance(f, dict)]
    try:
        model = model or train(outcomes or [], today=today)
    except Exception as exc:
        model = {"calibrated": False, "reasons": ["training errored: %s" % exc],
                 "store": {}, "weights": None, "bias": None, "metrics": {}, "sample_size": 0}

    calibrated = bool(model.get("calibrated"))
    rows = []
    for f in filings:
        if calibrated:
            values, _ = extract_features(f, model.get("store"), today)
            risk = predict(model["weights"], model["bias"], values)
            contributions = explain(model, f, today)
        else:
            risk = heuristic_risk(f)
            contributions = [{"feature": "heuristic",
                              "value": risk,
                              "weight": 1.0,
                              "contribution": risk,
                              "meaning": "filing_optimizer_v2 hardcoded coefficients; NOT fitted to data",
                              "provenance": {"source": "hardcoded", "n": 0, "ids": []}}]
        rows.append({
            "id": f.get("id"),
            "jurisdiction": f.get("jurisdiction", "unknown"),
            "type": f.get("type", "general"),
            "deadline": f.get("deadline"),
            "amendment_risk": round(risk, 6),
            "batch_key": "%s:%s" % (f.get("jurisdiction", "unknown"), f.get("type", "general")),
            "explanation": contributions,
        })

    # Deadline first, then risk, then id — a total order, so the output is reproducible.
    rows.sort(key=lambda r: (str(r.get("deadline") or "9999-12-31"),
                             -r["amendment_risk"],
                             str(r.get("id") or "")))

    return {
        "method": "calibrated_model" if calibrated else "heuristic",
        "calibrated": calibrated,
        "fallback_reasons": [] if calibrated else list(model.get("reasons") or []),
        "metrics": model.get("metrics", {}),
        "sample_size": model.get("sample_size", 0),
        "provenance": (model.get("store") or {}).get("provenance", {}),
        "filings": rows,
        "savings": measured_savings(realised_costs),
    }


# ─── 6. No savings claim unless measured ────────────────────────────────────

def measured_savings(realised_costs):
    """Savings, or None. There is no third option.

    This replaces `estimated_volume_discount = (n - groups) * 0.02`, which asserted a
    percentage saving from a function that had never observed a price. `realised_costs` is
    a list of {'baseline_usd', 'actual_usd'} from filings that ACTUALLY SHIPPED.
    """
    rows = [r for r in (realised_costs or []) if isinstance(r, dict)]
    if not rows:
        return {"measured": False, "savings_usd": None, "n": 0,
                "note": "no realised costs supplied; no savings are claimed. An estimated "
                        "discount from an unpriced batch is a number, not a saving."}
    try:
        baseline = sum(float(r.get("baseline_usd", 0) or 0) for r in rows)
        actual = sum(float(r.get("actual_usd", 0) or 0) for r in rows)
    except Exception:
        return {"measured": False, "savings_usd": None, "n": 0,
                "note": "realised costs were unparseable; no savings are claimed"}
    return {"measured": True, "savings_usd": round(baseline - actual, 2), "n": len(rows),
            "baseline_usd": round(baseline, 2), "actual_usd": round(actual, 2),
            "note": "measured against %d realised filing(s)" % len(rows)}


# ─── 7. Evidence trail and approval workflow ────────────────────────────────

def evidence_record(result, task_id=None):
    """What gets written to the evidence trail. Carries the refusal, not just the result."""
    return {
        "kind": "filing_optimizer_recommendation",
        "task_id": task_id,
        "method": result.get("method"),
        "calibrated": result.get("calibrated"),
        "fallback_reasons": result.get("fallback_reasons", []),
        "metrics": result.get("metrics", {}),
        "sample_size": result.get("sample_size", 0),
        "training_provenance": result.get("provenance", {}),
        "filing_count": len(result.get("filings", [])),
        "savings": result.get("savings", {}),
        # A recommendation nobody can reproduce is not evidence.
        "reproducible": True,
        "digest": recommendation_digest(result),
    }


def recommendation_digest(result):
    """Stable digest of the ordering and risks. Same inputs -> same digest."""
    try:
        payload = "|".join(
            "%s:%s:%s" % (r.get("id"), r.get("deadline"), r.get("amendment_risk"))
            for r in result.get("filings", []))
        return hashlib.sha256(("%s|%s" % (result.get("method"), payload)).encode("utf-8")).hexdigest()[:16]
    except Exception:
        return ""


def approval_requirement(result):
    """What the approval workflow must ask a human for.

    An UNCALIBRATED recommendation always requires approval: the whole point of shipping
    the fallback honestly is that nobody auto-applies it believing it was fitted.
    """
    if not result.get("calibrated"):
        return {
            "requires_approval": True,
            "tier": "human",
            "reason": "recommendation came from the uncalibrated heuristic fallback: %s"
                      % ("; ".join(result.get("fallback_reasons") or ["no reason recorded"])),
        }
    improvement = (result.get("metrics") or {}).get("improvement", 0)
    return {
        "requires_approval": True,
        "tier": "review",
        "reason": "calibrated model beat the heuristic by %.4f Brier on held-out data over "
                  "%d sample(s); review before applying."
                  % (improvement, result.get("sample_size", 0)),
    }


# ─── Compatibility with the incumbent ───────────────────────────────────────

def optimize(filings, outcomes=None, today=None, realised_costs=None):
    """Drop-in superset of SmartFilingOptimizer.optimize, with the estimate removed.

    Deliberately does NOT emit `estimated_volume_discount`. Callers reading that key get
    `savings` instead, which is None until something is measured.
    """
    result = recommend(filings, outcomes=outcomes, today=today, realised_costs=realised_costs)
    batch_keys = {r["batch_key"] for r in result["filings"]}
    result["batch_count"] = len(batch_keys)
    return result


def heuristic_baseline(filings, today=None):
    """The untouched incumbent, for side-by-side comparison. Never deleted."""
    try:
        return SmartFilingOptimizer().optimize(list(filings or []), today=today)
    except Exception as exc:
        return {"filings": [], "batch_count": 0, "error": str(exc)}
