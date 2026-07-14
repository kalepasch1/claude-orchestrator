#!/usr/bin/env python3
"""Model-level catalog and picker.

Provider routing is too coarse: each vendor has cheap, fast, strong, and local
models. This module ranks concrete model candidates by capability, cost, latency,
trust policy, and empirical outcome data.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import model_gateway


def _configured(name, default, deprecated=()):
    value = os.environ.get(name, "").strip()
    if value and not any(value.startswith(prefix) for prefix in deprecated):
        return value
    return default


MODELS = {
    "local": [],
    "deepseek": [
        {"model": _configured("DEEPSEEK_CHEAP_MODEL", "deepseek-v4-flash",
                              deprecated=("deepseek-chat", "deepseek-reasoner")), "cap": 7, "tier": "cheap"},
        {"model": _configured("DEEPSEEK_REASONER_MODEL", "deepseek-v4-pro",
                              deprecated=("deepseek-chat", "deepseek-reasoner")), "cap": 9, "tier": "cheap"},
    ],
    "groq": [
        {"model": os.environ.get("GROQ_FAST_MODEL", "llama-3.1-8b-instant"), "cap": 5, "tier": "cheap"},
        {"model": os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile"), "cap": 7, "tier": "cheap"},
    ],
    "xai": [
        {"model": os.environ.get("XAI_CODING_MODEL", "grok-build-0.1"), "cap": 8, "tier": "mid"},
        {"model": os.environ.get("XAI_MODEL", "grok-4.3"), "cap": 9, "tier": "mid"},
    ],
    "google": [
        {"model": _configured("GEMINI_CHEAP_MODEL", "gemini-2.5-flash-lite-preview-09-2025",
                              deprecated=("gemini-2.0-",)), "cap": 6, "tier": "cheap"},
        {"model": _configured("GEMINI_MODEL", "gemini-2.5-flash",
                              deprecated=("gemini-2.0-",)), "cap": 8, "tier": "cheap"},
        {"model": _configured("GEMINI_STRONG_MODEL", "gemini-2.5-pro",
                              deprecated=("gemini-2.0-",)), "cap": 9, "tier": "mid"},
    ],
    "openai": [
        {"model": os.environ.get("OPENAI_CHEAP_MODEL", "gpt-5.4-nano"), "cap": 5, "tier": "cheap"},
        {"model": os.environ.get("OPENAI_FAST_MODEL", "gpt-5.4-mini"), "cap": 7, "tier": "cheap"},
        {"model": os.environ.get("OPENAI_AGENTIC_MODEL", "gpt-5.5"), "cap": 9, "tier": "mid"},
        {"model": os.environ.get("OPENAI_STRONG_MODEL", "gpt-5.5-pro"), "cap": 10, "tier": "expensive"},
    ],
    "claude": [
        {"model": "claude-haiku-4-5-20251001", "cap": 6, "tier": "sub"},
        {"model": os.environ.get("ORCH_ESCALATION_MODEL", "claude-sonnet-5"), "cap": 9, "tier": "sub"},
        {"model": "claude-opus-4-8", "cap": 10, "tier": "sub"},
        {"model": os.environ.get("CLAUDE_STRONG_MODEL", "claude-fable-5"), "cap": 10, "tier": "expensive"},
    ],
}

TIER_COST = {"free": 0.0, "cheap": 0.15, "sub": 0.25, "mid": 1.0, "expensive": 3.0}


def vendor_family(provider, model):
    """Preserve underlying model-vendor diversity for local open-weight routes."""
    provider = str(provider or "").lower()
    model = str(model or "").lower()
    if provider != "local":
        return provider
    for family, hints in {
        "deepseek-local": ("deepseek",),
        "mistral-local": ("mistral", "mixtral", "codestral"),
        "qwen-local": ("qwen",),
        "meta-local": ("llama",),
        "google-local": ("gemma",),
    }.items():
        if any(hint in model for hint in hints):
            return family
    return "local-other"


def _price_score(candidate):
    if candidate["provider"] == "local":
        return 0.0
    try:
        pin, pout = model_gateway.PRICES.get((candidate["provider"], candidate["model"]), (None, None))
        if pin is not None and pout is not None:
            # Route by the expected blended cost of a small review/planning call.
            return (float(pin) + float(pout)) / 2.0
    except Exception:
        pass
    return TIER_COST.get(candidate.get("tier"), 1.0)


def _available_models(available_providers=None):
    providers = set(available_providers) if available_providers is not None else set(model_gateway.available())
    out = []
    if "local" in providers:
        try:
            import ollama_catalog
            out.extend(ollama_catalog.candidates())
        except Exception:
            out.append({"provider": "local", "model": os.environ.get("OLLAMA_MODEL", "llama3.1"),
                        "cap": 5, "tier": "free"})
    for provider, items in MODELS.items():
        if provider == "local":
            continue
        if provider not in providers:
            continue
        for item in items:
            if not item.get("model"):
                continue
            out.append({"provider": provider, **item})
    return out


def _empirical_score(task_class, provider, model):
    try:
        import db
        rows = db.select("app_operations", {"select": "ok,cost_usd,latency_ms",
                                            "provider": f"eq.{provider}",
                                            "model": f"eq.{model}",
                                            "task_class": f"eq.{task_class}",
                                            "order": "created_at.desc",
                                            "limit": "80"}) or []
    except Exception:
        return 0.0
    try:
        import route_value_optimizer
        min_samples = route_value_optimizer.MIN_SAMPLES
        lower = route_value_optimizer.wilson_lower(sum(1 for r in rows if r.get("ok")), len(rows))
    except Exception:
        min_samples, lower = 20, 0.0
    if len(rows) < min_samples:
        return 0.0
    cost = sum(float(r.get("cost_usd") or 0) for r in rows) / len(rows)
    latency = sum(float(r.get("latency_ms") or 0) for r in rows) / len(rows)
    return lower * 2.0 - cost - min(2.0, latency / 60000.0)


def ranked(task_class="review", need=6, sensitivity="standard", exclude_provider=None,
           available_providers=None, use_empirical=True):
    """Return every capable concrete model in optimizer order.

    Exposing the ranked portfolio lets independent QA panels select diverse
    vendors while retaining the same cost, capability, trust, and empirical
    scoring used for the primary route.
    """
    try:
        import provider_terms
    except Exception:
        provider_terms = None
    try:
        import model_slashing
    except Exception:
        model_slashing = None
    candidates = []
    for c in _available_models(available_providers):
        if exclude_provider and c["provider"] == exclude_provider:
            continue
        if int(c.get("cap") or 0) < int(need or 0):
            continue
        if provider_terms and not provider_terms.allowed(c["provider"], sensitivity):
            continue
        try:
            import provider_failover_sla
            if c["provider"] != "local" and provider_failover_sla.is_demoted(c["provider"]):
                continue
        except Exception:
            pass
        price = _price_score(c)
        empirical = _empirical_score(task_class, c["provider"], c["model"]) if use_empirical else 0.0
        deployed_value = 0.0
        if use_empirical:
            try:
                import route_value_optimizer
                deployed_value = route_value_optimizer.provider_score(c["provider"])
            except Exception:
                pass
        surplus = max(0, int(c.get("cap") or 0) - int(need or 0))
        surplus_penalty = surplus * (0.02 if c["provider"] == "local" else 0.05)
        local_bonus = 0.08 if c["provider"] == "local" else 0.0
        slash_penalty = model_slashing.score_adjustment(c["provider"], c["model"]) if model_slashing else 0.0
        score = empirical + (2.0 * deployed_value) - price - surplus_penalty - slash_penalty + (int(c.get("cap") or 0) / 100.0) + local_bonus
        candidates.append((score, price, -c["cap"], c))
    candidates.sort(key=lambda x: (-x[0], x[1], x[2]))
    return [{**item[3], "vendor_family": vendor_family(item[3]["provider"], item[3]["model"]),
             "optimizer_score": round(item[0], 4),
             "price_score": round(item[1], 4)} for item in candidates]


def choose(task_class="review", need=6, sensitivity="standard", exclude_provider=None,
           available_providers=None, use_empirical=True):
    candidates = ranked(task_class, need, sensitivity, exclude_provider,
                        available_providers, use_empirical)
    return candidates[0] if candidates else None


def available():
    return _available_models()


if __name__ == "__main__":
    import json
    print(json.dumps(available(), indent=2))
