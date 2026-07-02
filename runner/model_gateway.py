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
import os, sys, json, urllib.request, urllib.error
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

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


def _ollama_up():
    """Auto-detect a running Ollama on the default host (no OLLAMA_HOST needed)."""
    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
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
    if os.environ.get("OLLAMA_HOST", "").strip() or _ollama_up(): prov.append("local")
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
    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    d = _post(f"{host}/api/generate", {}, {"model": model, "prompt": prompt, "stream": False})
    return d.get("response", ""), 0.0


def complete(provider, model, prompt, project=None, timeout=90):
    """Non-agentic completion via any provider (for QA/review/rating/planning)."""
    try:
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
    except Exception as e:
        return {"text": "", "cost_usd": 0, "provider": provider, "model": model, "error": str(e)}


if __name__ == "__main__":
    print("available providers:", available())
