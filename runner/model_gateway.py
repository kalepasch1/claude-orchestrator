#!/usr/bin/env python3
"""
model_gateway.py - provider-agnostic model dispatch. Lets the orchestrator use the CHEAPEST
capable model for each task/subtask across providers, not just Claude.

Honest reality:
  * Claude Code (subscription via claude_cli) is the primary AGENTIC CODER — it edits files in
    worktrees, runs tools, etc. Other providers can't do that agentic loop headlessly today.
  * So multi-model shines for: QA/review/rating (judge.py), planning, cheap bulk sub-tasks,
    and second opinions — where a raw completion API is enough.
  * ChatGPT *Plus/Premium* is a UI subscription and does NOT grant API access. To use GPT here
    you need an OPENAI_API_KEY (pay-per-token). Same for Google (GOOGLE_API_KEY), etc. Add only
    keys you're authorized to use; each call is metered + capped like Claude.

Providers (enabled when their key/env is present):
  claude  -> claude_cli (subscription, agentic)      openai  -> OPENAI_API_KEY
  google  -> GOOGLE_API_KEY (Gemini)                 deepseek-> DEEPSEEK_API_KEY (very cheap)
  local   -> OLLAMA_HOST (free, for costless QA/rating)

complete(provider, model, prompt) -> {"text","cost_usd","provider","model"}
"""
import os, sys, json, time, urllib.request, urllib.error
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _load_env():
    """Load runner/.env for scripts that import routing without going through db.py first."""
    env = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    try:
        with open(env) as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.split("#")[0].strip().strip('"').strip("'"))
    except OSError:
        pass


_load_env()

# rough $/1M tokens (input,output) for routing decisions; edit to current pricing
PRICES = {
    ("claude", "claude-haiku-4-5-20251001"): (1.0, 5.0),
    ("claude", "claude-sonnet-4-6"): (3.0, 15.0),
    ("claude", "claude-opus-4-8"): (15.0, 75.0),
    ("openai", "gpt-4o-mini"): (0.15, 0.6),
    ("openai", "gpt-4o"): (2.5, 10.0),
    ("openai", "o4-mini"): (1.1, 4.4),
    ("google", "gemini-2.0-flash"): (0.1, 0.4),
    ("deepseek", "deepseek-chat"): (0.14, 0.28),
    ("local", "*"): (0.0, 0.0),
}


def _ollama_host():
    raw = os.environ.get("OLLAMA_HOST", "http://localhost:11434").strip()
    # tolerate accidental notes like "http://localhost:11434 + ollama pull model"
    return raw.split()[0] if raw else "http://localhost:11434"


def _ollama_up():
    """Auto-detect a running Ollama on the default host (no OLLAMA_HOST needed)."""
    host = _ollama_host()
    try:
        urllib.request.urlopen(host + "/api/tags", timeout=1.5)
        return True
    except Exception:
        return False


def available():
    prov = ["claude"]
    # a key counts only if it's non-empty (blank .env lines don't enable a provider)
    if os.environ.get("OPENAI_API_KEY", "").strip(): prov.append("openai")
    if os.environ.get("GOOGLE_API_KEY", "").strip(): prov.append("google")
    if os.environ.get("DEEPSEEK_API_KEY", "").strip(): prov.append("deepseek")
    if _ollama_up(): prov.append("local")
    return prov


def _post(url, headers, payload, timeout=90):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={**headers, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _openai(model, prompt):
    d = _post("https://api.openai.com/v1/chat/completions",
              {"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"},
              {"model": model, "messages": [{"role": "user", "content": prompt}]})
    u = d.get("usage", {})
    pin, pout = PRICES.get(("openai", model), (2.5, 10))
    cost = u.get("prompt_tokens", 0)/1e6*pin + u.get("completion_tokens", 0)/1e6*pout
    return d["choices"][0]["message"]["content"], round(cost, 4)


def google_models():
    """List models this GOOGLE_API_KEY can actually use (helps diagnose 404s)."""
    key = os.environ.get("GOOGLE_API_KEY", "")
    try:
        req = urllib.request.Request(
            f"https://generativelanguage.googleapis.com/v1beta/models?key={key}")
        with urllib.request.urlopen(req, timeout=15) as r:
            d = json.loads(r.read().decode())
        return [m["name"].split("/")[-1] for m in d.get("models", [])
                if "generateContent" in (m.get("supportedGenerationMethods") or [])]
    except Exception as e:
        return [f"(list failed: {e})"]


def _google(model, prompt):
    import time as _t
    key = os.environ["GOOGLE_API_KEY"]
    # only models that are broadly available on AI-Studio keys (no deprecated 1.5 -> avoids 404s)
    candidates = [model, os.environ.get("GEMINI_MODEL", ""), "gemini-2.0-flash",
                  "gemini-2.5-flash", "gemini-2.0-flash-lite", "gemini-flash-latest"]
    seen, ordered = set(), []
    for c in candidates:
        if c and c not in seen:
            seen.add(c); ordered.append(c)
    last_err = None
    for m in ordered:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={key}"
        for attempt in range(2):                       # retry transient 503 "high demand"
            try:
                d = _post(url, {}, {"contents": [{"parts": [{"text": prompt}]}]})
                return d["candidates"][0]["content"]["parts"][0]["text"], 0.0
            except urllib.error.HTTPError as e:
                code = e.code
                try:
                    msg = json.loads(e.read().decode()).get("error", {}).get("message", "")[:100]
                except Exception:
                    msg = ""
                last_err = f"{m}: {code} {msg}"
                if code == 503 and attempt == 0:
                    _t.sleep(1.5); continue            # transient -> retry same model once
                break                                   # 404/400 -> next model
            except Exception as e:
                last_err = f"{m}: {e}"; break
    raise RuntimeError(f"all gemini models failed ({last_err}). Available: {google_models()[:8]}")  # usage parsing omitted; cheap


def _deepseek(model, prompt):
    d = _post("https://api.deepseek.com/chat/completions",
              {"Authorization": f"Bearer {os.environ['DEEPSEEK_API_KEY']}"},
              {"model": model, "messages": [{"role": "user", "content": prompt}]})
    return d["choices"][0]["message"]["content"], 0.0


def _local(model, prompt):
    host = _ollama_host()
    d = _post(f"{host}/api/generate", {}, {"model": model, "prompt": prompt, "stream": False})
    return d.get("response", ""), 0.0


DEFAULT_MODELS = {
    "local": lambda: os.environ.get("OLLAMA_MODEL", "llama3.1"),
    "deepseek": lambda: "deepseek-chat",
    "google": lambda: os.environ.get("GEMINI_MODEL", "gemini-2.0-flash") or "gemini-2.0-flash",
    "openai": lambda: "gpt-4o-mini",
    "claude": lambda: "claude-haiku-4-5-20251001",
}

FALLBACK_ORDER = ("local", "deepseek", "google", "openai", "claude")


def provider_for_model(model):
    m = (model or "").lower()
    if "claude" in m:
        return "claude"
    if "gemini" in m:
        return "google"
    if "deepseek" in m:
        return "deepseek"
    if m.startswith(("gpt-", "o1", "o3", "o4")):
        return "openai"
    if m:
        return "local"
    return "claude"


def _record_operation(project, operation, task_class, provider, model, prompt, cost, latency_ms, ok=True, error=""):
    """Best-effort telemetry so routing decisions are visible and reviewable."""
    try:
        import db
        db.insert("app_operations", {
            "app": project or "orchestrator",
            "operation": operation or "completion",
            "task_class": task_class or "unknown",
            "provider": provider,
            "model": model,
            "prompt_chars": len(prompt or ""),
            "cost_usd": float(cost or 0),
            "latency_ms": int(latency_ms or 0),
            "ok": bool(ok),
        })
    except Exception:
        pass


def _call_provider(provider, model, prompt, project=None, timeout=90):
    if provider == "claude":
        import claude_cli
        r = claude_cli.run(prompt, model, project=project, max_turns=1, permission=None, timeout=timeout)
        return {"text": r["text"], "cost_usd": r["cost_usd"], "provider": provider, "model": model}
    fn = {"openai": _openai, "google": _google, "deepseek": _deepseek, "local": _local}[provider]
    text, cost = fn(model, prompt)
    try:
        import usage_meter
        usage_meter.record(provider, project, usd=cost)
    except Exception:
        pass
    return {"text": text, "cost_usd": cost, "provider": provider, "model": model}


def _fallbacks(first_provider):
    seen = {first_provider}
    for prov in FALLBACK_ORDER:
        if prov in seen or prov not in available():
            continue
        seen.add(prov)
        yield prov, DEFAULT_MODELS[prov]()


def complete(provider, model, prompt, project=None, timeout=90, operation="completion",
             task_class="unknown", fallback=True, record_op=True):
    """Non-agentic completion via any provider (for QA/review/rating/planning)."""
    attempts = [(provider, model)] + (list(_fallbacks(provider)) if fallback else [])
    last = None
    for prov, mdl in attempts:
        t0 = time.time()
        try:
            res = _call_provider(prov, mdl, prompt, project=project, timeout=timeout)
            latency = int((time.time() - t0) * 1000)
            if record_op:
                _record_operation(project, operation, task_class, res["provider"], res["model"],
                                  prompt, res.get("cost_usd", 0), latency, ok=True)
            if last:
                res["fallback_from"] = last.get("provider")
                res["fallback_error"] = last.get("error")
            return res
        except Exception as e:
            latency = int((time.time() - t0) * 1000)
            last = {"provider": prov, "model": mdl, "error": str(e)}
            if record_op:
                _record_operation(project, operation, task_class, prov, mdl, prompt, 0, latency,
                                  ok=False, error=str(e))
            continue
    return {"text": "", "cost_usd": 0, "provider": provider, "model": model,
            "error": (last or {}).get("error", "no provider attempted")}


def complete_legacy(provider, model, prompt, project=None, timeout=90):
    """Backward-compatible no-fallback/no-telemetry path for old callers that need it."""
    try:
        return _call_provider(provider, model, prompt, project=project, timeout=timeout)
    except Exception as e:
        return {"text": "", "cost_usd": 0, "provider": provider, "model": model, "error": str(e)}


if __name__ == "__main__":
    print("available providers:", available())
