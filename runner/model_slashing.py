#!/usr/bin/env python3
"""Model slashing ledger.

This is a lightweight punishment/recovery system for vendor/model routes. It
does not ban models outright; it lowers their allocation score after bad
outcomes and lets canaries earn the score back through later merges.
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

CONTROL_KEY = "model_slashing"
MAX_PENALTY = float(os.environ.get("ORCH_MODEL_SLASH_MAX", "3.0"))
RECOVERY_CREDIT = float(os.environ.get("ORCH_MODEL_SLASH_RECOVERY", "0.35"))


def agent_key(provider_or_agent, model=""):
    raw = str(provider_or_agent or "").strip().lower()
    m = str(model or "").strip().lower()
    if m and m not in raw:
        raw = f"{raw}:{m}"
    aliases = (
        ("deepseek", "deepseek"), ("codestral", "codestral"),
        ("ollama", "ollama"), ("gemini", "gemini"),
        ("grok", "xai"), ("xai", "xai"),
        ("gpt-mini", "gpt-mini"), ("openai", "gpt"),
    )
    for needle, canonical in aliases:
        if needle in raw:
            return canonical
    return raw or "unknown"


def _ledger():
    try:
        rows = db.select("controls", {"select": "value", "key": f"eq.{CONTROL_KEY}", "limit": "1"}) or []
        raw = (rows[0] if rows else {}).get("value") or "{}"
        return json.loads(raw) if isinstance(raw, str) else (raw or {})
    except Exception:
        return {}


def _save(ledger):
    try:
        db.insert("controls", {"key": CONTROL_KEY, "value": json.dumps(ledger), "updated_at": "now()"}, upsert=True)
    except Exception:
        pass


def penalty_for(provider_or_agent, model=""):
    entry = _ledger().get(agent_key(provider_or_agent, model), {})
    return float(entry.get("penalty") or 0.0)


def allocation_multiplier(provider_or_agent, model=""):
    penalty = penalty_for(provider_or_agent, model)
    return max(0.1, round(1.0 / (1.0 + penalty), 3))


def score_adjustment(provider_or_agent, model=""):
    """Amount to subtract from a model-catalog score."""
    return penalty_for(provider_or_agent, model)


def record(provider_or_agent, model="", *, merged=False, tests_passed=False,
           review_failures=0, rollback=False, cost_usd=0.0, domain="general"):
    key = agent_key(provider_or_agent, model)
    ledger = _ledger()
    entry = ledger.get(key, {
        "agent": key,
        "attempts": 0,
        "good": 0,
        "bad": 0,
        "penalty": 0.0,
        "domains": {},
    })
    entry["attempts"] = int(entry.get("attempts") or 0) + 1
    domain_key = str(domain or "general")
    domains = entry.setdefault("domains", {})
    d = domains.get(domain_key, {"attempts": 0, "merged": 0, "bad": 0})
    d["attempts"] = int(d.get("attempts") or 0) + 1

    delta = 0.0
    if merged:
        entry["good"] = int(entry.get("good") or 0) + 1
        d["merged"] = int(d.get("merged") or 0) + 1
        delta -= RECOVERY_CREDIT
    else:
        entry["bad"] = int(entry.get("bad") or 0) + 1
        d["bad"] = int(d.get("bad") or 0) + 1
        delta += 0.45
        if tests_passed:
            delta += 0.2  # passed local work but failed integration is still costly
    if not tests_passed:
        delta += 0.55
    if int(review_failures or 0) > 0:
        delta += min(0.8, 0.2 * int(review_failures or 0))
    if rollback:
        delta += 1.0
    if float(cost_usd or 0) > float(os.environ.get("ORCH_MODEL_SLASH_COST_WARN", "2.0")) and not merged:
        delta += 0.25

    entry["penalty"] = round(min(MAX_PENALTY, max(0.0, float(entry.get("penalty") or 0.0) + delta)), 4)
    entry["allocation_multiplier"] = max(0.1, round(1.0 / (1.0 + entry["penalty"]), 3))
    entry["last_outcome"] = {
        "merged": bool(merged),
        "tests_passed": bool(tests_passed),
        "review_failures": int(review_failures or 0),
        "rollback": bool(rollback),
        "cost_usd": float(cost_usd or 0.0),
        "domain": domain_key,
        "at": int(time.time()),
    }
    domains[domain_key] = d
    ledger[key] = entry
    _save(ledger)
    return entry


def rebuild_from_outcomes(hours=168, limit=5000):
    """Deterministically rebuild penalties from terminal routing evidence.

    This closes the old instrumentation gap where early test failures never
    reached record(), leaving weak routes at a zero penalty forever.
    """
    import datetime
    since = (datetime.datetime.utcnow() - datetime.timedelta(hours=hours)).isoformat()
    rows = db.select("outcomes", {
        "select": "id,task_id,model,kind,slug,integrated,tests_passed,usd,review_failures,created_at",
        "created_at": f"gte.{since}", "order": "created_at.desc", "limit": str(limit),
    }) or []
    try:
        import route_evidence
        rows = route_evidence.terminal_task_rows(rows)
    except Exception:
        pass
    ledger = {}
    for row in reversed(rows):
        key = agent_key(row.get("model"))
        entry = ledger.setdefault(key, {"agent": key, "attempts": 0, "good": 0,
                                        "bad": 0, "penalty": 0.0, "domains": {}})
        domain = str(row.get("kind") or "general")
        d = entry["domains"].setdefault(domain, {"attempts": 0, "merged": 0, "bad": 0})
        entry["attempts"] += 1
        d["attempts"] += 1
        merged, tested = bool(row.get("integrated")), bool(row.get("tests_passed"))
        if merged:
            entry["good"] += 1
            d["merged"] += 1
            delta = -RECOVERY_CREDIT
        else:
            entry["bad"] += 1
            d["bad"] += 1
            delta = 0.45 + (0.2 if tested else 0.0)
        if not tested:
            delta += 0.55
        delta += min(0.8, 0.2 * int(row.get("review_failures") or 0))
        if float(row.get("usd") or 0) > float(os.environ.get("ORCH_MODEL_SLASH_COST_WARN", "2.0")) and not merged:
            delta += 0.25
        entry["penalty"] = round(min(MAX_PENALTY, max(0.0, entry["penalty"] + delta)), 4)
        entry["allocation_multiplier"] = max(0.1, round(1.0 / (1.0 + entry["penalty"]), 3))
        entry["last_outcome"] = {"merged": merged, "tests_passed": tested,
                                  "domain": domain, "at": int(time.time())}
    _save(ledger)
    return ledger


def run():
    try:
        ledger = rebuild_from_outcomes()
    except Exception:
        ledger = _ledger()
    for key, entry in sorted(ledger.items(), key=lambda item: -float(item[1].get("penalty") or 0))[:20]:
        print(f"[slashing] {key}: penalty={entry.get('penalty')} multiplier={entry.get('allocation_multiplier')}")
    return ledger


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, default=str))
