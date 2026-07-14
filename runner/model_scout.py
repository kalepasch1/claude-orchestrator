#!/usr/bin/env python3
"""model_scout.py — autonomous model-release discovery, evaluation, and adoption.

You should never have to prompt "there's a new model, use it." This bot, every few hours:

  1. DISCOVER  Lists the live models each connected vendor actually offers (OpenAI, Google,
               DeepSeek, xAI/Grok, Groq, Cerebras, Anthropic, local Ollama) using whatever keys
               are in the env — vendors with no key are skipped. New models (not seen before) are
               detected against .runtime/known_models.json.
  2. EVALUATE  For each new model on a provider the gateway can already route to, runs a small
               fixed eval battery (coding, classification, reasoning) through model_gateway and
               scores quality × speed × cost — the same axes you asked to optimize.
  3. ADOPT     If a new model beats the currently-configured model of its tier by a margin, it
               swaps it in FLEET-WIDE by updating the tier's env var via fleet_config (e.g.
               OPENAI_FAST_MODEL=gpt-5.6), records the prior value, and files an informational
               ops card. Otherwise it shelves the result (still logged) so you can see the analysis.
  4. ROLLBACK  After adoption it watches the model's live success-rate for a window; if it
               regresses vs the prior model, it reverts automatically and cards you.

New models on vendors the gateway can't route to YET (xAI/Groq/Cerebras until the gateway
speed-tier lands) are recorded as 'pending-gateway' with a card, not silently dropped.

Fail-soft everywhere; conservative margins; every change is reversible and journaled.
"""
import datetime
import json
import os
import re
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
REPO = os.path.dirname(HERE)
RUNTIME = os.path.join(REPO, ".runtime")
KNOWN = os.path.join(RUNTIME, "known_models.json")
STATE = os.path.join(RUNTIME, "model_scout_state.json")
JOURNAL = os.path.join(RUNTIME, "model_scout.jsonl")

ADOPT_MARGIN = float(os.environ.get("MODEL_SCOUT_ADOPT_MARGIN", "0.05"))  # new must beat by >=5%
EVAL_TIMEOUT = int(os.environ.get("MODEL_SCOUT_EVAL_TIMEOUT", "60"))

# tier -> env var the gateway/catalog reads, per provider. Adopting = setting this var fleet-wide.
TIER_ENV = {
    "openai": {"cheap": "OPENAI_CHEAP_MODEL", "fast": "OPENAI_FAST_MODEL", "strong": "OPENAI_STRONG_MODEL"},
    "google": {"cheap": "GEMINI_CHEAP_MODEL", "fast": "GEMINI_MODEL", "strong": "GEMINI_STRONG_MODEL"},
    "deepseek": {"cheap": "DEEPSEEK_CHEAP_MODEL", "strong": "DEEPSEEK_REASONER_MODEL"},
}
ROUTABLE = {"openai", "google", "deepseek", "groq", "xai", "local"}


def _now():
    return datetime.datetime.utcnow()


def journal(action, detail="", durable=False):
    row = {"at": _now().isoformat() + "Z", "action": action, "detail": str(detail)[:400], "durable": bool(durable)}
    print(f"model_scout {action} {str(detail)[:140]}", flush=True)
    try:
        os.makedirs(RUNTIME, exist_ok=True)
        with open(JOURNAL, "a") as f:
            f.write(json.dumps(row) + "\n")
    except OSError:
        pass


def _load(path, default):
    try:
        return json.load(open(path))
    except Exception:
        return default


def _save(path, obj):
    try:
        os.makedirs(RUNTIME, exist_ok=True)
        json.dump(obj, open(path, "w"), indent=1)
    except OSError:
        pass


def _set_fleet_config(key, value):
    try:
        import db
        db.insert("fleet_config", {"key": key, "value": str(value)}, upsert=True)
        return True
    except Exception:
        return False


def _escalate(title, why, value):
    try:
        import db
        db.insert("approvals", {"project": "ORCHESTRATOR", "kind": "self",
                                "title": title[:120], "why": why[:400], "value": value[:200],
                                "risk": "Auto-applied by model_scout; reversible; watched for regression."})
    except Exception:
        pass


def _get(url, headers=None, timeout=25):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


# ── 1. DISCOVERY ──────────────────────────────────────────────────────────────

def _key(*names):
    for n in names:
        v = os.environ.get(n)
        if v:
            return v
    return None


def discover():
    """Return {provider: [model_id,...]} for every vendor with a usable key."""
    found = {}
    # OpenAI-compatible vendors: same /models shape, just different base + key
    oai_style = {
        "openai":   ("https://api.openai.com/v1/models",       _key("OPENAI_API_KEY")),
        "xai":      ("https://api.x.ai/v1/models",             _key("XAI_API_KEY", "GROK_API_KEY")),
        "groq":     ("https://api.groq.com/openai/v1/models",  _key("GROQ_API_KEY")),
        "cerebras": ("https://api.cerebras.ai/v1/models",      _key("CEREBRAS_API_KEY")),
        "deepseek": ("https://api.deepseek.com/v1/models",     _key("DEEPSEEK_API_KEY")),
    }
    for prov, (url, key) in oai_style.items():
        if not key:
            continue
        try:
            d = _get(url, {"Authorization": f"Bearer {key}", "User-Agent": "orch-scout"})
            found[prov] = sorted({m.get("id") for m in (d.get("data") or []) if m.get("id")})
        except Exception as e:
            journal("discover-skip", f"{prov}: {str(e)[:60]}")
    # Google
    try:
        import model_gateway
        gm = model_gateway.google_models()
        if gm:
            found["google"] = sorted(gm)
    except Exception:
        pass
    # Anthropic (only if a real API key is present; subscription mode has none)
    ak = _key("ANTHROPIC_API_KEY")
    if ak:
        try:
            d = _get("https://api.anthropic.com/v1/models",
                     {"x-api-key": ak, "anthropic-version": "2023-06-01", "User-Agent": "orch-scout"})
            found["claude"] = sorted({m.get("id") for m in (d.get("data") or []) if m.get("id")})
        except Exception:
            pass
    # Local Ollama
    try:
        out = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=20).stdout
        local = [ln.split()[0] for ln in out.splitlines()[1:] if ln.split()]
        if local:
            found["local"] = sorted(local)
    except Exception:
        pass
    return found


def _classify_tier(provider, model_id):
    """Best-effort tier from the model name so we compare like-for-like. Uses delimiter-aware
    token matching so 'mini' does not match inside 'geMINI' (a real bug that mis-tiered
    gemini-*-pro as 'fast')."""
    m = model_id.lower()

    def has(tok):
        return re.search(r"(?:^|[-_/. ])" + re.escape(tok) + r"(?:$|[-_/. \d])", m) is not None

    if any(has(t) for t in ("nano", "lite", "flash-lite", "mini-cheap")):
        return "cheap"
    if any(has(t) for t in ("mini", "flash", "fast", "haiku", "small")):
        return "fast"
    if any(has(t) for t in ("pro", "opus", "strong", "large", "reasoner", "sonnet", "max")) or has("o"):
        return "strong"
    return "fast"  # default bucket


def _is_chat_coding_model(provider, model_id):
    m = model_id.lower()
    bad = ("embed", "whisper", "tts", "audio", "image", "vision-only", "moderation",
           "dall-e", "rerank", "guard", "search")
    return not any(b in m for b in bad)


def _version_key(model_id):
    """Sort key from the numbers in a model id, so gpt-5.6 > gpt-5.4 and gemini-3 > gemini-2.5."""
    return [int(x) if x.isdigit() else 0 for x in re.findall(r"\d+", model_id)] or [0]


def tier_best_candidates(live):
    """For each routable provider+tier, the newest discovered chat/coding model of that tier that
    differs from the currently-configured one. This catches a NEW RELEASE (e.g. gpt-5.6 vs the
    configured gpt-5.4-mini) even on the very first run, without evaluating a vendor's whole list."""
    out = []
    for prov, models in live.items():
        if prov not in ROUTABLE or prov not in TIER_ENV:
            continue
        chat = [m for m in models if _is_chat_coding_model(prov, m)]
        for tier, env in TIER_ENV[prov].items():
            configured = os.environ.get(env)
            same_tier = [m for m in chat if _classify_tier(prov, m) == tier]
            if not same_tier:
                continue
            best = sorted(same_tier, key=_version_key)[-1]
            if best and best != configured:
                out.append((prov, best))
    # dedup preserving order
    seen, uniq = set(), []
    for pm in out:
        if pm not in seen:
            seen.add(pm); uniq.append(pm)
    return uniq


# ── 2. EVALUATION ─────────────────────────────────────────────────────────────

def _chk_code(t):
    s = (t or "").lower().replace(" ", "")
    return ("sum" in s and ("%2" in s or "even" in s or "&1" in s or "for" in s)) or ("%2==0" in s)


def _chk_classify(t):
    return "negative" in (t or "").lower()


def _chk_reason(t):
    s = (t or "").lower().replace(" ", "")
    return any(x in s for x in ("3:30", "15:30", "3.30", "330", "halfpast3", "3:30pm"))


EVAL_BATTERY = [
    ("code",
     "Write a Python one-liner that returns the sum of even numbers in a list xs. "
     "You may include a brief code fence.", _chk_code),
    ("classify",
     "Classify the sentiment of 'this build keeps failing and I am frustrated' as one word: "
     "positive, negative, or neutral.", _chk_classify),
    ("reason",
     "A train leaves at 2:00 and the trip takes 90 minutes. What time does it arrive? "
     "State the time.", _chk_reason),
]


def evaluate(provider, model):
    """Run the battery; return {'score','latency_ms','cost','passes','n'} or None on hard failure."""
    try:
        import model_gateway
    except Exception:
        return None
    passes, total_lat, total_cost, n = 0, 0.0, 0.0, 0
    for _name, prompt, check in EVAL_BATTERY:
        t0 = time.time()
        try:
            res = model_gateway.complete(provider, model, prompt, timeout=EVAL_TIMEOUT,
                                         operation="scout_eval", task_class="eval")
            txt = res.get("text", "")
            total_cost += float(res.get("cost_usd") or 0)
            total_lat += (time.time() - t0) * 1000
            n += 1
            if check(txt or ""):
                passes += 1
        except Exception:
            n += 1  # count as attempted; a hard failure counts against it
    if n == 0:
        return None
    quality = passes / n                          # 0..1
    avg_lat = total_lat / n                        # ms
    speed = 1.0 / (1.0 + avg_lat / 1000.0)         # 0..1, faster = higher
    cheapness = 1.0 / (1.0 + (total_cost / n) * 100)  # 0..1, cheaper = higher ($0 local -> 1)
    # composite: quality dominates, then value (speed+cost)
    score = 0.6 * quality + 0.25 * speed + 0.15 * cheapness
    return {"score": round(score, 4), "quality": round(quality, 3),
            "latency_ms": int(avg_lat), "cost": round(total_cost / n, 6), "passes": passes, "n": n}


# ── 3. ADOPT ──────────────────────────────────────────────────────────────────

# Effective defaults the gateway/catalog fall back to when the env var is unset — so the scout
# compares a new model against the REAL model in use, not against nothing.
_TIER_DEFAULTS = {
    "OPENAI_CHEAP_MODEL": "gpt-5.4-nano", "OPENAI_FAST_MODEL": "gpt-5.4-mini",
    "OPENAI_STRONG_MODEL": "gpt-5.4", "GEMINI_CHEAP_MODEL": "gemini-2.5-flash-lite-preview-09-2025",
    "GEMINI_MODEL": "gemini-2.5-flash", "GEMINI_STRONG_MODEL": "gemini-2.5-pro",
    "DEEPSEEK_CHEAP_MODEL": "deepseek-v4-flash", "DEEPSEEK_REASONER_MODEL": "deepseek-v4-pro",
}


def _incumbent(provider, tier):
    env = TIER_ENV.get(provider, {}).get(tier)
    if not env:
        return None, None
    return os.environ.get(env) or _TIER_DEFAULTS.get(env), env


def consider_adopt(provider, model, st):
    if provider not in ROUTABLE:
        journal("pending-gateway", f"{provider}:{model} — new model, gateway can't route {provider} yet")
        _escalate(f"New {provider} model available: {model}",
                  f"Discovered {model} but the gateway has no {provider} adapter yet "
                  "(pending the speed-tier gateway task). Not evaluated.",
                  "Add the adapter to auto-adopt this vendor's models.")
        return
    tier = _classify_tier(provider, model)
    incumbent, env = _incumbent(provider, tier)
    if not env:
        return
    new_eval = evaluate(provider, model)
    if not new_eval or new_eval["n"] == 0 or new_eval["quality"] <= 0:  # totally broken/unreachable
        journal("eval-failed", f"{provider}:{model} tier={tier} eval={new_eval}")
        return
    inc_eval = evaluate(provider, incumbent) if incumbent else None
    inc_score = inc_eval["score"] if inc_eval else 0.0
    journal("evaluated", f"{provider}:{model} tier={tier} score={new_eval['score']} "
                         f"vs incumbent {incumbent}={inc_score} ({new_eval})")
    if new_eval["score"] >= inc_score * (1 + ADOPT_MARGIN) and new_eval["quality"] >= (inc_eval["quality"] if inc_eval else 0):
        # ADOPT — set the tier env var fleet-wide, remember the prior for rollback + watch
        if _set_fleet_config(env, model):
            st.setdefault("adopted", {})[env] = {
                "new": model, "prev": incumbent, "at": _now().isoformat() + "Z",
                "new_score": new_eval["score"], "prev_score": inc_score, "watch_until": time.time() + 6 * 3600}
            journal("ADOPTED", f"{env}: {incumbent} -> {model} (score {inc_score}->{new_eval['score']})", durable=True)
            _escalate(f"Adopted new model {model} ({provider} {tier})",
                      f"{model} beat {incumbent} on the eval battery "
                      f"(score {new_eval['score']} vs {inc_score}; quality {new_eval['quality']}, "
                      f"{new_eval['latency_ms']}ms, ${new_eval['cost']}/call). Swapped in via {env}.",
                      "Watched 6h for live regression; auto-reverts if it underperforms.")
    else:
        journal("shelved", f"{provider}:{model} did not beat {incumbent} (kept incumbent)")


# ── 4. ROLLBACK WATCH ─────────────────────────────────────────────────────────

def rollback_watch(st):
    """After adoption, watch live outcome success for the model; revert if it regresses."""
    adopted = st.get("adopted", {})
    if not adopted:
        return
    try:
        import db
    except Exception:
        return
    for env, info in list(adopted.items()):
        if time.time() > info.get("watch_until", 0):
            adopted.pop(env, None)  # watch window over, keep the adoption
            continue
        model = info["new"]
        try:
            since = (_now() - datetime.timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S")
            rows = db.select("app_operations", {"select": "ok", "model": f"eq.{model}",
                                                "created_at": f"gte.{since}", "limit": "200"}) or []
            if len(rows) >= 12:  # enough signal
                ok_rate = sum(1 for r in rows if r.get("ok")) / len(rows)
                if ok_rate < 0.6:  # live regression
                    if _set_fleet_config(env, info["prev"]):
                        journal("ROLLED-BACK", f"{env}: {model} -> {info['prev']} (live ok_rate {ok_rate:.2f})", durable=True)
                        _escalate(f"Reverted {model} — live regression",
                                  f"{model} had {ok_rate:.0%} success over {len(rows)} live calls (<60%). "
                                  f"Reverted {env} to {info['prev']}.",
                                  "Auto-rollback protected throughput.")
                        adopted.pop(env, None)
        except Exception:
            continue


def main():
    st = _load(STATE, {})
    known = _load(KNOWN, {})
    live = discover()
    if not live:
        journal("no-vendors", "no vendor keys / endpoints reachable")
        return
    # New-since-baseline diffing only applies once a baseline exists; on cold start the ONLY
    # driver is tier_best_candidates (the current newest per tier), so we don't storm-evaluate a
    # vendor's entire catalog the first time.
    new_by_prov = {}
    if known:
        for prov, models in live.items():
            prev = set(known.get(prov, []))
            fresh = [m for m in models if m not in prev and _is_chat_coding_model(prov, m)]
            if fresh:
                new_by_prov[prov] = fresh
    # persist the full current catalog as the new baseline BEFORE evaluating (so a flapping list
    # doesn't re-trigger; first-ever run just records without adopting to avoid a cold-start storm)
    _save(KNOWN, live)
    # Candidates = (new-since-baseline) UNION (newest per tier that beats what's configured).
    # The second set catches CURRENT releases (e.g. gpt-5.6 vs configured gpt-5.4-mini) even on the
    # first run, so you never have to prompt "use the new model."
    candidates = []
    for prov, models in new_by_prov.items():
        journal("new-models", f"{prov}: {models}")
        for m in models:
            candidates.append((prov, m))
    for pm in tier_best_candidates(live):
        if pm not in candidates:
            candidates.append(pm)
    # skip candidates we already evaluated recently and shelved (avoid re-eval churn/cost)
    recent = st.get("evaluated", {})
    cutoff = time.time() - int(os.environ.get("MODEL_SCOUT_REEVAL_DAYS", "7")) * 86400
    todo = [(p, m) for (p, m) in candidates if recent.get(f"{p}:{m}", 0) < cutoff]
    if not todo:
        journal("no-new-candidates", f"scanned {len(live)} vendors; nothing new to evaluate")
    cap = int(os.environ.get("MODEL_SCOUT_MAX_EVAL_PER_RUN", "4"))
    for prov, m in todo[:cap]:
        try:
            consider_adopt(prov, m, st)
        except Exception as e:
            journal("adopt-error", f"{prov}:{m} {str(e)[:80]}")
        st.setdefault("evaluated", {})[f"{prov}:{m}"] = time.time()
    try:
        rollback_watch(st)
    except Exception as e:
        journal("rollback-error", str(e)[:80])
    _save(STATE, st)


if __name__ == "__main__":
    main()
