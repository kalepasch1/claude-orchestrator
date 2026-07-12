#!/usr/bin/env python3
"""
owner_preference.py — learn the OWNER's risk appetite from past approvals/rejections
and pre-weight committee aggregates toward decisions the owner would actually make.

Surfaces a "matches your past calls" signal so the committee output reflects
historical taste, not just abstract expert reasoning.

API:
  taste(card)       -> (likelihood, reason, matches_past)
  owner_bias()      -> dict profiling the owner's preferences
  reweight(votes)   -> normalized vote weights based on owner history
"""
import os, sys, math, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

# Configurable thresholds
TASTE_THRESHOLD = float(os.environ.get("TASTE_THRESHOLD", "0.6"))
MATCHES_THRESHOLD = float(os.environ.get("MATCHES_THRESHOLD", "0.7"))
MIN_HISTORY = int(os.environ.get("OWNER_MIN_HISTORY", "5"))


def _load_decisions():
    """Load past approval/rejection decisions from the approvals table."""
    try:
        rows = db.select("approvals", {
            "select": "id,kind,status,title,why,value,risk,detail",
            "status": "in.(approved,denied)",
            "order": "updated_at.desc",
            "limit": "500",
        }) or []
        return rows
    except Exception:
        return []


def _toks(text):
    """Simple word tokenizer — lowercase, alpha-only, length >= 3."""
    if not text:
        return []
    return [w.lower() for w in re.findall(r'[a-zA-Z]{3,}', str(text))]


def _kind_rates(decisions):
    """Compute per-kind approval rates with Laplace smoothing."""
    counts = {}  # kind -> [approved, total]
    for d in decisions:
        k = (d.get("kind") or "unknown").lower()
        if k not in counts:
            counts[k] = [0, 0]
        counts[k][1] += 1
        if d.get("status") == "approved":
            counts[k][0] += 1
    rates = {}
    for k, (approved, total) in counts.items():
        # Laplace smoothing: (approved + 1) / (total + 2)
        rates[k] = (approved + 1) / (total + 2)
    return rates


def _keyword_weights(decisions):
    """Log-odds keyword weighting: which words appear more in approved vs denied."""
    approved_toks, denied_toks = {}, {}
    for d in decisions:
        text = " ".join(filter(None, [d.get("title"), d.get("why"), d.get("value")]))
        tokens = _toks(text)
        bucket = approved_toks if d.get("status") == "approved" else denied_toks
        for t in tokens:
            bucket[t] = bucket.get(t, 0) + 1
    all_words = set(approved_toks) | set(denied_toks)
    weights = {}
    for w in all_words:
        a = approved_toks.get(w, 0) + 1  # Laplace
        d = denied_toks.get(w, 0) + 1
        weights[w] = math.log(a / d)
    return weights


def _classify_sentiment(text, dimension):
    """Simple sentiment classifier for value (high/med/low) and risk (high/med/low)."""
    t = (text or "").lower()
    if dimension == "value":
        if any(w in t for w in ("critical", "essential", "major", "significant", "high")):
            return "high"
        if any(w in t for w in ("minor", "small", "low", "marginal", "trivial")):
            return "low"
        return "medium"
    else:  # risk
        if any(w in t for w in ("breaking", "dangerous", "critical", "high", "severe")):
            return "high"
        if any(w in t for w in ("none", "minimal", "low", "safe", "trivial")):
            return "low"
        return "medium"


def taste(card):
    """Predict approval likelihood for a card based on owner's past decisions.

    Args:
        card: dict with keys like kind, title, why, value, risk

    Returns:
        (likelihood, reason, matches_past) where:
        - likelihood: float 0..1, predicted approval probability
        - reason: str explanation
        - matches_past: bool, True if this aligns with owner's historical pattern
    """
    decisions = _load_decisions()
    if len(decisions) < MIN_HISTORY:
        return (0.5, "insufficient history", False)

    kind = (card.get("kind") or "unknown").lower()
    kind_rates = _kind_rates(decisions)
    kw = _keyword_weights(decisions)

    # Base rate
    total_approved = sum(1 for d in decisions if d.get("status") == "approved")
    base_rate = (total_approved + 1) / (len(decisions) + 2)

    # Kind-specific rate (if enough data)
    kind_count = sum(1 for d in decisions if (d.get("kind") or "").lower() == kind)
    kind_rate = kind_rates.get(kind, base_rate) if kind_count >= MIN_HISTORY else base_rate

    # Keyword signal
    text = " ".join(filter(None, [card.get("title"), card.get("why"), card.get("value")]))
    tokens = _toks(text)
    kw_score = sum(kw.get(t, 0) for t in tokens) / max(1, len(tokens)) if tokens else 0

    # Value/risk sentiment
    val_sent = _classify_sentiment(card.get("value"), "value")
    risk_sent = _classify_sentiment(card.get("risk"), "risk")
    val_boost = {"high": 0.1, "medium": 0, "low": -0.05}.get(val_sent, 0)
    risk_penalty = {"high": -0.15, "medium": 0, "low": 0.05}.get(risk_sent, 0)

    # Combine signals: kind_rate (40%) + keyword (30%) + sentiment (30%)
    kw_prob = 1 / (1 + math.exp(-kw_score))  # sigmoid
    likelihood = 0.4 * kind_rate + 0.3 * kw_prob + 0.3 * (base_rate + val_boost + risk_penalty)
    likelihood = max(0.0, min(1.0, likelihood))

    matches_past = likelihood >= MATCHES_THRESHOLD

    # Build reason
    parts = [f"base={base_rate:.0%}"]
    if kind_count >= MIN_HISTORY:
        parts.append(f"{kind}={kind_rate:.0%}")
    if abs(kw_score) > 0.1:
        parts.append(f"keywords={'positive' if kw_score > 0 else 'negative'}")
    reason = "matches your past calls" if matches_past else f"predicted from history ({', '.join(parts)})"

    return (round(likelihood, 3), reason, matches_past)


def owner_bias():
    """Profile the owner's approval preferences from historical decisions.

    Returns dict with: base_rate, per_kind_rates, value_preference, risk_tolerance,
    top_approved_keywords, decision_count.
    """
    decisions = _load_decisions()
    if not decisions:
        return {"base_rate": 0.5, "per_kind_rates": {}, "value_preference": "unknown",
                "risk_tolerance": "unknown", "top_approved_keywords": [], "decision_count": 0}

    total_approved = sum(1 for d in decisions if d.get("status") == "approved")
    base_rate = (total_approved + 1) / (len(decisions) + 2)
    kind_rates = _kind_rates(decisions)

    # Value preference: does the owner favor high-value or accept low-value?
    approved = [d for d in decisions if d.get("status") == "approved"]
    val_sents = [_classify_sentiment(d.get("value"), "value") for d in approved]
    high_val = val_sents.count("high") / max(1, len(val_sents))
    value_preference = "high_value" if high_val > 0.5 else ("balanced" if high_val > 0.25 else "permissive")

    # Risk tolerance
    risk_sents = [_classify_sentiment(d.get("risk"), "risk") for d in approved]
    high_risk_approved = risk_sents.count("high") / max(1, len(risk_sents))
    risk_tolerance = "risk_tolerant" if high_risk_approved > 0.3 else (
        "risk_averse" if high_risk_approved < 0.1 else "moderate")

    # Top keywords in approved items
    kw = _keyword_weights(decisions)
    top_kw = sorted(kw.items(), key=lambda x: -x[1])[:10]

    return {
        "base_rate": round(base_rate, 3),
        "per_kind_rates": {k: round(v, 3) for k, v in kind_rates.items()},
        "value_preference": value_preference,
        "risk_tolerance": risk_tolerance,
        "top_approved_keywords": [w for w, _ in top_kw],
        "decision_count": len(decisions),
    }


def reweight(votes):
    """Normalize committee vote weights based on owner's historical patterns.

    Args:
        votes: list of dicts with at least {verdict, kind, score, conviction}

    Returns:
        list of votes with added 'owner_weight' field (0..2 multiplier)
    """
    decisions = _load_decisions()
    if len(decisions) < MIN_HISTORY:
        for v in votes:
            v["owner_weight"] = 1.0
        return votes

    kind_rates = _kind_rates(decisions)
    base_approved = sum(1 for d in decisions if d.get("status") == "approved")
    base_rate = (base_approved + 1) / (len(decisions) + 2)

    for v in votes:
        kind = (v.get("kind") or "unknown").lower()
        kr = kind_rates.get(kind, base_rate)
        verdict = (v.get("verdict") or "").lower()
        # If owner historically approves this kind AND the vote supports, boost weight
        if verdict in ("support", "go") and kr > 0.6:
            v["owner_weight"] = 1.0 + min(1.0, (kr - 0.5) * 2)
        elif verdict in ("oppose", "hold") and kr < 0.4:
            v["owner_weight"] = 1.0 + min(1.0, (0.5 - kr) * 2)
        else:
            v["owner_weight"] = 1.0
    return votes


if __name__ == "__main__":
    import json
    print("Owner bias:", json.dumps(owner_bias(), indent=2))
    sample = {"kind": "material", "title": "Add new feature", "value": "high", "risk": "low"}
    lk, reason, matches = taste(sample)
    print(f"Taste: likelihood={lk}, reason={reason}, matches_past={matches}")
