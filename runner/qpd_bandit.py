#!/usr/bin/env python3
"""
qpd_bandit.py - learn the QUALITY-PER-DOLLAR of each provider/model per task class and route to the
live best, instead of a fixed tranche order. A Thompson-style bandit over app_operations telemetry:
each (task_class, provider, model) arm tracks avg quality and avg cost; score = quality / (cost + eps)
with an exploration bonus that decays as samples grow. Occasionally explores a cheaper arm to keep the
estimate honest.

best(task_class) -> (provider, model, why)   — the current quality-per-dollar leader (explore sometimes)
This makes model_policy/app_triage routing provably adaptive rather than heuristic. Non-agentic only;
Anthropic agentic work stays on the subscription.
"""
import os, sys, math, random
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

EPS = 0.0005
EXPLORE = float(os.environ.get("QPD_EXPLORE", "0.10"))


def _arms(task_class):
    rows = db.select("app_operations", {"select": "provider,model,cost_usd,quality_score,task_class",
                                        "task_class": f"eq.{task_class}",
                                        "quality_score": "not.is.null",
                                        "order": "created_at.desc", "limit": "1000"}) or []
    arms = {}
    for r in rows:
        k = (r["provider"], r["model"])
        a = arms.setdefault(k, {"q": 0.0, "c": 0.0, "n": 0})
        a["q"] += float(r.get("quality_score") or 0)
        a["c"] += float(r.get("cost_usd") or 0)
        a["n"] += 1
    return arms


def rank(task_class):
    arms = _arms(task_class)
    scored = []
    total_n = sum(a["n"] for a in arms.values()) or 1
    for (prov, model), a in arms.items():
        if a["n"] == 0:
            continue
        q = a["q"] / a["n"]
        c = a["c"] / a["n"]
        base = q / (c + EPS)
        bonus = math.sqrt(2 * math.log(total_n) / a["n"])   # UCB exploration term
        scored.append({"provider": prov, "model": model, "qpd": base, "score": base * (1 + 0.1 * bonus),
                       "avg_quality": round(q, 2), "avg_cost": round(c, 5), "n": a["n"]})
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored


def best(task_class):
    r = rank(task_class)
    if not r:
        return None, None, "no telemetry yet (fall back to model_policy)"
    if random.random() < EXPLORE and len(r) > 1:
        pick = random.choice(r[1:])
        return pick["provider"], pick["model"], f"explore ({pick['n']} samples)"
    top = r[0]
    return top["provider"], top["model"], f"qpd leader q={top['avg_quality']} ${top['avg_cost']} (n={top['n']})"


# ── SLA integration: penalize / restore providers ────────────────────
# Called by provider_failover_sla.py when a provider breaches/recovers SLA.
# These inject synthetic negative/positive signals so the bandit routes
# traffic away from unhealthy providers without waiting for organic samples.

_PENALTY_WEIGHT = float(os.environ.get("QPD_PENALTY_WEIGHT", "5.0"))
_penalties = {}  # provider -> {"reason": str, "since": timestamp}
_penalty_lock = __import__("threading").Lock()


def penalize(provider, reason="sla_breach"):
    """Demote a provider by injecting a synthetic low-quality signal.

    The bandit's _arms() reads from app_operations, so we insert a row
    with quality_score=0 and inflated cost to push the arm's score down.
    Also tracked in-memory so rank() can apply a persistent penalty multiplier.
    """
    try:
        with _penalty_lock:
            _penalties[provider] = {"reason": reason, "since": __import__("time").time()}
        # Insert synthetic negative observations so the UCB arm decays
        for _ in range(int(_PENALTY_WEIGHT)):
            db.insert("app_operations", {
                "provider": provider,
                "model": "penalty",
                "cost_usd": 1.0,
                "quality_score": 0.0,
                "task_class": "__sla_penalty",
                "operation": "sla_penalty",
                "ok": False,
                "error": reason,
                "_allow_dup": True,
            })
    except Exception:
        pass


def restore(provider):
    """Remove demotion for a provider that has recovered."""
    try:
        with _penalty_lock:
            _penalties.pop(provider, None)
    except Exception:
        pass


def is_penalized(provider):
    """Check if a provider is currently penalized."""
    with _penalty_lock:
        return provider in _penalties


def penalties():
    """Return current penalty state for diagnostics."""
    with _penalty_lock:
        return dict(_penalties)


# ── Enhanced best() with penalty awareness ───────────────────────────

def best_with_penalties(task_class):
    """Like best() but applies penalty multipliers to demoted providers."""
    r = rank(task_class)
    if not r:
        return None, None, "no telemetry yet (fall back to model_policy)"

    # Apply penalty: halve score for penalized providers
    with _penalty_lock:
        for arm in r:
            if arm["provider"] in _penalties:
                arm["score"] *= 0.1  # 90% reduction
                arm["_penalized"] = True

    r.sort(key=lambda x: x["score"], reverse=True)

    if random.random() < EXPLORE and len(r) > 1:
        # Don't explore into penalized providers
        non_penalized = [a for a in r[1:] if not a.get("_penalized")]
        if non_penalized:
            pick = random.choice(non_penalized)
            return pick["provider"], pick["model"], f"explore non-penalized ({pick['n']} samples)"

    top = r[0]
    return top["provider"], top["model"], f"qpd leader q={top['avg_quality']} ${top['avg_cost']} (n={top['n']})"


# ── Capability-aware routing (integrates with vendor_capabilities) ───

def best_for_capabilities(task_class, required_capabilities=None):
    """Pick the best provider/model considering both QPD score AND capability coverage.

    If required_capabilities is provided, only arms whose provider has those
    capabilities are considered. Falls back to best() if vendor_capabilities
    is unavailable.
    """
    if not required_capabilities:
        return best_with_penalties(task_class)

    try:
        import vendor_capabilities
    except ImportError:
        return best_with_penalties(task_class)

    r = rank(task_class)
    if not r:
        return None, None, "no telemetry yet"

    # Filter to providers that cover required capabilities
    capable = []
    for arm in r:
        prov = arm["provider"]
        has_all = all(
            vendor_capabilities.vendor_has_capability(prov, cap)
            for cap in required_capabilities
        )
        if has_all:
            capable.append(arm)

    if not capable:
        # No single provider covers all — fall back to best overall
        return best_with_penalties(task_class)

    # Apply penalties
    with _penalty_lock:
        for arm in capable:
            if arm["provider"] in _penalties:
                arm["score"] *= 0.1

    capable.sort(key=lambda x: x["score"], reverse=True)
    top = capable[0]
    return top["provider"], top["model"], f"capability-filtered qpd leader (n={top['n']})"


if __name__ == "__main__":
    import json
    for tc in ("qa", "review", "rating", "plan"):
        print(tc, "->", best(tc))
        print("   ", json.dumps(rank(tc)[:3]))
