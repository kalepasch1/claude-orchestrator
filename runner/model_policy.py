#!/usr/bin/env python3
"""
model_policy.py - the model TRIAGE optimizer. Decides which provider+model runs each
task/subtask at the lowest all-in cost, preferring FREE / SUBSCRIPTION / cheap-API models and
only escalating to expensive ones when value would be materially and critically diminished.

Two dimensions:
  1. AGENTIC vs NON-AGENTIC.
     - agentic (edit files in a worktree, run tools) can ONLY be done by Claude Code today ->
       use the Claude Max SUBSCRIPTION (flat, $0/call), Haiku-first, escalate Sonnet->Opus only
       on retry/high-complexity. If the subscription is rate-limited/exhausted, rotate Claude
       accounts (account_pool); if all exhausted, fall back to API Claude (billed) or QUEUE.
     - non-agentic (QA/review/rating/planning/mechanical text) -> cheapest available capable
       provider across ALL providers (local Ollama = free, then DeepSeek/Gemini-Flash/4o-mini).
  2. COST TRANCHES (ascending all-in cost). Always pick the lowest tranche that clears the task's
     required capability; only step up when the cheaper tranche would materially hurt the result.

Env keys enable providers (added by the owner; Cowork cannot create accounts/keys):
  DEEPSEEK_API_KEY, OPENAI_API_KEY, GOOGLE_API_KEY, OLLAMA_HOST
"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import model_gateway as mg

# Ascending all-in cost. 'free' = local/subscription. Each entry: (provider, model, tier, cap)
# cap = rough capability score 1-10 for general coding/reasoning.
TRANCHES = [
    ("local",    os.environ.get("OLLAMA_MODEL", "llama3.1"), "free",   5),
    # self-hosted STRONG tier (e.g. qwen2.5-coder:32b on Mac #2 or a cheap GPU): $0 and capable enough
    # for qa/review/plan — pushes more non-agentic load off paid APIs. Active when OLLAMA_STRONG_MODEL set.
    ("local",    os.environ.get("OLLAMA_STRONG_MODEL", ""),  "free",   7),
    ("deepseek", "deepseek-chat",                            "cheap",  6),
    ("google",   "gemini-2.0-flash",                         "cheap",  6),
    ("openai",   "gpt-4o-mini",                              "cheap",  6),
    ("claude",   "claude-haiku-4-5-20251001",                "sub",    6),   # subscription $0/call
    ("openai",   "gpt-4o",                                   "mid",    8),
    ("claude",   "claude-sonnet-4-6",                        "sub",    8),   # subscription $0/call
    ("claude",   "claude-opus-4-8",                          "sub",    10),  # subscription but heavy tokens
]
TRANCHES = [t for t in TRANCHES if t[1]]  # drop the strong-local row when not configured

# required capability by task class
NEED = {"mechanical": 5, "qa": 6, "review": 6, "rating": 5, "plan": 7,
        "build": 6, "hard": 9, "security": 9, "legal": 9}


def choose(task_class="build", agentic=True, need=None, prefer_free=True):
    """Return (provider, model, reason). Cheapest capable, subscription/free-first."""
    need = need if need is not None else NEED.get(task_class, 6)
    avail = set(mg.available())            # providers with a key/host present
    if agentic:
        # only Claude Code can run the agentic loop; Haiku-first, escalate by need
        if need >= 9:
            return "claude", "claude-opus-4-8", "agentic + hard/critical -> Opus (subscription)"
        if need >= 8:
            return "claude", "claude-sonnet-4-6", "agentic standard -> Sonnet (subscription)"
        return "claude", "claude-haiku-4-5-20251001", "agentic simple -> Haiku (subscription, cheapest)"
    # non-agentic: two strategies.
    capable = [(prov, model, tier, cap) for prov, model, tier, cap in TRANCHES
               if prov in avail and cap >= need]
    # DIVERSIFY MODE (default ON): actively ROTATE across all capable providers so the whole stack —
    # local(Ollama), DeepSeek, Google(Gemini), OpenAI, Claude — gets exercised and benchmarked, instead
    # of always defaulting to the single cheapest. Cost stays bounded (only cheap/free tiers + the
    # key_broker $/day cap). Turn off with ORCH_DIVERSIFY_MODELS=false to go pure cheapest-first.
    if capable and os.environ.get("ORCH_DIVERSIFY_MODELS", "true").lower() == "true":
        # one entry per distinct provider (cheapest model for each), then round-robin by a persistent counter
        seen, ring = set(), []
        for prov, model, tier, cap in capable:
            if prov not in seen:
                seen.add(prov); ring.append((prov, model, tier))
        telemetry_pick = _least_used(task_class, ring)
        if telemetry_pick:
            prov, model, tier = telemetry_pick
            return prov, model, f"non-agentic {task_class}: least-used capable provider -> {prov} ({tier})"
        idx = _rr_next(f"{task_class}:{','.join(p for p, _, _ in ring)}", len(ring))
        prov, model, tier = ring[idx]
        return prov, model, f"non-agentic {task_class}: rotating stack -> {prov} ({tier})"
    # cheapest-first (diversify off): first capable tranche
    if capable:
        prov, model, tier, cap = capable[0]
        return prov, model, f"non-agentic {task_class}: cheapest capable ({tier})"
    return "claude", "claude-sonnet-4-6", "fallback (no cheaper capable provider configured)"


_RR_FILE = os.path.join(os.environ.get("CLAUDE_ORCH_HOME", os.path.expanduser("~/.claude-orchestrator")),
                        "model_rr.json")
_TELEMETRY_CACHE = {}


def _rr_next(bucket, n):
    """Persistent round-robin index per task_class, so successive non-agentic calls rotate providers."""
    if n <= 1:
        return 0
    import json
    try:
        d = json.load(open(_RR_FILE))
    except Exception:
        d = {}
    i = int(d.get(bucket, -1)) + 1
    d[bucket] = i
    try:
        os.makedirs(os.path.dirname(_RR_FILE), exist_ok=True)
        json.dump(d, open(_RR_FILE, "w"))
    except Exception:
        pass
    return i % n


def _least_used(task_class, ring):
    """Prefer providers underrepresented in recent telemetry, so routing visibly diversifies."""
    sig = (task_class, tuple(p for p, _, _ in ring))
    now = time.time()
    cached = _TELEMETRY_CACHE.get(sig)
    if cached and now - cached[0] < float(os.environ.get("ORCH_ROUTE_CACHE_SECONDS", "30")):
        return cached[1]
    try:
        import db
        rows = db.select("app_operations", {"select": "provider", "task_class": f"eq.{task_class}",
                                            "order": "created_at.desc", "limit": "200"}) or []
    except Exception:
        return None
    if len(rows) < max(8, len(ring) * 2):
        _TELEMETRY_CACHE[sig] = (now, None)
        return None
    counts = {p: 0 for p, _, _ in ring}
    for r in rows:
        p = r.get("provider")
        if p in counts:
            counts[p] += 1
    pick = sorted(ring, key=lambda item: (counts.get(item[0], 0), item[2] != "free"))[0]
    _TELEMETRY_CACHE[sig] = (now, pick)
    return pick


def analysis():
    """Human-readable triage: which model each task class routes to right now."""
    out = {"available_providers": sorted(mg.available()), "routing": {}}
    for tc in ("mechanical", "qa", "review", "rating", "plan", "build", "hard", "security", "legal"):
        agentic = tc in ("build", "hard", "security", "legal")
        p, m, why = choose(tc, agentic=agentic)
        out["routing"][tc] = {"agentic": agentic, "provider": p, "model": m, "why": why}
    return out


if __name__ == "__main__":
    import json
    print(json.dumps(analysis(), indent=2))
