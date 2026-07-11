#!/usr/bin/env python3
"""
tier_router.py - routing brain: route each task to the cheapest execution tier with capacity.

Tiers:
  0 "sub"         Subscription-based (Claude CLI/SDK, ChatGPT via aider, Gemini via aider). $0 marginal.
  1 "api"         Direct API via swarm_executor. Pay-per-use, no rate limits.
  2 "speculative" Race across 2+ API providers. Highest throughput, ~2x cost.

Routing preference: sub_first (default). Always try subscriptions before spending real dollars.

Env vars (ORCH_-prefixed for fleet-wide tuning via fleet_config):
  ORCH_TIER_MODE                "sub_first" (default) | "api_only" | "hybrid"
  ORCH_SPECULATIVE_THRESHOLD    max est cost for speculative tier ($0.05 default)
  ORCH_PREFER_SUB               "true" (default) — always try subscription first
"""
import os, sys, time, threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ---------------------------------------------------------------------------
# Env config (read at call time for live fleet_config reloads)
# ---------------------------------------------------------------------------

def _tier_mode():
    return os.environ.get("ORCH_TIER_MODE", "sub_first").lower()

def _spec_threshold():
    try:
        return float(os.environ.get("ORCH_SPECULATIVE_THRESHOLD", "0.05"))
    except ValueError:
        return 0.05

def _prefer_sub():
    return os.environ.get("ORCH_PREFER_SUB", "true").lower() in ("true", "1", "yes")

# ---------------------------------------------------------------------------
# Difficulty → model tier mapping
# ---------------------------------------------------------------------------
_DIFF_MODEL = {"easy": "fast", "hard": "mid", "critical": "heavy"}

# Provider cost ranking (lower = cheaper) for API tier selection
_API_PROVIDERS = [
    {"provider": "deepseek", "model": "deepseek-chat",    "coder": "aider", "cost_rank": 1},
    {"provider": "gemini",   "model": "gemini-2.0-flash", "coder": "aider", "cost_rank": 2},
    {"provider": "openai",   "model": "gpt-4o-mini",      "coder": "aider", "cost_rank": 3},
    {"provider": "anthropic","model": "claude-sonnet-4-6", "coder": "aider", "cost_rank": 4},
]

# Subscription providers and their model tiers
_SUB_PROVIDERS = [
    {"provider": "claude",  "model": "claude-sonnet-4-6", "coder": "claude-cli",
     "tiers": {"fast", "mid", "heavy"}},
    {"provider": "chatgpt", "model": "gpt-4o",            "coder": "aider",
     "tiers": {"fast", "mid"}},
    {"provider": "gemini",  "model": "gemini-2.5-pro",    "coder": "aider",
     "tiers": {"fast", "mid"}},
]


# ---------------------------------------------------------------------------
# TierRouter singleton
# ---------------------------------------------------------------------------

class TierRouter:
    def __init__(self):
        self._lock = threading.Lock()
        self._outcomes = []          # recent outcome records for stats
        self._max_outcomes = 2000

    # ---- helpers ----------------------------------------------------------

    def _task_difficulty(self, task):
        """Map task to easy/hard/critical."""
        d = (task.get("difficulty") or task.get("diff") or "easy").lower()
        if d in ("critical", "heavy"):
            return "critical"
        if d in ("hard", "medium", "mid"):
            return "hard"
        return "easy"

    def _estimated_cost(self, task):
        try:
            return float(task.get("est_usd") or task.get("estimated_cost") or 0.0)
        except (ValueError, TypeError):
            return 0.0

    def _sub_has_capacity(self, provider_name):
        """Check subscription capacity via subscription_tracker (if available) and account_pool."""
        # subscription_tracker may not exist yet — degrade gracefully
        try:
            import subscription_tracker
            status = subscription_tracker.status(provider_name)
            if status and status.get("remaining", 1) <= 0:
                return False
        except ImportError:
            pass
        except Exception:
            pass

        # Claude-specific: check account_pool exhaustion
        if provider_name == "claude":
            try:
                import account_pool
                if account_pool.claude_exhausted():
                    return False
            except Exception:
                pass
        return True

    def _kill_switch_paused(self):
        try:
            import kill_switch
            return kill_switch.is_paused()
        except Exception:
            return False

    def _paid_allowed(self):
        try:
            import budget
            return budget.paid_allowed()
        except Exception:
            return False

    # ---- core routing -----------------------------------------------------

    def route(self, task):
        """Return routing decision dict for a task.

        Returns: {"tier": "sub"|"api"|"speculative", "provider": str, "model": str,
                  "coder": str, "reason": str}
        """
        if not task:
            return {"tier": "sub", "provider": "claude", "model": "claude-sonnet-4-6",
                    "coder": "claude-cli", "reason": "empty task fallback"}

        if self._kill_switch_paused():
            return {"tier": "sub", "provider": "claude", "model": "claude-sonnet-4-6",
                    "coder": "claude-cli", "reason": "kill_switch paused — default sub only"}

        mode = _tier_mode()
        diff = self._task_difficulty(task)
        model_tier = _DIFF_MODEL.get(diff, "fast")
        est = self._estimated_cost(task)

        # --- wave_pipeline cross-task learning hint ---
        _hint_provider = task.get("_wave_provider_hint")
        _hint_model = task.get("_wave_model_hint")
        if _hint_provider and _hint_model:
            # If wave_pipeline learned a better path, honor it
            for sp in _SUB_PROVIDERS:
                if sp["provider"] == _hint_provider and self._sub_has_capacity(sp["provider"]):
                    return {"tier": "sub", "provider": sp["provider"], "model": _hint_model,
                            "coder": sp["coder"],
                            "reason": f"wave cross-task learning → {_hint_provider}:{_hint_model}"}
            for ap in _API_PROVIDERS:
                if ap["provider"] == _hint_provider:
                    if self._paid_allowed():
                        return {"tier": "api", "provider": ap["provider"], "model": _hint_model,
                                "coder": ap["coder"],
                                "reason": f"wave cross-task learning → api {_hint_provider}:{_hint_model}"}

        # --- api_only mode: skip subscription entirely ---
        if mode == "api_only":
            return self._pick_api(task, model_tier, "api_only mode")

        # --- sub_first / hybrid: try subscriptions ---
        if _prefer_sub() or mode == "sub_first":
            sub = self._pick_sub(model_tier)
            if sub:
                return sub

        # --- hybrid: try sub then api ---
        if mode == "hybrid":
            sub = self._pick_sub(model_tier)
            if sub:
                return sub

        # --- speculative for cheap + latency-sensitive tasks ---
        if est > 0 and est <= _spec_threshold() and task.get("latency_sensitive"):
            if self._paid_allowed():
                providers = [p for p in _API_PROVIDERS[:2]]  # cheapest 2
                names = "+".join(p["provider"] for p in providers)
                return {"tier": "speculative", "provider": names,
                        "model": providers[0]["model"], "coder": "swarm",
                        "reason": f"cheap (${est:.3f}) + latency_sensitive → speculative race"}

        # --- API fallback ---
        if self._paid_allowed():
            return self._pick_api(task, model_tier, "no sub capacity")

        # --- ultimate fallback: queue for sub (Claude) ---
        return {"tier": "sub", "provider": "claude", "model": "claude-sonnet-4-6",
                "coder": "claude-cli",
                "reason": "paid not allowed, no sub capacity — queued for Claude"}

    def _pick_sub(self, model_tier):
        """Find a subscription provider with capacity for the given model tier."""
        for sp in _SUB_PROVIDERS:
            if model_tier in sp["tiers"] and self._sub_has_capacity(sp["provider"]):
                return {"tier": "sub", "provider": sp["provider"], "model": sp["model"],
                        "coder": sp["coder"],
                        "reason": f"sub {sp['provider']} has capacity for {model_tier}"}
        return None

    def _pick_api(self, task, model_tier, context):
        """Pick cheapest API provider with needed capability."""
        for ap in _API_PROVIDERS:
            return {"tier": "api", "provider": ap["provider"], "model": ap["model"],
                    "coder": ap["coder"],
                    "reason": f"{context} → api {ap['provider']} (cheapest)"}
        return {"tier": "api", "provider": "deepseek", "model": "deepseek-chat",
                "coder": "aider", "reason": f"{context} → deepseek fallback"}

    # ---- outcome feedback -------------------------------------------------

    def record_outcome(self, task_id, tier, provider, success, cost_usd=0.0, latency_s=0.0):
        """Record a routing outcome for learning and stats."""
        rec = {"task_id": task_id, "tier": tier, "provider": provider,
               "success": bool(success), "cost_usd": float(cost_usd or 0),
               "latency_s": float(latency_s or 0), "ts": time.time()}
        with self._lock:
            self._outcomes.append(rec)
            if len(self._outcomes) > self._max_outcomes:
                self._outcomes = self._outcomes[-self._max_outcomes:]

    # ---- backlog planning -------------------------------------------------

    def suggest_tier_for_backlog(self, tasks):
        """Given pending tasks, return an optimal routing plan minimizing cost + maximizing throughput.

        Returns list of {"task": task, "decision": route_decision} dicts.
        """
        if not tasks:
            return []
        plan = []
        # Count sub slots used so we can estimate remaining capacity
        sub_slots_used = {}
        for t in tasks:
            decision = self.route(t)
            if decision["tier"] == "sub":
                p = decision["provider"]
                sub_slots_used[p] = sub_slots_used.get(p, 0) + 1
            plan.append({"task": t, "decision": decision})
        return plan

    # ---- stats ------------------------------------------------------------

    def stats(self):
        """Return routing breakdown: % sub vs api vs speculative, cost savings estimate."""
        with self._lock:
            outcomes = list(self._outcomes)
        if not outcomes:
            return {"total": 0, "sub_pct": 0.0, "api_pct": 0.0, "spec_pct": 0.0,
                    "total_cost": 0.0, "sub_cost_savings": 0.0}
        total = len(outcomes)
        by_tier = {"sub": 0, "api": 0, "speculative": 0}
        total_cost = 0.0
        api_avg_cost = 0.0
        api_count = 0
        for o in outcomes:
            t = o.get("tier", "sub")
            by_tier[t] = by_tier.get(t, 0) + 1
            total_cost += o.get("cost_usd", 0)
            if t in ("api", "speculative"):
                api_avg_cost += o.get("cost_usd", 0)
                api_count += 1
        avg_api = (api_avg_cost / api_count) if api_count else 0.02
        sub_savings = by_tier.get("sub", 0) * avg_api  # what sub tasks would have cost on API
        return {
            "total": total,
            "sub_pct": round(100 * by_tier.get("sub", 0) / total, 1),
            "api_pct": round(100 * by_tier.get("api", 0) / total, 1),
            "spec_pct": round(100 * by_tier.get("speculative", 0) / total, 1),
            "total_cost": round(total_cost, 4),
            "sub_cost_savings": round(sub_savings, 4),
        }


# ---------------------------------------------------------------------------
# Module-level singleton + delegation
# ---------------------------------------------------------------------------
_router = TierRouter()


def route(task):
    """Route task to cheapest execution tier with capacity."""
    return _router.route(task)


def record_outcome(task_id, tier, provider, success, cost_usd=0.0, latency_s=0.0):
    """Feed back execution results for stats and learning."""
    return _router.record_outcome(task_id, tier, provider, success, cost_usd, latency_s)


def suggest_tier_for_backlog(tasks):
    """Optimal routing plan for a list of pending tasks."""
    return _router.suggest_tier_for_backlog(tasks)


def stats():
    """Routing breakdown: % sub vs api vs speculative, cost savings."""
    return _router.stats()
