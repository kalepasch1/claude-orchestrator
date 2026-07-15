#!/usr/bin/env python3
"""
dynamic_tier_marginal_quality.py — Measure the quality DELTA expensive models
(Opus) give over cheap ones (Haiku) per task-shape, and only pay for Opus
where the delta is real.

Approach:
  1. Track judge scores by (task_kind, model) pairs from historical tasks
  2. Compute marginal quality gain: Opus_score - Haiku_score per kind
  3. If the delta is below a threshold, route to Haiku (save cost)
  4. Continuously update as new judge results arrive

Feeds into model_policy.py's choose() function.
"""
import os, sys, json, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

MIN_SAMPLES = int(os.environ.get("ORCH_MARGINAL_MIN_SAMPLES", "5"))
DELTA_THRESHOLD = float(os.environ.get("ORCH_MARGINAL_DELTA_THRESHOLD", "0.15"))
ENABLED = os.environ.get("ORCH_DYNAMIC_TIER", "true").lower() in ("1", "true", "yes")

# Model tier mapping
TIER_MAP = {
    "claude-opus-4-8": "expensive",
    "claude-sonnet-4-6": "mid",
    "claude-haiku-4-5-20251001": "cheap",
}


def _safe_query(query, default=None):
    try:
        return db.sql(query) or (default if default is not None else [])
    except Exception:
        return default if default is not None else []


def collect_quality_data(days=30):
    """Collect judge scores grouped by (task_kind, model_tier).

    Returns {kind: {"expensive": [scores], "mid": [scores], "cheap": [scores]}}
    """
    rows = _safe_query(
        f"SELECT t.kind, t.metadata->>'model' AS model, "
        f"t.metadata->>'judge_score' AS score "
        f"FROM tasks t "
        f"WHERE t.state IN ('DONE','MERGED') "
        f"AND t.metadata->>'judge_score' IS NOT NULL "
        f"AND t.updated_at > now() - interval '{days} days'", [])

    data = {}
    for r in rows:
        kind = r.get("kind", "unknown")
        model = r.get("model", "")
        try:
            score = float(r.get("score", 0))
        except (ValueError, TypeError):
            continue

        tier = "unknown"
        for model_name, t in TIER_MAP.items():
            if model_name in model:
                tier = t
                break
        if tier == "unknown":
            if "opus" in model.lower():
                tier = "expensive"
            elif "sonnet" in model.lower():
                tier = "mid"
            elif "haiku" in model.lower():
                tier = "cheap"
            else:
                continue

        data.setdefault(kind, {"expensive": [], "mid": [], "cheap": []})
        data[kind].setdefault(tier, []).append(score)

    return data


def compute_marginal_deltas(quality_data=None):
    """Compute the marginal quality gain of expensive over cheap per task kind.

    Returns {kind: {"delta": float, "expensive_avg": float, "cheap_avg": float,
                     "samples": int, "worth_it": bool}}
    """
    if quality_data is None:
        quality_data = collect_quality_data()

    results = {}
    for kind, tiers in quality_data.items():
        expensive_scores = tiers.get("expensive", [])
        cheap_scores = tiers.get("cheap", [])

        if len(expensive_scores) < MIN_SAMPLES or len(cheap_scores) < MIN_SAMPLES:
            results[kind] = {
                "delta": None, "expensive_avg": None, "cheap_avg": None,
                "samples": len(expensive_scores) + len(cheap_scores),
                "worth_it": True,  # default to expensive when insufficient data
                "reason": "insufficient samples",
            }
            continue

        exp_avg = sum(expensive_scores) / len(expensive_scores)
        cheap_avg = sum(cheap_scores) / len(cheap_scores)
        delta = exp_avg - cheap_avg

        results[kind] = {
            "delta": round(delta, 3),
            "expensive_avg": round(exp_avg, 3),
            "cheap_avg": round(cheap_avg, 3),
            "samples": len(expensive_scores) + len(cheap_scores),
            "worth_it": delta >= DELTA_THRESHOLD,
            "reason": f"delta={delta:.3f} {'>=' if delta >= DELTA_THRESHOLD else '<'} threshold={DELTA_THRESHOLD}",
        }

    return results


def recommend_tier(task_kind, deltas=None):
    """Recommend cheap or expensive tier for a given task kind.

    Returns {"tier": "cheap"|"expensive", "reason": str, "confidence": float}
    """
    if not ENABLED:
        return {"tier": "expensive", "reason": "dynamic tier disabled", "confidence": 0.0}

    if deltas is None:
        deltas = compute_marginal_deltas()

    info = deltas.get(task_kind)
    if not info:
        return {"tier": "expensive", "reason": f"no data for kind={task_kind}",
                "confidence": 0.0}

    if info.get("delta") is None:
        return {"tier": "expensive", "reason": info.get("reason", "insufficient data"),
                "confidence": 0.0}

    if info["worth_it"]:
        confidence = min(info["samples"] / 50, 1.0)
        return {"tier": "expensive",
                "reason": f"opus adds {info['delta']:.1%} quality for {task_kind}",
                "confidence": round(confidence, 2)}
    else:
        confidence = min(info["samples"] / 50, 1.0)
        return {"tier": "cheap",
                "reason": f"opus only adds {info['delta']:.1%} for {task_kind}, below threshold",
                "confidence": round(confidence, 2)}


def update_policy_cache():
    """Recompute deltas and write a cache file for model_policy to consume."""
    deltas = compute_marginal_deltas()
    cache = {
        "computed_at": datetime.datetime.utcnow().isoformat() + "Z",
        "deltas": deltas,
        "recommendations": {kind: recommend_tier(kind, deltas) for kind in deltas},
    }

    cache_dir = os.environ.get("CLAUDE_ORCH_HOME", os.path.expanduser("~/.claude-orchestrator"))
    cache_path = os.path.join(cache_dir, "marginal_quality_cache.json")
    try:
        os.makedirs(cache_dir, exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2)
        return cache_path
    except Exception:
        return ""


def summary():
    """Human-readable summary of marginal quality analysis."""
    deltas = compute_marginal_deltas()
    lines = ["Marginal Quality Analysis (Opus vs Haiku by task kind):"]
    for kind, info in sorted(deltas.items()):
        if info.get("delta") is not None:
            verdict = "WORTH IT" if info["worth_it"] else "USE CHEAP"
            lines.append(f"  {kind}: delta={info['delta']:.3f} "
                         f"(opus={info['expensive_avg']:.3f}, haiku={info['cheap_avg']:.3f}) "
                         f"-> {verdict} (n={info['samples']})")
        else:
            lines.append(f"  {kind}: {info.get('reason', 'no data')} (n={info['samples']})")
    return "\n".join(lines)
