#!/usr/bin/env python3
"""
fleet_topology.py - optimal allocation of subscriptions, machines, and execution
channels for maximum throughput at minimum cost.

The fleet has N physical machines, M subscription accounts across multiple vendors,
and can run multiple execution channels per machine:
  - CLI runner (1 per machine, existing)
  - Cowork terminals (1+ per subscription account, subscription-covered)
  - API-direct calls (unlimited, pay-per-use)

This module:
  1. Models the fleet's theoretical and actual throughput capacity
  2. Recommends optimal subscription/machine allocation
  3. Suggests new subscriptions when ROI-positive based on historical data
  4. Coordinates Cowork terminal provisioning across machines

Env:
    ORCH_FLEET_MACHINES    JSON list of machine hostnames (auto-detected if unset)
    ORCH_FLEET_SUBS        JSON list of subscription configs (delegates to subscription_tracker)
    ORCH_COWORK_PER_SUB    Max Cowork terminals per subscription account (default 2)
    ORCH_TARGET_THROUGHPUT Target tasks/hour to plan for (default 500)
"""
import os, sys, json, time, threading, logging, socket

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Fleet model
# ---------------------------------------------------------------------------

# Execution channel throughput estimates (tasks/hour per channel)
CHANNEL_THROUGHPUT = {
    "cli_runner":     8,    # CLI subprocess path: ~80 calls/hr shared across ~10 tasks/hr effective
    "sdk_runner":     12,   # Agent SDK path: slightly faster, same rate limits
    "cowork_agent":   40,   # Cowork Agent tool: parallel sub-agents, no CLI overhead
    "api_direct":     200,  # Direct API: no rate limits, bounded by spend
}

# Vendor subscription catalog — what's available to buy
SUBSCRIPTION_CATALOG = [
    {"vendor": "anthropic", "tier": "max",      "monthly_cost": 100, "est_tasks_hour": 25,
     "cowork_capable": True, "models": ["claude-opus-4-8", "claude-sonnet-4-6", "claude-haiku-4-5-20251001"],
     "best_for": ["complex", "architecture", "security", "core logic"]},
    {"vendor": "anthropic", "tier": "team",     "monthly_cost": 30,  "est_tasks_hour": 15,
     "cowork_capable": True, "models": ["claude-sonnet-4-6", "claude-haiku-4-5-20251001"],
     "best_for": ["standard implementation", "tests", "docs"]},
    {"vendor": "openai",    "tier": "pro",      "monthly_cost": 200, "est_tasks_hour": 30,
     "cowork_capable": False, "models": ["o3", "gpt-5.5", "gpt-5.4-mini"],
     "best_for": ["reasoning", "complex refactors", "architecture"]},
    {"vendor": "openai",    "tier": "plus",     "monthly_cost": 20,  "est_tasks_hour": 15,
     "cowork_capable": False, "models": ["gpt-5.4-mini", "gpt-4o"],
     "best_for": ["standard tasks", "boilerplate"]},
    {"vendor": "deepseek",  "tier": "basic",    "monthly_cost": 10,  "est_tasks_hour": 40,
     "cowork_capable": False, "models": ["deepseek-chat", "deepseek-reasoner"],
     "best_for": ["mechanical", "boilerplate", "formatting", "simple fixes"]},
    {"vendor": "google",    "tier": "advanced", "monthly_cost": 20,  "est_tasks_hour": 20,
     "cowork_capable": False, "models": ["gemini-2.5-pro", "gemini-2.0-flash"],
     "best_for": ["standard tasks", "code review", "docs"]},
]

COWORK_PER_SUB = int(os.environ.get("ORCH_COWORK_PER_SUB", "2"))


class FleetTopology:
    """Model the fleet and recommend optimal allocation."""

    def __init__(self):
        self._lock = threading.Lock()
        self._machines = self._detect_machines()
        self._subscriptions = self._load_subscriptions()

    def _detect_machines(self):
        """Detect or load machine list."""
        try:
            raw = os.environ.get("ORCH_FLEET_MACHINES")
            if raw:
                return json.loads(raw)
        except Exception:
            pass
        # Auto-detect from fleet heartbeats in DB
        try:
            import db
            rows = db.select("fleet_heartbeats",
                             {"select": "hostname", "updated_at": f"gt.{time.time() - 300}"})
            if rows:
                return list({r["hostname"] for r in rows})
        except Exception:
            pass
        return [socket.gethostname()]

    def _load_subscriptions(self):
        """Load current subscription inventory."""
        try:
            import subscription_tracker
            tracker = subscription_tracker._get()
            return list(tracker.subs)  # the raw config list
        except Exception:
            return []

    def current_capacity(self):
        """Calculate current theoretical throughput."""
        n_machines = len(self._machines)
        n_subs = len(self._subscriptions)
        cowork_subs = sum(1 for s in self._subscriptions
                         if s.get("vendor") == "anthropic")  # only Claude has Cowork

        channels = {
            "cli_runners": n_machines,
            "cowork_terminals": cowork_subs * COWORK_PER_SUB,
            "api_direct": 1,  # unlimited but singular cost pool
        }

        throughput = {
            "cli": channels["cli_runners"] * CHANNEL_THROUGHPUT["cli_runner"],
            "cowork": channels["cowork_terminals"] * CHANNEL_THROUGHPUT["cowork_agent"],
            "api": CHANNEL_THROUGHPUT["api_direct"],
        }

        return {
            "machines": n_machines,
            "subscriptions": n_subs,
            "channels": channels,
            "throughput_per_hour": throughput,
            "total_sub_throughput": throughput["cli"] + throughput["cowork"],
            "total_with_api": sum(throughput.values()),
            "monthly_sub_cost": sum(s.get("monthly_cost", 0) for s in self._subscriptions),
        }

    def recommend_topology(self, target_tasks_hour=None):
        """Recommend optimal fleet configuration to hit target throughput."""
        target = target_tasks_hour or int(os.environ.get("ORCH_TARGET_THROUGHPUT", "500"))
        current = self.current_capacity()
        recommendations = []

        # 1. If current sub throughput is below target, recommend more subs
        sub_throughput = current["total_sub_throughput"]
        if sub_throughput < target:
            gap = target - sub_throughput
            # Rank catalog by cost-effectiveness (tasks/hr per $)
            ranked = sorted(SUBSCRIPTION_CATALOG,
                            key=lambda s: s["est_tasks_hour"] / max(s["monthly_cost"], 1),
                            reverse=True)
            remaining_gap = gap
            for cat in ranked:
                if remaining_gap <= 0:
                    break
                n_needed = max(1, int(remaining_gap / cat["est_tasks_hour"]) + 1)
                # Don't recommend more than 3 of any single tier
                n_needed = min(n_needed, 3)
                recommendations.append({
                    "action": "add_subscription",
                    "vendor": cat["vendor"],
                    "tier": cat["tier"],
                    "quantity": n_needed,
                    "monthly_cost": cat["monthly_cost"] * n_needed,
                    "added_throughput": cat["est_tasks_hour"] * n_needed,
                    "cowork_capable": cat["cowork_capable"],
                    "rationale": (f"+{cat['est_tasks_hour'] * n_needed} tasks/hr for "
                                 f"${cat['monthly_cost'] * n_needed}/mo "
                                 f"(${cat['monthly_cost'] / cat['est_tasks_hour']:.2f}/task-hr)"),
                })
                remaining_gap -= cat["est_tasks_hour"] * n_needed

        # 2. If we have cowork-capable subs not running Cowork terminals, recommend starting them
        cowork_capable = sum(1 for s in self._subscriptions if s.get("vendor") == "anthropic")
        cowork_running = 0  # TODO: detect running Cowork terminals
        if cowork_capable > 0 and cowork_running < cowork_capable * COWORK_PER_SUB:
            recommendations.append({
                "action": "start_cowork_terminals",
                "quantity": cowork_capable * COWORK_PER_SUB - cowork_running,
                "added_throughput": (cowork_capable * COWORK_PER_SUB - cowork_running) * CHANNEL_THROUGHPUT["cowork_agent"],
                "monthly_cost": 0,
                "rationale": "Free throughput — Cowork terminals run on existing subscriptions",
            })

        # 3. If we have fewer machines than subscriptions, recommend more machines
        if len(self._machines) < len(self._subscriptions):
            recommendations.append({
                "action": "add_machine",
                "quantity": len(self._subscriptions) - len(self._machines),
                "rationale": "Each machine can run a CLI runner + Cowork terminals",
            })

        # 4. DeepSeek recommendation for mechanical tasks
        has_deepseek = any(s.get("vendor") == "deepseek" for s in self._subscriptions)
        if not has_deepseek:
            recommendations.append({
                "action": "add_subscription",
                "vendor": "deepseek",
                "tier": "basic",
                "quantity": 1,
                "monthly_cost": 10,
                "added_throughput": 40,
                "cowork_capable": False,
                "rationale": ("DeepSeek at $10/mo handles mechanical tasks (formatting, renames, "
                              "boilerplate) at ~40 tasks/hr — best cost/task for low-intelligence work. "
                              "Falls back to API at $0.001/call if sub limits hit."),
            })

        return {
            "current": current,
            "target_tasks_hour": target,
            "gap": max(0, target - current["total_sub_throughput"]),
            "recommendations": recommendations,
        }

    def optimal_task_allocation(self, tasks):
        """Given a batch of tasks, allocate them optimally across channels."""
        allocation = {"cli": [], "cowork": [], "api_cheap": [], "api_heavy": []}

        for t in tasks:
            difficulty = t.get("difficulty", "easy")
            kind = t.get("kind", "")

            if kind in ("mechanical", "chore", "cleanup", "docs") or difficulty == "easy":
                # Cheap tasks → DeepSeek sub or API, or Cowork batch
                allocation["api_cheap"].append(t)
            elif difficulty == "critical":
                # Critical → Claude CLI (full agentic) or Opus API
                allocation["cli"].append(t)
            else:
                # Standard → Cowork agents (best throughput on subscription)
                allocation["cowork"].append(t)

        return allocation


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_topo = None
_topo_lock = threading.Lock()


def _get():
    global _topo
    if _topo is None:
        with _topo_lock:
            if _topo is None:
                _topo = FleetTopology()
    return _topo


def current_capacity():
    try:
        return _get().current_capacity()
    except Exception:
        return {}


def recommend_topology(target_tasks_hour=None):
    try:
        return _get().recommend_topology(target_tasks_hour)
    except Exception:
        return {}


def optimal_task_allocation(tasks):
    try:
        return _get().optimal_task_allocation(tasks)
    except Exception:
        return {"cli": tasks, "cowork": [], "api_cheap": [], "api_heavy": []}


def invalidate():
    global _topo
    _topo = None
