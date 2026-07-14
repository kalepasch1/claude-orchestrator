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
import provider_credentials
provider_credentials.activate_aliases()

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
    {"provider": "groq",     "model": "llama-3.1-8b-instant",  "coder": "swarm", "cost_rank": 0},
    {"provider": "deepseek", "model": "deepseek-v4-flash",     "coder": "aider", "cost_rank": 1},
    {"provider": "gemini",   "model": "gemini-3-flash",        "coder": "aider", "cost_rank": 2},
    {"provider": "xai",      "model": "grok-build-0.1",        "coder": "swarm", "cost_rank": 3},
    {"provider": "openai",   "model": "gpt-5.4-nano",          "coder": "aider", "cost_rank": 4},
    {"provider": "anthropic","model": "claude-sonnet-5",      "coder": "aider", "cost_rank": 5},
]

# API key env var map for availability checks
_KEY_ENV_MAP = {
    "groq": "GROQ_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "xai": "XAI_API_KEY",
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}


def _registry_provider(provider):
    """Normalize execution-provider aliases to vendor registry names."""
    return {
        "google": "gemini", "gemini": "gemini",
        "anthropic": "claude", "claude": "claude",
        "chatgpt": "openai",
    }.get(str(provider or "").lower(), str(provider or "").lower())

# Subscription providers: drain $0/flat-fee tokens BEFORE API billing.
# Includes: Claude Max, Groq free (30 RPM), Google AI Studio free (1500 RPD),
# ChatGPT Plus/Pro, Gemini Advanced.
# Original comment: Subscription providers and their model tiers — calibrated per task difficulty.
# With 3 Claude Max plans, we have abundant subscription credits across all Claude
# models. Route easy/mechanical → Haiku ($0, fast), standard → Sonnet ($0, balanced),
# hard/critical → Opus ($0, max capability). All subscription = $0 marginal cost.
_SUB_PROVIDERS = [
    # Claude Haiku: fast, cheap-token, great for mechanical/docs/lint/easy tasks
    {"provider": "claude",  "model": "claude-haiku-4-5-20251001", "coder": "claude-cli",
     "tiers": {"fast"}},
    # Claude Sonnet: balanced, good for standard build/mid-complexity
    {"provider": "claude",  "model": "claude-sonnet-5", "coder": "claude-cli",
     "tiers": {"mid"}},
    # Claude Opus: maximum capability for hard/critical/security/architecture tasks
    {"provider": "claude",  "model": "claude-opus-4-8", "coder": "claude-cli",
     "tiers": {"heavy"}},
    # -- Groq free tier (30 RPM, $0, 500+ tok/s) --
    {"provider": "groq",    "model": "llama-3.3-70b-versatile", "coder": "swarm",
     "tiers": {"fast", "mid"}},
    # -- Google AI Studio free tier (1500 RPD, $0) --
    {"provider": "gemini",  "model": "gemini-3-flash",    "coder": "aider",
     "tiers": {"fast"}},
    {"provider": "chatgpt", "model": "gpt-5.4-mini",      "coder": "aider",
     "tiers": {"fast", "mid"}},
    {"provider": "gemini",  "model": "gemini-3.5-flash",  "coder": "aider",
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
            return {"tier": "sub", "provider": "claude", "model": "claude-sonnet-5",
                    "coder": "claude-cli", "reason": "empty task fallback"}

        if self._kill_switch_paused():
            return {"tier": "sub", "provider": "claude", "model": "claude-sonnet-5",
                    "coder": "claude-cli", "reason": "kill_switch paused — default sub only"}

        # Capabilities that genuinely require Cowork must be dispatched before
        # generic Claude model calibration. Code/build tasks without these
        # requirements continue through the fully native orchestrator path.
        try:
            import vendor_capabilities, cowork_skills
            needs_cowork, cowork_caps = vendor_capabilities.requires_cowork_session(task)
            if needs_cowork and cowork_skills.ENABLED:
                return {"tier": "sub", "provider": "claude",
                        "model": os.environ.get("ORCH_COWORK_SKILL_MODEL", "claude-sonnet-5"),
                        "coder": "cowork-skill", "skill_types": cowork_caps,
                        "reason": "capability gate → Cowork-only " + ",".join(cowork_caps)}
        except Exception:
            pass

        mode = _tier_mode()
        diff = self._task_difficulty(task)
        model_tier = _DIFF_MODEL.get(diff, "fast")
        est = self._estimated_cost(task)

        # --- Cowork model calibration: right-size Claude model per task ---
        if os.environ.get("ORCH_COWORK_MODEL_CALIBRATE", "true").lower() in ("true", "1"):
            kind = (task.get("kind") or "").lower()
            # Mechanical/docs/lint/test → Haiku (fast, $0)
            if kind in ("mechanical", "docs", "lint", "format", "bump", "test") or model_tier == "fast":
                _cal_model = os.environ.get("ORCH_COWORK_EASY_MODEL", "claude-haiku-4-5-20251001")
                if self._sub_has_capacity("claude"):
                    return {"tier": "sub", "provider": "claude", "model": _cal_model,
                            "coder": "claude-cli",
                            "reason": f"cowork-calibrate: {kind or diff} → Haiku (fast/$0)"}
            # Hard/critical/security/architecture → Opus (max capability, $0)
            elif model_tier == "heavy" or kind in ("security", "architecture", "legal"):
                _cal_model = os.environ.get("ORCH_COWORK_HARD_MODEL", "claude-opus-4-8")
                if self._sub_has_capacity("claude"):
                    return {"tier": "sub", "provider": "claude", "model": _cal_model,
                            "coder": "claude-cli",
                            "reason": f"cowork-calibrate: {kind or diff} → Opus (heavy/$0)"}
            # Everything else (build, refactor, standard) → Sonnet (balanced, $0)
            elif self._sub_has_capacity("claude"):
                _cal_model = os.environ.get("ORCH_COWORK_MID_MODEL", "claude-sonnet-5")
                return {"tier": "sub", "provider": "claude", "model": _cal_model,
                        "coder": "claude-cli",
                        "reason": f"cowork-calibrate: {kind or diff} → Sonnet (mid/$0)"}

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

        # --- model_cascade: start on cheapest viable model ---
        try:
            if os.environ.get("ORCH_MODEL_CASCADE", "true").lower() in ("true", "1"):
                import model_cascade
                _cascade = model_cascade.should_cascade(task)
                if _cascade and _cascade.get("start_model"):
                    task["_cascade_start_model"] = _cascade["start_model"]
        except Exception:
            pass

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
        return {"tier": "sub", "provider": "claude", "model": "claude-sonnet-5",
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
        """Pick cheapest API provider with needed capability.

        Enhanced to:
        1. Check vendor_capabilities for task-specific capability matching
        2. Consult qpd_bandit for learned quality-per-dollar routing
        3. Skip providers demoted by SLA enforcement
        4. Auto-dispatch to cowork_skills for browser/document tasks
        """
        # --- Cowork skill dispatch: tasks needing browser/document capabilities ---
        try:
            import cowork_skills
            if cowork_skills.needs_skill(task):
                skill_types = cowork_skills.detect_skill_type(task)
                if skill_types:
                    return {"tier": "sub", "provider": "claude", "model": "claude-sonnet-5",
                            "coder": "cowork-skill",
                            "skill_types": [s[0] for s in skill_types],
                            "reason": f"{context} → cowork skill dispatch ({skill_types[0][0]})"}
        except Exception:
            pass

        # --- QPD bandit: learned routing when enough signal exists ---
        try:
            import qpd_bandit
            task_class = (task.get("kind") or task.get("type") or "unknown").lower()

            # Capability-aware bandit routing
            try:
                import vendor_capabilities
                required = vendor_capabilities.detect_required_capabilities(task)
                prov, model, reason = qpd_bandit.best_for_capabilities(task_class, required)
            except ImportError:
                prov, model, reason = qpd_bandit.best_with_penalties(task_class)

            if prov and model and model != "penalty":
                # Map provider to API entry
                for ap in _API_PROVIDERS:
                    if _registry_provider(ap["provider"]) == _registry_provider(prov):
                        registry_provider = _registry_provider(ap["provider"])
                        if required and not all(vendor_capabilities.vendor_has_capability(
                                registry_provider, cap) for cap in required):
                            continue
                        return {"tier": "api", "provider": ap["provider"], "model": model,
                                "coder": ap["coder"],
                                "reason": f"{context} → bandit: {reason}"}
        except Exception:
            pass

        # --- Capability-filtered cheapest provider ---
        try:
            import vendor_capabilities
            required = vendor_capabilities.detect_required_capabilities(task)
            import provider_failover_sla
            for ap in _API_PROVIDERS:
                key_env = _KEY_ENV_MAP.get(ap["provider"], "")
                if key_env and not provider_credentials.has(ap["provider"]):
                    continue  # no API key
                if provider_failover_sla.is_demoted(ap["provider"]):
                    continue  # SLA-demoted
                registry_provider = _registry_provider(ap["provider"])
                if required and not all(vendor_capabilities.vendor_has_capability(
                        registry_provider, cap) for cap in required):
                    continue
                if vendor_capabilities.vendor_has_capability(registry_provider, "code_generation"):
                    suggested, why = vendor_capabilities.suggest_model(registry_provider, task)
                    return {"tier": "api", "provider": ap["provider"], "model": suggested or ap["model"],
                            "coder": ap["coder"],
                            "reason": f"{context} → capability-complete {ap['provider']} ({why or 'cheapest capable'})"}
        except Exception:
            pass

        # --- Fallback: cheapest available API provider ---
        for ap in _API_PROVIDERS:
            key_env = _KEY_ENV_MAP.get(ap["provider"])
            if key_env and not provider_credentials.has(ap["provider"]):
                continue
            try:
                import provider_failover_sla
                if provider_failover_sla.is_demoted(ap["provider"]):
                    continue
            except Exception:
                pass
            return {"tier": "api", "provider": ap["provider"], "model": ap["model"],
                    "coder": ap["coder"],
                    "reason": f"{context} → api {ap['provider']} (cheapest available)"}
        return {"tier": "api", "provider": "deepseek", "model": "deepseek-v4-flash",
                "coder": "aider", "reason": f"{context} → deepseek fallback"}

    # ---- failover routing ------------------------------------------------

    def failover_route(self, task, exclude_providers=None):
        """Route to a non-Claude provider for failover scenarios.

        Called when Claude CLI hits CircuitOpen, rate limits, or auth failures.
        Skips Claude entirely and picks the best alternative vendor.
        """
        exclude = set(exclude_providers or [])
        exclude.add("claude")  # always exclude Claude in failover

        diff = self._task_difficulty(task)
        model_tier = _DIFF_MODEL.get(diff, "fast")

        # Try subscription providers first (Groq free, Gemini free, ChatGPT)
        for sp in _SUB_PROVIDERS:
            if sp["provider"] in exclude:
                continue
            if model_tier in sp["tiers"] and self._sub_has_capacity(sp["provider"]):
                return {"tier": "sub", "provider": sp["provider"], "model": sp["model"],
                        "coder": sp["coder"],
                        "reason": f"failover: sub {sp['provider']} (excluding {', '.join(sorted(exclude))})"}

        # Try API providers
        if self._paid_allowed():
            for ap in _API_PROVIDERS:
                if ap["provider"] in exclude:
                    continue
                key_env = _KEY_ENV_MAP.get(ap["provider"], "")
                if key_env and not provider_credentials.has(ap["provider"]):
                    continue
                try:
                    import provider_failover_sla
                    if provider_failover_sla.is_demoted(ap["provider"]):
                        continue
                except Exception:
                    pass
                return {"tier": "api", "provider": ap["provider"], "model": ap["model"],
                        "coder": ap["coder"],
                        "reason": f"failover: api {ap['provider']} (excluding {', '.join(sorted(exclude))})"}

        return None  # no failover available

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


def failover_route(task, exclude_providers=None):
    return _router.failover_route(task, exclude_providers)


def record_outcome(task_id, tier, provider, success, cost_usd=0.0, latency_s=0.0):
    """Feed back execution results for stats and learning."""
    return _router.record_outcome(task_id, tier, provider, success, cost_usd, latency_s)


def suggest_tier_for_backlog(tasks):
    """Optimal routing plan for a list of pending tasks."""
    return _router.suggest_tier_for_backlog(tasks)


def stats():
    """Routing breakdown: % sub vs api vs speculative, cost savings."""
    return _router.stats()
