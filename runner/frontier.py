#!/usr/bin/env python3
"""frontier.py — frontier-grade reasoning on SUBSCRIPTION capacity, at $0 marginal cost.

THE FINDING THIS ENCODES (2026-09-11). The expert subsystem (corps, gauntlet, docket,
committees) was routing 90%+ of its seats to llama3.1:8b because every hosted API account was
exhausted and the `claude` provider had been sitting in a permanent "exhaustion" demotion since
2026-08-17. Meanwhile the machine holds a Claude Max subscription whose headless CLI runs
Fable 5.1 and Opus 5 at zero billable cost, and a ChatGPT subscription whose `codex exec` runs
GPT-5.5 the same way. The constraint on those is a RATE LIMIT, not dollars — so the right
accounting unit here is tokens-per-window, and the right engineering is to make each call
carry almost nothing but the actual reasoning.

WHAT A LEAN CALL IS. A default `claude -p` call drags the whole Claude Code system prompt plus
every configured MCP server's tool definitions into context: measured 31,824 -> 59,668 tokens of
cache-creation for a four-token answer. With `--strict-mcp-config` (empty server set),
`--setting-sources ""`, `--tools ""` and an explicit `--system-prompt`, the same answer costs
768 tokens. That is a 40-80x reduction in what each expert seat consumes against the weekly
limit — which is what makes running a frontier model on EVERY tournament affordable.

WHAT IT STILL GOES THROUGH. Every Claude call here is made via claude_cli.run(), so the kill
switch, the hourly circuit breaker, usage metering and subscription tracking all still apply;
this module only adds (a) the lean argument set, (b) a token budget with a cooldown that trips
on rate-limit signals so a limited account degrades to local models instead of hammering the
limit, and (c) web-grounded research (`WebSearch`/`WebFetch`) when the caller asks for it —
the model opens the statute, the rule, the opinion, and cites the URL it actually read.

TIERS (need -> model): 9+ Fable 5.1 (chair, red team, research synthesis, novel questions);
7-8 Opus 5 (judges, evidence review, doctrine research); 5-6 Sonnet 5 (routine review);
below 5 -> the caller should use a local model (local_complete). Codex (GPT-5.5) is the
cross-vendor adversary: a second opinion from a different model family, which is the one thing
no amount of self-debate inside one model can supply.

FAIL-SOFT. Unavailable, exhausted, or in cooldown -> callers get {"degraded": True} and fall
back to local_complete(). Nothing here raises into a tournament.
"""
from __future__ import annotations
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

HOME = os.environ.get("CLAUDE_ORCH_HOME", os.path.expanduser("~/.claude-orchestrator"))
STATE = os.path.join(HOME, "frontier_budget.json")
EMPTY_MCP = os.path.join(HOME, "empty-mcp.json")

FABLE = os.environ.get("ORCH_FRONTIER_MODEL", "claude-fable-5-1")
OPUS = os.environ.get("ORCH_FRONTIER_MID_MODEL", "claude-opus-5")
SONNET = os.environ.get("ORCH_FRONTIER_LOW_MODEL", "claude-sonnet-5")
CODEX_MODEL = os.environ.get("ORCH_CODEX_MODEL", "gpt-5.5")
CODEX_BIN = os.environ.get("CODEX_BIN", "codex")
CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "claude")
LOCAL_STRONG = os.environ.get("OLLAMA_STRONG_MODEL") or "qwen3.5:27b-mlx"

ENABLED = os.environ.get("ORCH_FRONTIER_ENABLED", "true").lower() not in ("0", "false", "no", "off")
CODEX_ENABLED = os.environ.get("ORCH_CODEX_ENABLED", "true").lower() not in ("0", "false", "no", "off")
TOK_HOUR = int(os.environ.get("ORCH_FRONTIER_TOKENS_PER_HOUR", "600000"))
TOK_DAY = int(os.environ.get("ORCH_FRONTIER_TOKENS_PER_DAY", "3000000"))
CODEX_TOK_DAY = int(os.environ.get("ORCH_CODEX_TOKENS_PER_DAY", "2000000"))
COOLDOWN_MIN = int(os.environ.get("ORCH_FRONTIER_COOLDOWN_MIN", "30"))
NIGHT_MULT = float(os.environ.get("ORCH_FRONTIER_NIGHT_MULT", "2"))
# Budget weights relative to a fresh input token (API price ratios: cache write 1.25x, cache
# read 0.1x, output 5x). The budget is a rate-limit proxy, so it uses the same proportions.
CACHE_CREATE_WEIGHT = float(os.environ.get("ORCH_FRONTIER_CACHE_CREATE_WEIGHT", "1.25"))
CACHE_READ_WEIGHT = float(os.environ.get("ORCH_FRONTIER_CACHE_READ_WEIGHT", "0.1"))
OUTPUT_WEIGHT = float(os.environ.get("ORCH_FRONTIER_OUTPUT_WEIGHT", "5"))

WEB_TOOLS = ("WebSearch", "WebFetch")
NEED_LABELS = {"seat": 6, "review": 7, "judge": 8, "research": 8, "evidence": 8,
               "chair": 9, "redteam": 9, "frontier": 9}
_RATE_PATTERNS = ("usage limit", "rate limit", "hit your", "weekly limit", "too many requests",
                  "overloaded", "\"429\"", "status 429", "quota")

_lock = threading.Lock()


# ── budget state ─────────────────────────────────────────────────────────────────────────────────
def _ensure_home():
    try:
        os.makedirs(HOME, exist_ok=True)
        if not os.path.exists(EMPTY_MCP):
            with open(EMPTY_MCP, "w") as f:
                f.write('{"mcpServers":{}}')
    except Exception:
        pass


def _load():
    _ensure_home()
    try:
        with open(STATE) as f:
            s = json.load(f)
        if isinstance(s, dict):
            s.setdefault("events", []); s.setdefault("codex_events", [])
            s.setdefault("cooldown_until", 0); s.setdefault("cooldown_reason", "")
            s.setdefault("codex_cooldown_until", 0)
            return s
    except Exception:
        pass
    return {"events": [], "codex_events": [], "cooldown_until": 0, "cooldown_reason": "",
            "codex_cooldown_until": 0}


def _save(s):
    try:
        tmp = STATE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(s, f)
        os.replace(tmp, STATE)
    except Exception:
        pass


def _prune(events, horizon=86400):
    cut = time.time() - horizon
    return [e for e in events if isinstance(e, list) and len(e) >= 2 and e[0] >= cut]


def _night_mult():
    try:
        h = datetime.datetime.now().hour
        start = int(os.environ.get("ORCH_NIGHT_START_HOUR", "23"))
        end = int(os.environ.get("ORCH_NIGHT_END_HOUR", "7"))
        in_night = (h >= start or h < end) if start > end else (start <= h < end)
        return NIGHT_MULT if in_night else 1.0
    except Exception:
        return 1.0


def budget():
    s = _load()
    ev = _prune(s.get("events", []))
    cev = _prune(s.get("codex_events", []))
    now = time.time()
    hour = sum(e[1] for e in ev if e[0] >= now - 3600)
    day = sum(e[1] for e in ev)
    cday = sum(e[1] for e in cev)
    mult = _night_mult()
    return {"hour_used": hour, "day_used": day,
            "hour_cap": int(TOK_HOUR * mult), "day_cap": TOK_DAY,
            "remaining_hour": max(0, int(TOK_HOUR * mult) - hour),
            "remaining_day": max(0, TOK_DAY - day),
            "codex_day_used": cday, "codex_day_cap": CODEX_TOK_DAY,
            "codex_remaining_day": max(0, CODEX_TOK_DAY - cday),
            "cooldown_until": s.get("cooldown_until", 0),
            "cooldown_reason": s.get("cooldown_reason", ""),
            "in_cooldown": now < float(s.get("cooldown_until", 0) or 0),
            "codex_in_cooldown": now < float(s.get("codex_cooldown_until", 0) or 0),
            "calls_24h": len(ev), "codex_calls_24h": len(cev),
            "night_multiplier": mult}


def _record(kind, tokens, model, ok, err=""):
    with _lock:
        s = _load()
        key = "codex_events" if kind == "codex" else "events"
        s[key] = _prune(s.get(key, [])) + [[time.time(), int(tokens or 0), model, bool(ok), (err or "")[:120]]]
        _save(s)


def _mark_cooldown(reason, kind="claude"):
    with _lock:
        s = _load()
        until = time.time() + COOLDOWN_MIN * 60
        if kind == "codex":
            s["codex_cooldown_until"] = until
        else:
            s["cooldown_until"] = until
            s["cooldown_reason"] = (reason or "")[:200]
        _save(s)


def _paused():
    try:
        import kill_switch
        return bool(kill_switch.is_paused(None))
    except Exception:
        return False


def available(min_tokens=4000):
    """Can a frontier Claude call be made right now without breaching our own budget?"""
    if not ENABLED or not shutil.which(CLAUDE_BIN):
        return False
    if _paused():
        return False
    b = budget()
    return (not b["in_cooldown"]) and b["remaining_hour"] >= min_tokens and b["remaining_day"] >= min_tokens


def codex_available(min_tokens=4000):
    if not CODEX_ENABLED or not shutil.which(CODEX_BIN):
        return False
    if _paused():
        return False
    b = budget()
    return (not b["codex_in_cooldown"]) and b["codex_remaining_day"] >= min_tokens


def model_for(need):
    """Map a need level (int 1-10 or a role label) to the cheapest frontier model that clears it.
    Returns None below the frontier floor — the caller should use local_complete()."""
    if isinstance(need, str):
        need = NEED_LABELS.get(need.lower(), 7)
    try:
        need = int(need)
    except Exception:
        need = 7
    if need >= 9:
        return FABLE
    if need >= 7:
        return OPUS
    if need >= 5:
        return SONNET
    return None


# ── JSON extraction ──────────────────────────────────────────────────────────────────────────────
def extract_json(text, arr=False):
    """Pull the first balanced JSON object/array out of model text. Tolerates ``` fences."""
    if text is None:
        return None
    if isinstance(text, (dict, list)):
        return text
    t = str(text).strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.S)
    try:
        return json.loads(t)
    except Exception:
        pass
    opener, closer = ("[", "]") if arr else ("{", "}")
    start = t.find(opener)
    while start != -1:
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(t)):
            c = t[i]
            if in_str:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
                continue
            if c == '"':
                in_str = True
            elif c == opener:
                depth += 1
            elif c == closer:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(t[start:i + 1])
                    except Exception:
                        break
        start = t.find(opener, start + 1)
    return None


# ── telemetry ────────────────────────────────────────────────────────────────────────────────────
def _telemetry(project, tag, provider, model, prompt, latency_s, ok, tokens_in=0, tokens_out=0):
    try:
        import db
        db.insert("app_operations", {
            "app": project or "consilium", "operation": tag or "frontier",
            "task_class": "consilium", "provider": provider, "model": model,
            "prompt_chars": len(prompt or ""), "cost_usd": 0.0,
            "latency_ms": int(latency_s * 1000), "ok": bool(ok),
        })
    except Exception:
        pass


# ── Claude (subscription CLI) ────────────────────────────────────────────────────────────────────
def complete(prompt, *, system=None, model=None, need=9, tools=None, max_turns=None,
             json_schema=None, timeout=900, project="consilium", tag="frontier"):
    """One lean frontier call. Returns
    {text, json, model, tokens_in, tokens_out, rc, error, degraded, turns, latency_s}."""
    model = model or model_for(need) or OPUS
    out = {"text": "", "json": None, "model": model, "tokens_in": 0, "tokens_out": 0,
           "rc": None, "error": "", "degraded": False, "turns": 0, "latency_s": 0.0}
    if not available():
        out.update(error="frontier unavailable (disabled, paused, cooldown or budget)",
                   degraded=True, budget=budget())
        return out
    _ensure_home()
    extra = ["--no-session-persistence", "--strict-mcp-config", "--mcp-config", EMPTY_MCP,
             "--setting-sources", ""]
    if tools:
        extra += ["--tools", ",".join(tools), "--allowedTools", ",".join(tools)]
    else:
        extra += ["--tools", ""]
    if system:
        extra += ["--system-prompt", system]
    if json_schema:
        extra += ["--json-schema", json_schema if isinstance(json_schema, str) else json.dumps(json_schema)]
    turns = max_turns or (12 if tools else 1)
    t0 = time.time()
    try:
        import claude_cli
        r = claude_cli.run(prompt, model, project=project, max_turns=turns, permission=None,
                           timeout=timeout, sandbox=True, extra_args=extra)
    except Exception as e:  # CircuitOpen, timeout, missing binary ...
        out.update(error=f"{type(e).__name__}: {str(e)[:200]}", degraded=True)
        if "timeout" not in type(e).__name__.lower():
            _record("claude", 0, model, ok=False, err=str(e))
        return out
    lat = time.time() - t0
    raw = r.get("raw") if isinstance(r.get("raw"), dict) else {}
    usage = raw.get("usage") or {}
    # COST-WEIGHTED TOKENS (2026-09-12). A multi-turn research call re-reads its whole context
    # every turn, so raw cache_read dominates (measured: 255K raw in for a 18-turn tournament,
    # of which ~90% was cache reads). Cache reads are priced at ~10% of fresh input and rate
    # limits weight them accordingly, so the budget counts them at CACHE_READ_WEIGHT; raw
    # figures are still returned to the caller for the audit trail.
    fresh = int(r.get("input_tokens") or 0)
    cc = int(usage.get("cache_creation_input_tokens") or 0)
    cr = int(usage.get("cache_read_input_tokens") or 0)
    tin = fresh + cc + cr
    tin_weighted = int(fresh + cc * CACHE_CREATE_WEIGHT + cr * CACHE_READ_WEIGHT)
    tout = int(r.get("output_tokens") or 0)
    text = r.get("text") or ""
    if not isinstance(text, str):
        text = json.dumps(text)
    rc = r.get("returncode")
    stderr = r.get("stderr") or ""
    err = ""
    if r.get("skipped"):
        err = f"skipped: {r.get('skipped')}"
    elif (rc not in (0, None)) or raw.get("is_error"):
        err = (text or stderr)[:300] or f"rc={rc}"
        blob = (text + " " + stderr).lower()
        if any(p in blob for p in _RATE_PATTERNS):
            _mark_cooldown(err)
    parsed = None
    if raw.get("structured_output") is not None:
        parsed = raw["structured_output"]
    elif json_schema:
        parsed = extract_json(text)
    _record("claude", tin_weighted + tout * OUTPUT_WEIGHT, model, ok=not err, err=err)
    _telemetry(project, tag, "claude", model, prompt, lat, ok=not err, tokens_in=tin, tokens_out=tout)
    out.update(text=text, json=parsed, tokens_in=tin, tokens_out=tout, tokens_weighted=tin_weighted + tout * OUTPUT_WEIGHT,
               cache_read=cr, cache_create=cc, rc=rc, error=err,
               degraded=bool(err), turns=int(raw.get("num_turns") or 0), latency_s=round(lat, 1))
    return out


# ── Codex (ChatGPT subscription CLI) — the cross-vendor adversary ────────────────────────────────
def codex_complete(prompt, *, system=None, model=None, json_schema=None, timeout=900,
                   project="consilium", tag="codex"):
    model = model or CODEX_MODEL
    out = {"text": "", "json": None, "model": model, "provider": "openai-codex", "tokens_in": 0,
           "tokens_out": 0, "rc": None, "error": "", "degraded": False, "latency_s": 0.0}
    if not codex_available():
        out.update(error="codex unavailable (disabled, missing, paused, cooldown or budget)", degraded=True)
        return out
    tmp = tempfile.mkdtemp(prefix="orch-codex-")
    schema_path = None
    try:
        args = [CODEX_BIN, "exec", "--skip-git-repo-check", "-s", "read-only", "-m", model,
                "-c", "mcp_servers={}", "-c", 'model_reasoning_effort="high"', "--json"]
        # NOTE: --ephemeral combined with --output-schema makes codex 0.145 fail the turn
        # (item error + turn.failed) — measured 2026-09-12; each flag works alone. Sessions
        # therefore persist under ~/.codex/sessions, which is harmless.
        if json_schema:
            schema_path = os.path.join(tmp, "schema.json")
            with open(schema_path, "w") as f:
                f.write(json_schema if isinstance(json_schema, str) else json.dumps(json_schema))
            args += ["--output-schema", schema_path]
        args.append("-")
        full = (system.rstrip() + "\n\n" if system else "") + prompt
        t0 = time.time()
        proc = subprocess.run(args, input=full, cwd=tmp, capture_output=True, text=True, timeout=timeout)
        lat = time.time() - t0
        text, tin, tout = "", 0, 0
        for line in (proc.stdout or "").splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                ev = json.loads(line)
            except Exception:
                continue
            if ev.get("type") == "item.completed":
                it = ev.get("item") or {}
                if it.get("type") == "agent_message" and it.get("text"):
                    text = it["text"]
            elif ev.get("type") == "turn.completed":
                u = ev.get("usage") or {}
                tin += int(u.get("input_tokens") or 0) + int(u.get("cached_input_tokens") or 0)
                tout += int(u.get("output_tokens") or 0) + int(u.get("reasoning_output_tokens") or 0)
        err = ""
        if proc.returncode != 0 or not text:
            err = ((proc.stderr or "")[-300:] or f"rc={proc.returncode}").strip()
            blob = ((proc.stderr or "") + (proc.stdout or "")).lower()
            if any(p in blob for p in _RATE_PATTERNS):
                _mark_cooldown(err, kind="codex")
        _record("codex", tin + tout, model, ok=not err, err=err)
        _telemetry(project, tag, "openai-codex", model, prompt, lat, ok=not err)
        out.update(text=text, json=extract_json(text) if (json_schema and text) else None,
                   tokens_in=tin, tokens_out=tout, rc=proc.returncode, error=err,
                   degraded=bool(err), latency_s=round(lat, 1))
        return out
    except Exception as e:
        out.update(error=f"{type(e).__name__}: {str(e)[:200]}", degraded=True)
        return out
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ── local strong model (free, always-on fallback) ────────────────────────────────────────────────
def local_complete(prompt, model=None, timeout=600, project="consilium", tag="local"):
    model = model or LOCAL_STRONG
    try:
        import model_gateway
        r = model_gateway.complete("local", model, prompt, project=project, timeout=timeout,
                                   operation=tag, task_class="consilium", fallback=True)
        return {"text": r.get("text") or "", "json": None, "model": r.get("model") or model,
                "provider": "local", "error": r.get("error") or "", "degraded": False}
    except Exception as e:
        return {"text": "", "json": None, "model": model, "provider": "local",
                "error": f"{type(e).__name__}: {str(e)[:160]}", "degraded": True}


def route_json(prompt, need=7, *, system=None, arr=False, tools=None, json_schema=None,
               max_turns=None, project="consilium", tag="route"):
    """The drop-in for the old `_json()` helpers: frontier when the need clears the floor and the
    budget allows; strong local otherwise. Always returns a dict/list (possibly empty)."""
    empty = [] if arr else {}
    m = model_for(need)
    if m and available():
        r = complete(prompt, system=system, model=m, tools=tools, max_turns=max_turns,
                     json_schema=json_schema, project=project, tag=tag)
        j = r.get("json")
        if j is None and r.get("text"):
            j = extract_json(r["text"], arr=arr)
        if j is not None and not r.get("error"):
            return j
    r = local_complete(prompt, project=project, tag=tag)
    j = extract_json(r.get("text") or "", arr=arr)
    return j if j is not None else empty


def status():
    b = budget()
    b.update({"enabled": ENABLED, "claude_bin": shutil.which(CLAUDE_BIN) or None,
              "codex_enabled": CODEX_ENABLED, "codex_bin": shutil.which(CODEX_BIN) or None,
              "models": {"frontier": FABLE, "mid": OPUS, "low": SONNET, "codex": CODEX_MODEL,
                         "local_strong": LOCAL_STRONG},
              "available": available(), "codex_available": codex_available()})
    return b


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "probe":
        r = complete("Reply with exactly: OK", system="Terse.", need=7, max_turns=1)
        print(json.dumps({k: r[k] for k in ("text", "model", "tokens_in", "tokens_out", "error", "latency_s")}))
    elif len(sys.argv) > 1 and sys.argv[1] == "probe-codex":
        r = codex_complete("Reply with exactly: OK")
        print(json.dumps({k: r[k] for k in ("text", "model", "tokens_in", "tokens_out", "error", "latency_s")}))
    else:
        print(json.dumps(status(), indent=2, default=str))
