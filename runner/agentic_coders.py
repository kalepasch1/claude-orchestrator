#!/usr/bin/env python3
"""
agentic_coders.py - a MULTI-CODER POOL. Any model can be an agentic coder: Claude Code + Codex are
native subscriptions; DeepSeek / Gemini / OpenAI / a LOCAL Ollama model plug in through a headless CLI
(aider works with all of them). The orchestrator routes each task to the cheapest coder whose
capability clears the task's difficulty, so work is always flowing and Claude's subscription capacity
is spent only where it's actually needed. Every coder's output is judged by the SAME cross-model panel
(judge.py) and gated identically, so quality stays uniform.

Configure the pool with ONE env var (JSON list), plus the legacy single-second/third env still works:

    ORCH_EXTRA_CODERS='[
      {"name":"ollama-qwen","cmd":"aider --model ollama/qwen2.5-coder --yes --no-auto-commit --message {prompt}","cost":0,"cap":5},
      {"name":"deepseek","cmd":"aider --model deepseek/deepseek-chat --yes --no-auto-commit --message {prompt}","cost":2,"cap":6,"daily_usd":5,"est_usd":0.02},
      {"name":"gemini","cmd":"aider --model gemini/gemini-2.0-flash --yes --no-auto-commit --message {prompt}","cost":2,"cap":6,"daily_usd":5,"est_usd":0.02},
      {"name":"gpt","cmd":"aider --model openai/gpt-4o-mini --yes --no-auto-commit --message {prompt}","cost":2,"cap":6,"daily_usd":5,"est_usd":0.02}
    ]'

Coder fields: name (shown in outcomes.model), cmd (headless CLI; {prompt}/{model} placeholders),
cost (0=free/local, 1=subscription, 2=paid-API), cap (capability 1-10), daily_usd (soft paid cap; 0=off),
est_usd (nominal $/call used for the daily-cap accounting when the CLI doesn't report cost).
Backward compatible: with no extra coders, behavior is the prior claude -> codex cascade.
"""
import os, sys, json, re, shlex, subprocess, time, hashlib
import contextlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# capability a task needs by difficulty (see _task_difficulty)
_NEED = {"easy": 5, "hard": 8}

# aider prints e.g. "Tokens: 1.2k sent, 500 received. Cost: $0.0021 message, $0.0021 session."
_AIDER_MSG_COST = re.compile(r"cost:\s*\$([0-9.]+)\s*message", re.I)
_AIDER_ANY_COST = re.compile(r"\$([0-9.]+)\s*(?:message|session)", re.I)
_AIDER_OK = None
_HEAVY_RUNNING_CACHE = {"t": 0.0, "counts": {}}
_AIDER_HEADLESS_FLAGS = [
    "--yes-always",
    "--no-auto-commits",
    "--no-show-model-warnings",
    "--no-check-model-accepts-settings",
    "--no-browser",
    "--no-gui",
    "--no-check-update",
    "--no-show-release-notes",
    "--analytics-disable",
    "--no-detect-urls",
    "--no-notifications",
    "--no-gitignore",
    "--no-restore-chat-history",
    "--no-suggest-shell-commands",
    "--no-fancy-input",
    "--no-pretty",
]


def _truthy(name, default=True):
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.lower() in ("1", "true", "yes", "on")


def _aider_available():
    """Return True when the generic headless coding CLI is importable/runnable."""
    global _AIDER_OK
    if _AIDER_OK is not None:
        return _AIDER_OK
    try:
        _AIDER_OK = subprocess.run([sys.executable, "-m", "aider", "--version"],
                                   capture_output=True, timeout=10).returncode == 0
    except Exception:
        _AIDER_OK = False
    return _AIDER_OK


def _aider_cmd(model):
    return (f"{shlex.quote(sys.executable)} -m aider --model {shlex.quote(model)} "
            + " ".join(_AIDER_HEADLESS_FLAGS) + " --message {prompt}")


def _flag_rewrite(cmd, old, new):
    return re.sub(rf"(?<!\S){re.escape(old)}(?=\s|$)", new, cmd)


def _normalize_aider_cmd(cmd):
    """Make any user/env-provided Aider command safe for unattended orchestration.

    Older setup snippets used stale flags (`--yes`, `--no-auto-commit`) and let Aider show model
    warning docs via osascript. Normalize here so even pre-existing ORCH_EXTRA_CODERS entries stop
    opening browser pages and stop failing on current Aider flag names.
    """
    text = str(cmd or "")
    if "aider" not in text:
        return text
    text = _flag_rewrite(text, "--yes", "--yes-always")
    text = _flag_rewrite(text, "--no-auto-commit", "--no-auto-commits")
    text = _flag_rewrite(text, "--browser", "--no-browser")
    text = _flag_rewrite(text, "--gui", "--no-gui")
    tokens = set(re.findall(r"(?<!\S)--[A-Za-z0-9-]+", text))
    add = []
    for flag in _AIDER_HEADLESS_FLAGS:
        positive = "--" + flag.removeprefix("--no-")
        if flag not in tokens and positive not in tokens:
            add.append(flag)
    if add:
        marker = "--message"
        idx = text.find(marker)
        if idx >= 0:
            text = text[:idx].rstrip() + " " + " ".join(add) + " " + text[idx:]
        else:
            text = text.rstrip() + " " + " ".join(add)
    return text


def _aider_env(env=None):
    merged = dict(os.environ)
    if env:
        merged.update(env)
    defaults = {
        "AIDER_SHOW_MODEL_WARNINGS": "false",
        "AIDER_CHECK_MODEL_ACCEPTS_SETTINGS": "false",
        "AIDER_GUI": "false",
        "AIDER_BROWSER": "false",
        "AIDER_CHECK_UPDATE": "false",
        "AIDER_SHOW_RELEASE_NOTES": "false",
        "AIDER_ANALYTICS_DISABLE": "true",
        "AIDER_DETECT_URLS": "false",
        "AIDER_NOTIFICATIONS": "false",
        "AIDER_GITIGNORE": "false",
        "AIDER_RESTORE_CHAT_HISTORY": "false",
        "AIDER_SUGGEST_SHELL_COMMANDS": "false",
        "AIDER_FANCY_INPUT": "false",
        "AIDER_PRETTY": "false",
        "AIDER_TIMEOUT": os.environ.get("ORCH_AIDER_REQUEST_TIMEOUT", "120"),
        "LITELLM_NUM_RETRIES": os.environ.get("ORCH_AIDER_LITELLM_RETRIES", "1"),
        "LITELLM_REQUEST_TIMEOUT": os.environ.get("ORCH_AIDER_REQUEST_TIMEOUT", "120"),
    }
    for k, v in defaults.items():
        merged.setdefault(k, v)
    if "OLLAMA_API_BASE" not in merged:
        merged["OLLAMA_API_BASE"] = merged.get("OLLAMA_HOST") or "http://127.0.0.1:11434"
    if "OLLAMA_HOST" not in merged:
        merged["OLLAMA_HOST"] = merged["OLLAMA_API_BASE"]
    return merged


def _paid_credits_enabled(default=False):
    try:
        import control_flags
        return control_flags.use_purchased_credits(default)
    except Exception:
        return _truthy("ORCH_USE_PAID_AGENTIC_CREDITS", default)


def _explicit_full_offload_requested():
    """A 100% offload share is an explicit operator directive to try non-Claude value coders."""
    for name in ("ORCH_EASY_OFFLOAD_SHARE", "ORCH_HARD_OFFLOAD_SHARE", "ORCH_CRITICAL_NON_CLAUDE_SHARE"):
        raw = os.environ.get(name)
        if raw is None:
            continue
        try:
            if float(raw) >= 1.0:
                return True
        except ValueError:
            pass
    return False


def _auto_coders():
    """Provider-key driven agentic coders. No manual ORCH_EXTRA_CODERS required."""
    if not _truthy("ORCH_AUTO_AGENTIC_CODERS", True) or not _aider_available():
        return []
    try:
        import model_gateway
        available = set(model_gateway.available())
    except Exception:
        available = set()
    paid_enabled = (_paid_credits_enabled(_truthy("ORCH_USE_PAID_AGENTIC_CREDITS", False))
                    or _explicit_full_offload_requested())
    paid_cap = float(os.environ.get("ORCH_PAID_AGENTIC_DAILY_USD", "25") or 25)
    coders = []
    if "local" in available:
        try:
            import ollama_catalog
            locals_ = ollama_catalog.candidates()
        except Exception:
            locals_ = [{"model": os.environ.get("OLLAMA_MODEL", "llama3.1"),
                        "cap": int(os.environ.get("ORCH_LOCAL_AGENTIC_CAP", "5"))}]
        for idx, lc in enumerate(sorted(locals_, key=lambda c: (-int(c.get("cap") or 0), c.get("model") or ""))[:4]):
            name = "ollama" if idx == 0 else f"ollama-{idx + 1}"
            coders.append({"name": name, "cmd": _aider_cmd("ollama/" + lc["model"]),
                           "cost": 0, "cap": int(lc.get("cap") or 5),
                           "daily_usd": 0, "est_usd": 0.0})
    if not paid_enabled:
        return coders
    if "deepseek" in available:
        coders.append({"name": "deepseek", "cmd": _aider_cmd("deepseek/" + os.environ.get("DEEPSEEK_AGENTIC_MODEL", "deepseek-v4-flash")),
                       "cost": 2, "cap": int(os.environ.get("DEEPSEEK_AGENTIC_CAP", "7")), "daily_usd": paid_cap, "est_usd": 0.02})
    if "google" in available:
        coders.append({"name": "gemini", "cmd": _aider_cmd("gemini/" + (os.environ.get("GEMINI_AGENTIC_MODEL") or os.environ.get("GEMINI_MODEL") or "gemini-2.5-flash")),
                       "cost": 2, "cap": int(os.environ.get("GEMINI_AGENTIC_CAP", "8")), "daily_usd": paid_cap, "est_usd": 0.02})
    if "openai" in available:
        coders.append({"name": "gpt-mini", "cmd": _aider_cmd("openai/" + os.environ.get("OPENAI_CHEAP_AGENTIC_MODEL", "gpt-5.4-mini")),
                       "cost": 2, "cap": 7, "daily_usd": paid_cap, "est_usd": 0.03})
        coders.append({"name": "gpt", "cmd": _aider_cmd("openai/" + os.environ.get("OPENAI_AGENTIC_MODEL", "gpt-5.5")),
                       "cost": 3, "cap": int(os.environ.get("OPENAI_AGENTIC_CAP", "9")), "daily_usd": paid_cap, "est_usd": 0.10})
    return coders


def _parse_cost(text):
    """Extract the REAL $ cost from aider's output (prefer the per-message cost, else the last cost
    figure). Returns None if the CLI reported nothing, so callers fall back to the nominal estimate."""
    t = text or ""
    m = _AIDER_MSG_COST.search(t)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass
    hits = _AIDER_ANY_COST.findall(t)
    if hits:
        try:
            return float(hits[-1])
        except ValueError:
            pass
    return None


def _pool():
    """Build the ordered coder pool from env. Native subscriptions first, then configured extras.
    Fail-soft: a malformed ORCH_EXTRA_CODERS entry is skipped, never crashes the picker."""
    pool = [{"name": "claude", "cmd": None, "cost": 1, "cap": 10, "daily_usd": 0, "est_usd": 0.0}]
    pool.extend(_auto_coders())
    second = os.environ.get("ORCH_SECOND_CODER")
    if second and os.environ.get("ORCH_SECOND_CODER_CMD"):
        pool.append({"name": second, "cmd": os.environ["ORCH_SECOND_CODER_CMD"],
                     "cost": 1, "cap": 8, "daily_usd": 0, "est_usd": 0.0})   # Codex = subscription, capable
    third = os.environ.get("ORCH_THIRD_CODER")
    if third and os.environ.get("ORCH_THIRD_CODER_CMD"):
        pool.append({"name": third, "cmd": os.environ["ORCH_THIRD_CODER_CMD"], "cost": 2, "cap": 6,
                     "daily_usd": float(os.environ.get("ORCH_THIRD_CODER_DAILY_USD", "0") or 0), "est_usd": 0.02})
    try:
        for c in json.loads(os.environ.get("ORCH_EXTRA_CODERS", "[]") or "[]"):
            if not c.get("name") or not c.get("cmd"):
                continue
            pool.append({"name": c["name"], "cmd": c["cmd"],
                         "cost": int(c.get("cost", 2)), "cap": int(c.get("cap", 6)),
                         "daily_usd": float(c.get("daily_usd", 0) or 0), "est_usd": float(c.get("est_usd", 0.02) or 0)})
    except Exception as e:
        print(f"agentic_coders: bad ORCH_EXTRA_CODERS ({e}) — ignoring extras")
    # SAFETY / SELF-HEALING: only keep a coder whose CLI is installed AND whose provider (key or local
    # server) is actually reachable. Without this, configuring a coder before its cred/server exists would
    # route real tasks to a backend that instantly fails on every call — turning "no cheap models" into
    # "broken tasks + tanked throughput". Each cheap coder (ollama/gemini/deepseek/gpt) therefore lights
    # up automatically the moment its key/server appears, and drops out the moment it's gone. Native
    # claude (cmd=None) is never pruned. All checks cached (~60s) so this hot path stays cheap.
    pool = [c for c in pool if _coder_ready(c.get("cmd"))]
    # de-dupe by name, keep first (native wins)
    seen, uniq = set(), []
    for c in pool:
        if c["name"] in seen:
            continue
        seen.add(c["name"]); uniq.append(c)
    return uniq


_CLI_CACHE = {}


def _cli_present(name):
    """Is a CLI on PATH? Cached ~60s so _pool() (hot path) doesn't shell out on every call."""
    import time as _t
    hit = _CLI_CACHE.get(name)
    if hit and _t.time() - hit[0] < 60:
        return hit[1]
    import shutil
    ok = bool(shutil.which(name))
    _CLI_CACHE[name] = (_t.time(), ok)
    return ok


def _ollama_up():
    """Is a local Ollama server reachable? Cached ~60s. Used to prune the free ollama coder when the
    server is down, so easy tasks don't all fail on it before switching coders."""
    import time as _t
    hit = _CLI_CACHE.get("__ollama__")
    if hit and _t.time() - hit[0] < 60:
        return hit[1]
    ok = False
    try:
        import urllib.request
        base = (os.environ.get("OLLAMA_API_BASE") or os.environ.get("OLLAMA_HOST")
                or "http://127.0.0.1:11434")
        if not base.startswith("http"):
            base = "http://" + base
        urllib.request.urlopen(base.rstrip("/") + "/api/tags", timeout=1.5)
        ok = True
    except Exception:
        ok = False
    _CLI_CACHE["__ollama__"] = (_t.time(), ok)
    return ok


def _coder_ready(cmd):
    """A coder is usable only if its CLI is installed AND its provider is reachable (key present /
    local server up). Native coders (cmd falsy) are always ready. Prevents routing tasks to a backend
    that would fail every call. Unknown providers are assumed ready (fail-open, never over-prune)."""
    cmd = str(cmd or "").strip()
    if not cmd:
        return True                                  # native (claude)
    if not _cli_present(cmd.split()[0]):
        return False                                 # e.g. aider not installed yet
    low = cmd.lower()
    if "ollama/" in low:
        return _ollama_up()                          # free/local — never gated by the $ ceiling
    # PAID providers below: also require the global real-spend ceiling not be reached, so paid coders
    # go dormant once total real spend hits ORCH_REAL_USD_MONTH_CAP ($200) — subscription/free work
    # keeps running, only real spending pauses for approval.
    def _paid_ok():
        try:
            import budget
            return budget.paid_allowed()
        except Exception:
            return True
    if "deepseek/" in low:
        return bool(os.environ.get("DEEPSEEK_API_KEY")) and _paid_ok()
    if "gemini/" in low or "google/" in low:
        return bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")) and _paid_ok()
    if "openai/" in low or "gpt-" in low:
        return bool(os.environ.get("OPENAI_API_KEY")) and _paid_ok()
    return True


def available():
    """List configured agentic coder names ('claude' always present)."""
    return [c["name"] for c in _pool()]


def _spec(name):
    for c in _pool():
        if c["name"] == name:
            return c
    return None


def _within_cap(coder):
    """A paid coder (daily_usd>0) is usable only while today's spend on it is under its cap. Free/local
    and subscription coders (daily_usd<=0) are always within cap."""
    cap = float(coder.get("daily_usd") or 0)
    if cap <= 0:
        return True
    try:
        import db, datetime
        since = datetime.date.today().isoformat()
        rows = db.select("outcomes", {"select": "usd", "created_at": f"gte.{since}",
                                      "model": f"eq.{coder['name']}"}) or []
        return sum(float(r.get("usd") or 0) for r in rows) < cap
    except Exception:
        return True  # fail-open within the day; per-call cost stays small


def _heavy_ollama_model(coder):
    try:
        import local_model_slots
        model = _ollama_model_for(coder, "")
        if model and local_model_slots.is_heavy(model):
            return model
    except Exception:
        pass
    return ""


def _heavy_running_counts():
    now = time.time()
    if now - _HEAVY_RUNNING_CACHE["t"] < 10:
        return dict(_HEAVY_RUNNING_CACHE["counts"])
    counts = {}
    try:
        import db
        rows = db.select("tasks", {"select": "model,note", "state": "eq.RUNNING", "limit": "120"}) or []
        for r in rows:
            text = f"{r.get('model') or ''} {r.get('note') or ''}".lower()
            if "ollama/" not in text and "ollama:" not in text and "draft: ollama" not in text:
                continue
            for spec in _pool():
                model = _heavy_ollama_model(spec)
                if model and model.lower() in text:
                    counts[model] = counts.get(model, 0) + 1
    except Exception:
        counts = {}
    _HEAVY_RUNNING_CACHE.update({"t": now, "counts": counts})
    return dict(counts)


def _heavy_ollama_saturated(coder):
    model = _heavy_ollama_model(coder)
    if not model:
        return False
    try:
        cap = int(os.environ.get("ORCH_HEAVY_OLLAMA_RUNNING_CAP", "1") or 1)
    except ValueError:
        cap = 1
    return _heavy_running_counts().get(model, 0) >= max(1, cap)


# kept for backward-compat with any external caller
def _third_within_cap():
    c = _spec(os.environ.get("ORCH_THIRD_CODER", ""))
    return bool(c) and _within_cap(c)


def _task_difficulty(task):
    """Cheap heuristic for whether a lower-intelligence/cheaper model can likely complete this task.
    Material work and anything with dependencies is 'hard' (stays on a capable coder); mechanical/
    bugfix/docs/test kinds, an explicit haiku hint, or a small self-contained prompt are 'easy'."""
    if int(task.get("_need") or 0) >= 9:
        return "critical"
    if int(task.get("_need") or 0) >= 8:
        return "hard"
    kind = str(task.get("kind") or "").lower()
    if kind in ("security", "legal") or any(w in str(task.get("prompt") or "").lower() for w in ("private key", "custody", "regulated", "securities", "hipaa", "soc2")):
        return "critical"
    if task.get("material") or (task.get("deps") or []):
        return "hard"
    if kind in ("mechanical", "chore", "bugfix", "docs", "test", "cleanup", "canary"):
        return "easy"
    if "haiku" in str(task.get("model") or "").lower():
        return "easy"
    if len(str(task.get("prompt") or "")) < 600:
        return "easy"
    return "hard"


def _task_sensitivity(task):
    explicit = str(task.get("sensitivity") or "").strip().lower()
    if explicit:
        return explicit
    try:
        import privacy
        return privacy.sensitivity(" ".join(str(task.get(k) or "") for k in ("prompt", "note", "slug", "kind")))
    except Exception:
        return "standard"


def _allowed_by_terms(coder, sensitivity):
    try:
        import provider_terms
        return provider_terms.allowed(coder.get("name"), sensitivity)
    except Exception:
        return sensitivity in ("standard", "public", "routine")


def _stable_share(task):
    """Deterministic 0..1 from the task id/slug so both machines agree without coordination
    (Python's str hash is process-randomized, so use a stable digest)."""
    key = str(task.get("slug") or task.get("id") or "")
    return (int(hashlib.sha1(key.encode()).hexdigest()[:8], 16) % 1000) / 1000.0


def pick(task, slot_index=0):
    """Choose an agentic coder, optimizing cost x capability x task difficulty.

    - FORCED coder (integrate self-heal) wins when usable.
    - Claude EXHAUSTED: pick the cheapest pooled coder that clears the task's capability need, so the
      fleet keeps completing work on other models (nothing waits for Claude to reset).
    - NORMAL: material/dependency tasks -> Claude (top capability). Otherwise cost-optimize: send a
      large share of EASY tasks to the cheapest capable coder (free/local first) to save subscription
      capacity, and a diversification share of harder-but-safe tasks to the next coder.
    """
    pool = _pool()
    diff = _task_difficulty(task)
    need = int(task.get("_need") or 0) or (9 if diff == "critical" else _NEED[diff])
    sensitivity = _task_sensitivity(task)
    usable = [c for c in pool
              if c["cap"] >= need and _within_cap(c) and _allowed_by_terms(c, sensitivity)
              and not _heavy_ollama_saturated(c)]
    if not usable and sensitivity in ("crown_jewel", "crown-jewel", "crownjewel"):
        # Fail closed toward local-only: prefer any local coder even if it is below ideal cap,
        # instead of leaking crown-jewel context to an external provider.
        local = [c for c in pool if _allowed_by_terms(c, sensitivity) and _within_cap(c)]
        if local:
            usable = sorted(local, key=lambda c: (-c["cap"], c["cost"]))
    def adjusted_cost(c):
        try:
            import model_slashing
            return float(c["cost"]) + model_slashing.penalty_for(c.get("name"))
        except Exception:
            return float(c["cost"])

    by_cost = sorted([c for c in usable if c["name"] != "claude"], key=lambda c: (adjusted_cost(c), -c["cap"]))

    forced = str(task.get("force_coder") or "").strip()
    if forced:
        fc = _spec(forced)
        if forced == "claude" and fc and fc["cap"] >= need and _within_cap(fc) and _allowed_by_terms(fc, sensitivity):
            return "claude"
        if fc and fc["cap"] >= need and _within_cap(fc) and not _heavy_ollama_saturated(fc):
            if _allowed_by_terms(fc, sensitivity):
                return forced
        # forced coder unusable for this task -> fall through to normal selection

    try:
        import account_pool
        exhausted = account_pool.claude_exhausted()
    except Exception:
        exhausted = False

    if exhausted:
        # cheapest capable non-Claude coder; if the task is 'hard' and only weak coders exist, still try
        # the strongest available rather than stall (better an attempt than an idle lane).
        if by_cost:
            return by_cost[0]["name"]
        if diff == "critical":
            return "claude"
        strongest = sorted([c for c in pool if c["name"] != "claude" and _within_cap(c)],
                           key=lambda c: -c["cap"])
        return strongest[0]["name"] if strongest else "claude"

    # LEARNED ROUTER: prefer the coder that empirically converts THIS task-kind to merges most cheaply
    # ($/merge from our own outcomes). Returns None until there's enough signal, so it refines the
    # heuristic rather than fighting it; never overrides material (those stay on Claude below).
    if not task.get("material"):
        try:
            import router_stats
            slug = str(task.get("slug") or "").lower()
            stage = "recovery" if slug.startswith("recover-missing-branch") else None
            rec = router_stats.best_coder(task.get("kind"), [c["name"] for c in usable], stage=stage)
            if rec:
                return rec
        except Exception:
            pass

    # NORMAL state: no task class is hard-coded to Claude. Pick the best capable coder
    # by learned $/merge when available, else by capability-adjusted cost. Critical work
    # may still choose Claude when it is the only cap>=9 backend.
    if task.get("material") or (task.get("deps") or []) or diff == "critical":
        if diff == "critical":
            if by_cost and _paid_credits_enabled(_truthy("ORCH_USE_PAID_AGENTIC_CREDITS", False)):
                try:
                    share = float(os.environ.get("ORCH_CRITICAL_NON_CLAUDE_SHARE", "0.2"))
                except ValueError:
                    share = 0.2
                if _stable_share(task) < share:
                    return by_cost[0]["name"]
            ranked = sorted(usable, key=lambda c: (adjusted_cost(c), -c["cap"]))
            return ranked[0]["name"] if ranked else "claude"
        # Hard/material work needs outcome data from non-Claude coders too. Use a stable
        # exploration share while respecting capability and daily paid caps; router_stats
        # above will take over once there are enough samples.
        if by_cost and _paid_credits_enabled(_truthy("ORCH_USE_PAID_AGENTIC_CREDITS", False)):
            try:
                share = float(os.environ.get("ORCH_HARD_OFFLOAD_SHARE", "0.45"))
            except ValueError:
                share = 0.45
            if _stable_share(task) < share:
                return by_cost[0]["name"]
        ranked = sorted(usable, key=lambda c: (adjusted_cost(c), -c["cap"]))
        return ranked[0]["name"] if ranked else "claude"
    h = _stable_share(task)
    if diff == "easy" and by_cost:
        try:
            share = float(os.environ.get("ORCH_EASY_OFFLOAD_SHARE", "0.6"))
        except ValueError:
            share = 0.6
        if h < share:
            return by_cost[0]["name"]      # cheapest capable coder (free/local first) does easy work
        return "claude"
    # harder-but-safe: keep the modest second-coder diversification for benchmarking/capacity
    try:
        share = float(os.environ.get("ORCH_SECOND_CODER_SHARE", "0.25"))
    except ValueError:
        share = 0.25
    if by_cost and h < share:
        return by_cost[0]["name"]
    return "claude"


def route(task):
    """Structured route metadata for dashboards/policy probes."""
    name = pick(task)
    spec = _spec(name) or {"name": name, "cost": 1, "cap": 10}
    model = "claude" if name == "claude" else name
    if spec.get("cmd"):
        m = re.search(r"--model\s+([^ ]+)", spec["cmd"])
        if m:
            model = m.group(1).strip("'\"")
    elif name == "claude":
        need = int(task.get("_need") or 0)
        if need >= 9:
            model = os.environ.get("ORCH_HARD_MODEL", "claude-opus-4-8")
        elif need >= 8:
            model = os.environ.get("ORCH_ESCALATION_MODEL", "claude-sonnet-4-6")
        else:
            model = os.environ.get("ORCH_DEFAULT_MODEL", "claude-haiku-4-5-20251001")
    provider = name
    if model.startswith("openai/"):
        provider = "openai"
    elif model.startswith("gemini/"):
        provider = "google"
    elif model.startswith("deepseek/"):
        provider = "deepseek"
    elif model.startswith("ollama/"):
        provider = "local"
    elif name == "claude":
        provider = "claude"
    return {"coder": name, "provider": provider, "model": model,
            "cap": spec.get("cap"), "cost": spec.get("cost")}


def _ollama_model_for(spec, model):
    raw = str(model or "")
    if raw.startswith("ollama/"):
        return raw.split("/", 1)[1]
    cmd = str((spec or {}).get("cmd") or "")
    m = re.search(r"--model\s+['\"]?ollama/([^ '\"]+)", cmd)
    return m.group(1) if m else ""


def _agentic_event(kind, coder, model="", project=None, value=0, action=""):
    if not _truthy("ORCH_AGENTIC_RUN_EVENTS", True):
        return
    try:
        import db
        db.insert("resource_events", {
            "kind": kind,
            "value": value,
            "detail": f"coder={coder} model={model or '-'} project={project or '-'}",
            "action": action,
        })
    except Exception:
        pass


def run(coder, prompt, model, cwd=None, env=None, project=None, timeout=900, **kwargs):
    """Dispatch to the chosen agentic backend, returning claude_cli-shaped output."""
    if coder == "claude":
        import claude_cli
        return claude_cli.run(prompt, model, cwd=cwd, env=env, project=project, timeout=timeout, **kwargs)
    spec = _spec(coder)
    tmpl = _normalize_aider_cmd(spec["cmd"] if spec else "")
    if not tmpl:
        raise RuntimeError(f"coder '{coder}' command not configured")
    cmd = tmpl.replace("{prompt}", shlex.quote(prompt)).replace("{model}", shlex.quote(model or ""))
    ollama_model = _ollama_model_for(spec, model)
    t0 = time.time()
    try:
        _agentic_event("agentic_coder_start", coder, model, project=project, action="subprocess_start")
        slot = contextlib.nullcontext({"locked": False, "unloaded": []})
        if ollama_model:
            try:
                import local_model_slots
                slot = local_model_slots.slot(ollama_model, operation=f"agentic:{coder}")
            except Exception:
                slot = contextlib.nullcontext({"locked": False, "unloaded": []})
        with slot:
            proc = subprocess.run(shlex.split(cmd) if "{prompt}" not in tmpl else ["bash", "-lc", cmd],
                                  cwd=cwd, env=_aider_env(env), capture_output=True, text=True, timeout=timeout)
        # REAL cost from aider's own output (per-message $), so paid-coder daily caps are exact; fall
        # back to the coder's nominal est_usd only when the CLI reported no cost (e.g. a free local model).
        real = _parse_cost((proc.stdout or "") + "\n" + (proc.stderr or ""))
        cost = real if real is not None else float((spec or {}).get("est_usd", 0.0) or 0.0)
        latency_ms = int((time.time() - t0) * 1000)
        _agentic_event("agentic_coder_finish", coder, model, project=project, value=latency_ms,
                       action=f"returncode={proc.returncode} cost_usd={cost}")
        return {"text": proc.stdout, "cost_usd": cost, "input_tokens": 0, "output_tokens": 0,
                "returncode": proc.returncode, "stderr": proc.stderr or "",
                "coder": coder, "latency_ms": latency_ms}
    except subprocess.TimeoutExpired:
        _agentic_event("agentic_coder_finish", coder, model, project=project,
                       value=int((time.time() - t0) * 1000), action="returncode=124 timeout")
        return {"text": "", "cost_usd": 0.0, "input_tokens": 0, "output_tokens": 0,
                "returncode": 124, "stderr": f"{coder} timeout", "coder": coder}


if __name__ == "__main__":
    print("configured agentic coders:", available())
