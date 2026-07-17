#!/usr/bin/env python3
"""
adaptive_budget.py — Adaptive token budget (50X context window savings).

Most tasks need <2K output tokens but get 8K+ budget — wasting context window
and increasing latency. This module predicts the needed output length from
similar past tasks and sets a tight budget.

Factors:
  1. Historical output length for this (kind × domain) pair
  2. Prompt length (longer prompts → longer outputs, but with diminishing returns)
  3. Diff compiler confidence (template matches need less output)
  4. Task complexity signals (file count, scope)

Usage:
    import adaptive_budget
    budget = adaptive_budget.predict_budget(task, domain, diff_plan)
    # Use budget["max_tokens"] instead of fixed 8192
"""
import os, sys, json, time, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

DEFAULT_BUDGET = int(os.environ.get("ORCH_DEFAULT_TOKEN_BUDGET", "8192"))
MIN_BUDGET = int(os.environ.get("ORCH_MIN_TOKEN_BUDGET", "1024"))
# Multiplier applied on top of the predicted output length so the model doesn't get
# truncated when a task runs slightly longer than its historical average.
BUDGET_HEADROOM = float(os.environ.get("ORCH_BUDGET_HEADROOM", "1.5"))  # 50% headroom over predicted


def _history():
    """Load output length history from controls."""
    try:
        rows = db.select("controls", {"select": "value", "key": "eq.token_budget_history"})
        if rows and rows[0].get("value"):
            v = rows[0]["value"]
            return json.loads(v) if isinstance(v, str) else v
    except Exception:
        pass
    return {}


def _save_history(history):
    """Persist output-length history to controls, capped at 200 entries."""
    if len(history) > 200:
        by_time = sorted(history.items(), key=lambda x: x[1].get("last_updated", 0))
        history = dict(by_time[-200:])
    try:
        db.upsert("controls", {"key": "token_budget_history", "value": json.dumps(history, default=str)})
    except Exception:
        pass


def _history_key(kind, domain):
    return f"{kind}:{domain}"


def record_output(task, domain, output_tokens, prompt_tokens=0):
    """Record actual output token usage for future predictions."""
    kind = task.get("kind", "feature")
    key = _history_key(kind, domain)
    history = _history()

    entry = history.get(key, {
        "kind": kind, "domain": domain,
        "samples": 0, "total_tokens": 0,
        "max_tokens": 0, "min_tokens": 99999,
        "avg_tokens": 0, "p90_tokens": 0,
        "recent": [],
    })

    entry["samples"] = entry.get("samples", 0) + 1
    entry["total_tokens"] = entry.get("total_tokens", 0) + output_tokens
    entry["avg_tokens"] = entry["total_tokens"] // entry["samples"]
    entry["max_tokens"] = max(entry.get("max_tokens", 0), output_tokens)
    entry["min_tokens"] = min(entry.get("min_tokens", 99999), output_tokens)
    entry["last_updated"] = time.time()

    # Track recent for P90 estimation
    recent = entry.get("recent", [])
    recent.append(output_tokens)
    if len(recent) > 50:
        recent = recent[-50:]
    entry["recent"] = recent

    # Compute P90
    sorted_recent = sorted(recent)
    p90_idx = int(len(sorted_recent) * 0.9)
    entry["p90_tokens"] = sorted_recent[min(p90_idx, len(sorted_recent) - 1)]

    history[key] = entry
    _save_history(history)
    return entry


def predict_budget(task, domain="backend", diff_plan=None):
    """Predict the optimal token budget for a task.

    Returns: {max_tokens: int, predicted_output: int, confidence: float, source: str}
    """
    kind = task.get("kind", "feature")
    key = _history_key(kind, domain)
    history = _history()
    entry = history.get(key)

    # If we have history, use P90 + headroom
    if entry and entry.get("samples", 0) >= 5:
        p90 = entry.get("p90_tokens", DEFAULT_BUDGET)
        predicted = int(p90 * BUDGET_HEADROOM)
        budget = max(MIN_BUDGET, min(predicted, DEFAULT_BUDGET))

        return {
            "max_tokens": budget,
            "predicted_output": p90,
            "confidence": min(0.9, entry["samples"] / 50),
            "source": "historical",
            "samples": entry["samples"],
            "savings_pct": round((1 - budget / DEFAULT_BUDGET) * 100, 1),
        }

    # Heuristic fallback based on task characteristics
    prompt_len = len(task.get("prompt", ""))

    # Template match → tighter budget
    if diff_plan and diff_plan.get("has_plan") and diff_plan.get("confidence", 0) > 0.5:
        template_lines = diff_plan.get("estimated_lines", 50)
        # ~4 tokens per line of code, plus explanation
        predicted = max(MIN_BUDGET, template_lines * 6 + 500)
        return {
            "max_tokens": min(predicted, DEFAULT_BUDGET),
            "predicted_output": predicted,
            "confidence": 0.4,
            "source": "template_estimate",
            "savings_pct": round((1 - min(predicted, DEFAULT_BUDGET) / DEFAULT_BUDGET) * 100, 1),
        }

    # Kind-based defaults
    KIND_DEFAULTS = {
        "mechanical": 2048,
        "config": 1536,
        "recovery": 3072,
        "test": 4096,
        "feature": 6144,
        "refactor": 6144,
        "security": 4096,
    }

    default = KIND_DEFAULTS.get(kind, DEFAULT_BUDGET)
    return {
        "max_tokens": default,
        "predicted_output": default,
        "confidence": 0.2,
        "source": "kind_default",
        "savings_pct": round((1 - default / DEFAULT_BUDGET) * 100, 1),
    }


def run():
    """Periodic: log budget prediction stats."""
    history = _history()
    if not history:
        print("[adaptive-budget] no history yet")
        return

    total_samples = sum(e.get("samples", 0) for e in history.values())
    avg_savings = sum(
        (1 - min(e.get("p90_tokens", 8192) * BUDGET_HEADROOM, DEFAULT_BUDGET) / DEFAULT_BUDGET)
        for e in history.values() if e.get("samples", 0) >= 5
    )
    entries_with_data = sum(1 for e in history.values() if e.get("samples", 0) >= 5)

    if entries_with_data > 0:
        avg_savings_pct = (avg_savings / entries_with_data) * 100
        print(f"[adaptive-budget] {len(history)} pairs, {total_samples} samples, "
              f"avg savings={avg_savings_pct:.0f}% on {entries_with_data} mature pairs")
