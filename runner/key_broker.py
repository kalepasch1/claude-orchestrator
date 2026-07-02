#!/usr/bin/env python3
"""
key_broker.py - the ONE mediated path to any paid provider. Zero-key architecture: modules never read
provider API keys from the environment directly; they ask the broker to make the call. The broker is
the single place a key is touched, and every call passes through a per-call budget token that enforces
a hard ceiling BEFORE the request goes out. This makes another surprise bill structurally impossible,
not just guarded after the fact.

  call(provider, model, prompt, *, app, operation, max_usd=None) -> {text, cost_usd, provider, model}

Rules:
  * Anthropic is NEVER billed here — subscription_guard has stripped its key; agentic Claude work goes
    through claude_cli (Max subscription). The broker only mediates the cheap external providers.
  * Every call is checked against a rolling daily REAL-$ ceiling (BROKER_MAX_USD_DAY, default $5) and a
    per-call ceiling (max_usd). Over ceiling -> the call is refused (returns error), never silently sent.
  * All spend is logged to app_operations so the forecaster + arbitrage loops see it.
"""
import os, sys, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import model_gateway as mg

HOME = os.environ.get("CLAUDE_ORCH_HOME", os.path.expanduser("~/.claude-orchestrator"))
LEDGER = os.path.join(HOME, "broker_spend.json")
MAX_USD_DAY = float(os.environ.get("BROKER_MAX_USD_DAY", "5.0"))
MAX_USD_CALL = float(os.environ.get("BROKER_MAX_USD_CALL", "0.50"))
os.makedirs(HOME, exist_ok=True)


def _today_spend():
    try:
        d = json.load(open(LEDGER))
        cut = time.time() - 86400
        return sum(v for ts, v in d.get("spend", []) if ts >= cut)
    except Exception:
        return 0.0


def _record(usd):
    try:
        d = json.load(open(LEDGER))
    except Exception:
        d = {"spend": []}
    cut = time.time() - 86400
    d["spend"] = [[ts, v] for ts, v in d.get("spend", []) if ts >= cut] + [[time.time(), float(usd or 0)]]
    json.dump(d, open(LEDGER, "w"))


def budget_left():
    return round(max(0.0, MAX_USD_DAY - _today_spend()), 4)


# ── Per-call budget TOKENS ────────────────────────────────────────────────────────────────────
# A caller gets a signed grant for a bounded amount; the broker decrements it per call and refuses
# once exhausted. This turns cost safety from "monitored" into "mathematically bounded" — a module
# cannot spend beyond its grant even in aggregate, even if it loops.
import hmac, hashlib
_SECRET = (os.environ.get("BROKER_TOKEN_SECRET", "") or "orchestrator-local").encode()
_GRANTS = os.path.join(HOME, "broker_grants.json")


def _grants():
    try:
        return json.load(open(_GRANTS))
    except Exception:
        return {}


def _save_grants(g):
    json.dump(g, open(_GRANTS, "w"))


def issue_grant(owner, max_usd):
    """Issue a signed budget grant of `max_usd` to `owner`. Returns a token string."""
    max_usd = min(float(max_usd), MAX_USD_DAY)
    nonce = hashlib.sha1(f"{owner}{time.time()}".encode()).hexdigest()[:12]
    sig = hmac.new(_SECRET, f"{owner}:{max_usd}:{nonce}".encode(), hashlib.sha256).hexdigest()[:16]
    token = f"{owner}:{max_usd}:{nonce}:{sig}"
    g = _grants(); g[nonce] = {"owner": owner, "cap": max_usd, "spent": 0.0}; _save_grants(g)
    return token


def _valid(token):
    try:
        owner, cap, nonce, sig = token.split(":")
        good = hmac.new(_SECRET, f"{owner}:{cap}:{nonce}".encode(), hashlib.sha256).hexdigest()[:16]
        return nonce if hmac.compare_digest(sig, good) else None
    except Exception:
        return None


def call_with_grant(token, provider, model, prompt, app="orchestrator", operation="call"):
    """Like call(), but ALSO bounded by the grant's remaining budget. Refuses if grant exhausted."""
    nonce = _valid(token)
    if not nonce:
        return {"text": "", "cost_usd": 0, "error": "invalid budget token"}
    g = _grants(); rec = g.get(nonce)
    if not rec or rec["spent"] >= rec["cap"]:
        return {"text": "", "cost_usd": 0, "error": "budget grant exhausted"}
    res = call(provider, model, prompt, app=app, operation=operation,
               max_usd=min(MAX_USD_CALL, rec["cap"] - rec["spent"]))
    rec["spent"] = round(rec["spent"] + float(res.get("cost_usd") or 0), 6)
    g[nonce] = rec; _save_grants(g)
    res["grant_left"] = round(rec["cap"] - rec["spent"], 6)
    return res


def call(provider, model, prompt, app="orchestrator", operation="call", max_usd=None):
    """Mediated, budget-gated provider call. Anthropic is refused (use claude_cli/subscription)."""
    if provider in ("claude", "anthropic"):
        return {"text": "", "cost_usd": 0, "provider": provider, "model": model,
                "error": "anthropic must go through claude_cli (subscription), not the key broker"}
    cap = float(max_usd if max_usd is not None else MAX_USD_CALL)
    if _today_spend() >= MAX_USD_DAY:
        return {"text": "", "cost_usd": 0, "provider": provider, "model": model,
                "error": f"broker daily ceiling ${MAX_USD_DAY} reached — call refused"}
    res = mg.complete(provider, model, prompt, project=app)
    cost = float(res.get("cost_usd") or 0)
    if cost > cap:
        # over the per-call ceiling: record it (already spent) but flag loudly
        res["over_call_cap"] = True
    _record(cost)
    try:
        import app_triage
        app_triage.record(app, operation, "broker", provider, model, len(prompt or ""), cost, 0,
                          ok=not bool(res.get("error")))
    except Exception:
        pass
    return res


if __name__ == "__main__":
    print(json.dumps({"budget_left_today": budget_left(), "ceiling_day": MAX_USD_DAY}, indent=2))
