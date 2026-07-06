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
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# capability a task needs by difficulty (see _task_difficulty)
_NEED = {"easy": 5, "hard": 8}

# aider prints e.g. "Tokens: 1.2k sent, 500 received. Cost: $0.0021 message, $0.0021 session."
_AIDER_MSG_COST = re.compile(r"cost:\s*\$([0-9.]+)\s*message", re.I)
_AIDER_ANY_COST = re.compile(r"\$([0-9.]+)\s*(?:message|session)", re.I)


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
    # SAFETY: drop any coder whose command needs a CLI that isn't installed. Without this, configuring a
    # coder (aider/codex/etc.) before its CLI exists would route real tasks to a coder that instantly
    # fails — turning "no cheap models" into "broken tasks". Pruning keeps work on the coders that ARE
    # present; each cheap coder lights up automatically the moment its CLI is installed. Native claude
    # (cmd=None) is never pruned. Cached (~60s) so this hot path doesn't shell out per call.
    def _usable(c):
        cmd = str(c.get("cmd") or "").strip()
        if not cmd:
            return True                      # native (claude) — always usable
        exe = cmd.split()[0]
        return _cli_present(exe)
    pool = [c for c in pool if _usable(c)]
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


# kept for backward-compat with any external caller
def _third_within_cap():
    c = _spec(os.environ.get("ORCH_THIRD_CODER", ""))
    return bool(c) and _within_cap(c)


def _task_difficulty(task):
    """Cheap heuristic for whether a lower-intelligence/cheaper model can likely complete this task.
    Material work and anything with dependencies is 'hard' (stays on a capable coder); mechanical/
    bugfix/docs/test kinds, an explicit haiku hint, or a small self-contained prompt are 'easy'."""
    if task.get("material") or (task.get("deps") or []):
        return "hard"
    kind = str(task.get("kind") or "").lower()
    if kind in ("mechanical", "chore", "bugfix", "docs", "test", "cleanup"):
        return "easy"
    if "haiku" in str(task.get("model") or "").lower():
        return "easy"
    if len(str(task.get("prompt") or "")) < 600:
        return "easy"
    return "hard"


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
    need = _NEED[diff]
    usable = [c for c in pool if c["cap"] >= need and _within_cap(c)]
    by_cost = sorted([c for c in usable if c["name"] != "claude"], key=lambda c: (c["cost"], -c["cap"]))

    forced = str(task.get("force_coder") or "").strip()
    if forced:
        fc = _spec(forced)
        if forced == "claude":
            return "claude"
        if fc and fc["cap"] >= need and _within_cap(fc):
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
        strongest = sorted([c for c in pool if c["name"] != "claude" and _within_cap(c)],
                           key=lambda c: -c["cap"])
        return strongest[0]["name"] if strongest else "claude"

    # LEARNED ROUTER: prefer the coder that empirically converts THIS task-kind to merges most cheaply
    # ($/merge from our own outcomes). Returns None until there's enough signal, so it refines the
    # heuristic rather than fighting it; never overrides material (those stay on Claude below).
    if not task.get("material"):
        try:
            import router_stats
            rec = router_stats.best_coder(task.get("kind"), [c["name"] for c in usable])
            if rec:
                return rec
        except Exception:
            pass

    # NORMAL state
    if task.get("material") or (task.get("deps") or []):
        return "claude"
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


def run(coder, prompt, model, cwd=None, env=None, project=None, timeout=900, **kwargs):
    """Dispatch to the chosen agentic backend, returning claude_cli-shaped output."""
    if coder == "claude":
        import claude_cli
        return claude_cli.run(prompt, model, cwd=cwd, env=env, project=project, timeout=timeout, **kwargs)
    spec = _spec(coder)
    tmpl = spec["cmd"] if spec else ""
    if not tmpl:
        raise RuntimeError(f"coder '{coder}' command not configured")
    cmd = tmpl.replace("{prompt}", shlex.quote(prompt)).replace("{model}", shlex.quote(model or ""))
    t0 = time.time()
    try:
        proc = subprocess.run(shlex.split(cmd) if "{prompt}" not in tmpl else ["bash", "-lc", cmd],
                              cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
        # REAL cost from aider's own output (per-message $), so paid-coder daily caps are exact; fall
        # back to the coder's nominal est_usd only when the CLI reported no cost (e.g. a free local model).
        real = _parse_cost((proc.stdout or "") + "\n" + (proc.stderr or ""))
        cost = real if real is not None else float((spec or {}).get("est_usd", 0.0) or 0.0)
        return {"text": proc.stdout, "cost_usd": cost, "input_tokens": 0, "output_tokens": 0,
                "returncode": proc.returncode, "stderr": proc.stderr or "",
                "coder": coder, "latency_ms": int((time.time() - t0) * 1000)}
    except subprocess.TimeoutExpired:
        return {"text": "", "cost_usd": 0.0, "input_tokens": 0, "output_tokens": 0,
                "returncode": 124, "stderr": f"{coder} timeout", "coder": coder}


if __name__ == "__main__":
    print("configured agentic coders:", available())
