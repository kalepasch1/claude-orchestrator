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
import os, sys, json, time, subprocess, urllib.request, urllib.error
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import provider_credentials


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
provider_credentials.activate_aliases()

# rough $/1M tokens (input,output) for routing decisions; edit to current pricing
PRICES = {
    ("claude", "claude-haiku-4-5-20251001"): (1.0, 5.0),
    ("claude", "claude-sonnet-5"): (3.0, 15.0),
    ("claude", "claude-opus-4-8"): (5.0, 25.0),
    ("claude", "claude-fable-5"): (10.0, 50.0),
    ("openai", "gpt-5.6-sol"): (5.0, 30.0),
    ("openai", "gpt-5.6-terra"): (2.50, 15.0),
    ("openai", "gpt-5.6-luna"): (1.0, 6.0),
    ("openai", "gpt-5.5"): (5.0, 30.0),
    ("openai", "gpt-5.5-pro"): (30.0, 180.0),
    ("openai", "gpt-5.4-mini"): (0.75, 4.50),
    ("openai", "gpt-5.4-nano"): (0.20, 1.25),
    ("openai", "o4-mini"): (1.1, 4.4),
    ("openai", "gpt-4o-mini"): (0.15, 0.6),
    ("openai", "gpt-4o"): (2.5, 10.0),
    ("google", "gemini-3.5-flash"): (1.50, 9.0),
    ("google", "gemini-3.1-pro"): (2.0, 12.0),
    ("google", "gemini-3.1-flash-lite"): (0.25, 1.50),
    ("google", "gemini-3-flash"): (0.50, 3.0),
    ("google", "gemini-2.5-pro"): (1.25, 10.0),
    ("google", "gemini-2.5-flash"): (0.30, 2.50),
    ("deepseek", "deepseek-v4-flash"): (0.14, 0.28),
    ("deepseek", "deepseek-v4-pro"): (0.435, 0.87),
    ("deepseek", "deepseek-chat"): (0.14, 0.28),
    ("deepseek", "deepseek-reasoner"): (0.14, 0.28),
    ("local", "*"): (0.0, 0.0),
    ("groq", "llama-3.1-8b-instant"): (0.05, 0.08),
    ("groq", "llama-3.3-70b-versatile"): (0.59, 0.79),
    ("xai", "grok-4.5"): (2.0, 6.0),
    ("xai", "grok-4.3"): (1.25, 2.50),
    ("xai", "grok-4.20"): (1.25, 2.50),
    ("xai", "grok-build-0.1"): (1.00, 2.00),
}


def _ollama_host():
    raw = os.environ.get("OLLAMA_HOST", "http://localhost:11434").strip()
    # tolerate accidental notes like "http://localhost:11434 + ollama pull model"
    return raw.split()[0] if raw else "http://localhost:11434"


def _configured(name, default, deprecated=()):
    value = os.environ.get(name, "").strip()
    if value and not any(value.startswith(prefix) for prefix in deprecated):
        return value
    return default


def _ollama_up():
    """Auto-detect a running Ollama on the default host (no OLLAMA_HOST needed)."""
    host = _ollama_host()
    try:
        urllib.request.urlopen(host + "/api/tags", timeout=1.5)
        return True
    except Exception:
        # Some macOS/sandboxed Python contexts deny urllib localhost access while curl
        # is still allowed. Use curl as a second probe so free local routing is visible.
        try:
            if subprocess.run(["curl", "-sf", host + "/api/tags"],
                              capture_output=True, timeout=2).returncode == 0:
                return True
        except Exception:
            pass
        if (os.environ.get("OLLAMA_HOST") or os.environ.get("OLLAMA_MODEL")) and os.environ.get("ORCH_ASSUME_CONFIGURED_OLLAMA", "true").lower() in ("1", "true", "yes", "on"):
            return True
        return False


def configured():
    """Providers with local configuration present, regardless of health."""
    prov = ["claude"]
    # a key counts only if it's non-empty (blank .env lines don't enable a provider)
    if provider_credentials.has("openai"): prov.append("openai")
    if provider_credentials.has("google"): prov.append("google")
    if provider_credentials.has("deepseek"): prov.append("deepseek")
    if provider_credentials.has("groq"): prov.append("groq")
    if provider_credentials.has("xai"): prov.append("xai")
    if _ollama_up(): prov.append("local")
    return prov


def available():
    """Configured providers currently eligible for traffic."""
    providers = configured()
    try:
        import provider_failover_sla
        return [p for p in providers if not provider_failover_sla.is_demoted(p)]
    except Exception:
        return providers


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
    candidates = [model, os.environ.get("GEMINI_MODEL", ""),
                  os.environ.get("GEMINI_CHEAP_MODEL", ""),
                  os.environ.get("GEMINI_STRONG_MODEL", ""),
                  "gemini-2.5-flash", "gemini-2.5-flash-lite-preview-09-2025",
                  "gemini-flash-latest"]
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


def _local(model, prompt, timeout=90):
    host = _ollama_host()
    if not model:
        try:
            import ollama_catalog
            model = (ollama_catalog.best("completion", need=5) or {}).get("model") or os.environ.get("OLLAMA_MODEL", "llama3.1")
        except Exception:
            model = os.environ.get("OLLAMA_MODEL", "llama3.1")
    # Cap the context window: without an explicit num_ctx Ollama uses the Modelfile default,
    # which for large coders (qwen3-coder:30b) balloons KV cache to ~2x model size (observed
    # 44GB resident on 2026-07-10) and drives the sentinel ram-clamp thrash. Gateway prompts
    # are short, so a modest window loses nothing. ORCH_OLLAMA_NUM_CTX=0 disables the cap.
    try:
        num_ctx = int(os.environ.get("ORCH_OLLAMA_NUM_CTX", "16384"))
    except ValueError:
        num_ctx = 16384
    body = {"model": model, "prompt": prompt, "stream": False,
            "keep_alive": os.environ.get("ORCH_OLLAMA_KEEP_ALIVE", "0")}
    if num_ctx > 0:
        body["options"] = {"num_ctx": num_ctx}
    try:
        import local_model_slots
        with local_model_slots.slot(model, operation="local_completion"):
            d = _post(f"{host}/api/generate", {}, body, timeout=timeout)
    except Exception:
        d = _post(f"{host}/api/generate", {}, body, timeout=timeout)
    return d.get("response", ""), 0.0


DEFAULT_MODELS = {
    "local": lambda: __import__("ollama_catalog").best("fallback", need=5).get("model"),
    "groq": lambda: os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile"),
    "deepseek": lambda: _configured("DEEPSEEK_CHEAP_MODEL", "deepseek-v4-flash",
                                    deprecated=("deepseek-chat", "deepseek-reasoner")),
    "google": lambda: _configured("GEMINI_MODEL", "gemini-3-flash",
                                  deprecated=("gemini-2.0-",)),
    "xai": lambda: os.environ.get("XAI_MODEL", "grok-build-0.1"),
    "openai": lambda: os.environ.get("OPENAI_CHEAP_MODEL", "gpt-5.4-nano"),
    "claude": lambda: "claude-haiku-4-5-20251001",
}

FALLBACK_ORDER = ("local", "groq", "deepseek", "google", "xai", "openai", "claude")


def provider_for_model(model):
    m = (model or "").lower()
    if "claude" in m:
        return "claude"
    if "gemini" in m:
        return "google"
    if "deepseek" in m:
        return "deepseek"
    if "grok" in m:
        return "xai"
    if "llama" in m or "qwen" in m or "mixtral" in m:
        # Groq for cloud inference of open-source models; local for Ollama
        if os.environ.get("GROQ_API_KEY"):
            return "groq"
        return "local"
    if m.startswith(("gpt-", "o1", "o3", "o4", "o5")):
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


def _groq(model, prompt):
    """Groq LPU inference — 10x speed, OpenAI-compatible API."""
    d = _post("https://api.groq.com/openai/v1/chat/completions",
              {"Authorization": f"Bearer {os.environ['GROQ_API_KEY']}"},
              {"model": model, "messages": [{"role": "user", "content": prompt}],
               "max_tokens": 8192})
    u = d.get("usage", {})
    pin, pout = PRICES.get(("groq", model), (0.59, 0.79))
    cost = u.get("prompt_tokens", 0)/1e6*pin + u.get("completion_tokens", 0)/1e6*pout
    return d["choices"][0]["message"]["content"], round(cost, 6)


def _xai(model, prompt):
    """xAI Grok — real-time data, OpenAI-compatible API."""
    d = _post("https://api.x.ai/v1/chat/completions",
              {"Authorization": f"Bearer {provider_credentials.get('xai')}"},
              {"model": model, "messages": [{"role": "user", "content": prompt}],
               "max_tokens": 8192})
    u = d.get("usage", {})
    pin, pout = PRICES.get(("xai", model), (1.25, 2.50))
    cost = u.get("prompt_tokens", 0)/1e6*pin + u.get("completion_tokens", 0)/1e6*pout
    return d["choices"][0]["message"]["content"], round(cost, 6)


def _call_provider(provider, model, prompt, project=None, timeout=90):
    if provider == "claude":
        import claude_cli
        r = claude_cli.run(prompt, model, project=project, max_turns=1, permission=None, timeout=timeout)
        return {"text": r["text"], "cost_usd": r["cost_usd"], "provider": provider, "model": model}
    if provider == "local":
        text, cost = _local(model, prompt, timeout=timeout)
    else:
        fn = {"openai": _openai, "google": _google, "deepseek": _deepseek,
              "groq": _groq, "xai": _xai}[provider]
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


def _confidential_mode():
    return os.environ.get("ORCH_CONFIDENTIAL_MODE", "false").lower() in ("true", "1", "yes")


def _sensitivity(prompt):
    try:
        import privacy
        return privacy.sensitivity(prompt or "")
    except Exception:
        return "standard"


def _provider_allowed(provider, sensitivity):
    try:
        import provider_terms
        return provider_terms.allowed(provider, sensitivity)
    except Exception:
        return sensitivity in ("standard", "public", "routine")


def _learned_route(project, operation, task_class, sensitivity):
    """Best observed app/operation route, guarded by quality, availability, and provider terms."""
    if os.environ.get("ORCH_USE_LEARNED_APP_ROUTES", "true").lower() not in ("1", "true", "yes", "on"):
        return None
    app = project or "orchestrator"
    min_q = float(os.environ.get("ORCH_LEARNED_ROUTE_MIN_QUALITY", "6.5"))
    try:
        import db
        for op in (operation, task_class, "completion"):
            if not op:
                continue
            rows = db.select("app_op_routes", {"select": "*", "app": f"eq.{app}",
                                               "operation": f"eq.{op}",
                                               "order": "updated_at.desc", "limit": "1"}) or []
            if not rows:
                continue
            r = rows[0]
            provider = r.get("provider")
            model = r.get("model")
            if provider not in available():
                continue
            if not _provider_allowed(provider, sensitivity):
                continue
            if float(r.get("avg_quality") or 0) < min_q:
                continue
            return provider, model, f"learned {app}/{op} route q={r.get('avg_quality')}"
    except Exception:
        return None
    return None


def complete(provider, model, prompt, project=None, timeout=90, operation="completion",
             task_class="unknown", fallback=True, record_op=True):
    """Non-agentic completion via any provider (for QA/review/rating/planning)."""
    if _confidential_mode():
        # In confidential mode a prompt may be intentionally scoped for one vendor/local model.
        # Do not resend it to a second provider after a transient failure unless the caller opts out
        # of confidential mode for this process.
        fallback = False
    sensitivity = _sensitivity(prompt)
    learned = _learned_route(project, operation, task_class, sensitivity)
    if learned and learned[0] != provider:
        provider, model, learned_reason = learned
    else:
        learned_reason = ""
    try:
        import prompt_result_cache
        cached = prompt_result_cache.lookup(provider, model, task_class, operation, prompt, sensitivity)
        if cached:
            if learned_reason:
                cached = {**cached, "learned_route": learned_reason}
            if record_op:
                _record_operation(project, operation, task_class, provider, model, prompt, 0.0, 0, ok=True)
            try:
                import savings_meter
                savings_meter.record("prompt_result_cache", prompt=prompt, result_text=cached.get("text"))
            except Exception:
                pass
            return cached
    except Exception:
        pass
    attempts = [(provider, model)] + (list(_fallbacks(provider)) if fallback else [])
    attempts = [(p, m) for p, m in attempts if _provider_allowed(p, sensitivity)]
    if not attempts:
        return {"text": "", "cost_usd": 0, "provider": provider, "model": model,
                "error": f"no provider allowed for sensitivity={sensitivity}"}
    last = None
    for prov, mdl in attempts:
        t0 = time.time()
        try:
            res = _call_provider(prov, mdl, prompt, project=project, timeout=timeout)
            try:
                import provider_failover_sla
                provider_failover_sla.record_probe_success(prov)
            except Exception:
                pass
            latency = int((time.time() - t0) * 1000)
            if record_op:
                _record_operation(project, operation, task_class, res["provider"], res["model"],
                                  prompt, res.get("cost_usd", 0), latency, ok=True)
            try:
                import prompt_result_cache
                prompt_result_cache.store(res["provider"], res["model"], task_class, operation,
                                          prompt, res.get("text"), sensitivity)
            except Exception:
                pass
            if last:
                res["fallback_from"] = last.get("provider")
                res["fallback_error"] = last.get("error")
            if learned_reason:
                res["learned_route"] = learned_reason
            return res
        except Exception as e:
            latency = int((time.time() - t0) * 1000)
            last = {"provider": prov, "model": mdl, "error": str(e)}
            if isinstance(e, urllib.error.HTTPError) and e.code in (401, 403):
                try:
                    import provider_failover_sla
                    provider_failover_sla.demote(prov, f"auth-{e.code}")
                except Exception:
                    pass
            if record_op:
                _record_operation(project, operation, task_class, prov, mdl, prompt, 0, latency,
                                  ok=False, error=str(e))
            continue
    return {"text": "", "cost_usd": 0, "provider": provider, "model": model,
            "error": (last or {}).get("error", "no provider attempted")}


def complete_legacy(provider, model, prompt, project=None, timeout=90):
    """Backward-compatible no-fallback/no-telemetry path for old callers that need it."""
    try:
        result = _call_provider(provider, model, prompt, project=project, timeout=timeout)
        try:
            import provider_failover_sla
            provider_failover_sla.record_probe_success(provider)
        except Exception:
            pass
        return result
    except Exception as e:
        return {"text": "", "cost_usd": 0, "provider": provider, "model": model, "error": str(e)}


if __name__ == "__main__":
    print("available providers:", available())
