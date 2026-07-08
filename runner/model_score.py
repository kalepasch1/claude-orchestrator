"""
model_score.py — model router scoring by $/merged-diff.

Routes tasks to models based on LIVE OUTCOME DATA, not static capability ratings.
Tracks per vendor/model: tokens, latency, tests_passed, merged, deployed,
review_failures, rollback_risk. Forces canaries until providers have enough evidence.

Score = cost_per_merged_diff (lower is better)
       with Bayesian smoothing so new models get a fair trial.
"""
import os, sys, json, math, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

MIN_SAMPLES = int(os.environ.get("ORCH_MODEL_MIN_SAMPLES", "10"))
CANARY_FRACTION = float(os.environ.get("ORCH_MODEL_CANARY_FRACTION", "0.15"))
SCORE_TABLE = "model_scores"


def run():
    """Compute and store model scores from outcome data."""
    scores = compute_scores()

    # Write scores to controls for the router to consume
    try:
        db.insert("controls", {
            "key": "model_scores",
            "value": json.dumps(scores),
            "updated_at": "now()"
        }, upsert=True)
    except Exception as e:
        print(f"[model_score] write failed: {e}")

    # Log summary
    for name, s in sorted(scores.items(), key=lambda x: x[1].get("score", 999)):
        print(f"[model_score] {name}: $/merge={s['score']:.4f} "
              f"merged={s['merged']}/{s['total']} "
              f"avg_cost=${s['avg_cost']:.4f} "
              f"needs_canary={s.get('needs_canary', False)}")

    return scores


def compute_scores():
    """Compute $/merged-diff score for each model."""
    outcomes = db.select("outcomes", {
        "select": "model,tests_passed,integrated,usd,wall_ms,review_failures,input_tokens,output_tokens",
        "order": "created_at.desc",
        "limit": "5000"
    }) or []

    # Group by normalized model name
    groups = {}
    for o in outcomes:
        model = _normalize_model(o.get("model", ""))
        if not model:
            continue
        if model not in groups:
            groups[model] = {
                "total": 0, "tests_passed": 0, "merged": 0,
                "total_cost": 0.0, "total_wall_ms": 0,
                "review_failures": 0, "total_tokens": 0
            }
        g = groups[model]
        g["total"] += 1
        if o.get("tests_passed"):
            g["tests_passed"] += 1
        if o.get("integrated"):
            g["merged"] += 1
        g["total_cost"] += float(o.get("usd") or 0)
        g["total_wall_ms"] += int(o.get("wall_ms") or 0)
        g["review_failures"] += int(o.get("review_failures") or 0)
        g["total_tokens"] += int(o.get("input_tokens") or 0) + int(o.get("output_tokens") or 0)

    scores = {}
    for model, g in groups.items():
        total = g["total"]
        merged = g["merged"]
        avg_cost = g["total_cost"] / max(1, total)
        avg_wall_min = (g["total_wall_ms"] / max(1, total)) / 60000
        merge_rate = merged / max(1, total)

        # $/merged-diff with Bayesian smoothing
        # Prior: assume a model merges at 30% rate with $0.10/attempt cost
        prior_merged = 3
        prior_cost = 1.0

        smoothed_merged = merged + prior_merged
        smoothed_cost = g["total_cost"] + prior_cost
        smoothed_total = total + prior_merged / 0.3

        cost_per_merge = smoothed_cost / max(1, smoothed_merged)

        # Penalty for review failures (proxy for quality)
        review_fail_rate = g["review_failures"] / max(1, total)
        quality_penalty = 1.0 + review_fail_rate

        # Final score (lower is better)
        score = cost_per_merge * quality_penalty

        scores[model] = {
            "score": round(score, 6),
            "total": total,
            "tests_passed": g["tests_passed"],
            "merged": merged,
            "merge_rate": round(merge_rate, 4),
            "avg_cost": round(avg_cost, 6),
            "avg_wall_min": round(avg_wall_min, 2),
            "review_fail_rate": round(review_fail_rate, 4),
            "total_tokens": g["total_tokens"],
            "needs_canary": total < MIN_SAMPLES,
            "cost_per_merge": round(cost_per_merge, 4),
        }

    return scores


def best_model(kind="build", exclude=None):
    """Return the best model for a given task kind based on live scores."""
    try:
        rows = db.select("controls", {"select": "value", "key": "eq.model_scores", "limit": "1"})
        if not rows:
            return None
        scores = json.loads(rows[0].get("value", "{}"))
    except Exception:
        return None

    exclude = set(exclude or [])
    candidates = [(s["score"], name) for name, s in scores.items()
                  if name not in exclude and not s.get("needs_canary")]

    if not candidates:
        return None

    candidates.sort()
    return candidates[0][1]


def needs_canary():
    """Return models that need more samples (for forced canary scheduling)."""
    try:
        rows = db.select("controls", {"select": "value", "key": "eq.model_scores", "limit": "1"})
        if not rows:
            return []
        scores = json.loads(rows[0].get("value", "{}"))
        return [name for name, s in scores.items() if s.get("needs_canary")]
    except Exception:
        return []


def _normalize_model(model):
    """Normalize model names for consistent grouping."""
    m = str(model or "").lower().strip()
    if not m:
        return ""
    # Group by vendor:model
    if ":" in m:
        return m
    # Known Claude models
    if "opus" in m:
        return "claude:opus"
    if "sonnet" in m:
        return "claude:sonnet"
    if "haiku" in m:
        return "claude:haiku"
    # Known vendors
    for prefix in ("deepseek", "gemini", "gpt", "ollama", "codex"):
        if prefix in m:
            return m
    return m


if __name__ == "__main__":
    result = run()
    print(json.dumps(result, indent=2))
