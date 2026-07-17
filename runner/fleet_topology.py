#!/usr/bin/env python3
"""
fleet_topology.py - optimal allocation of subscriptions, machines, and execution
channels for maximum throughput at minimum cost, plus machine capability profiles
for intelligent task routing.

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
  5. Detects hardware characteristics (RAM, disk, CPU, tools) per machine
  6. Registers capability profiles in DB for routing decisions
  7. Routes tasks to the best-fit machine based on complexity and history

Env:
    ORCH_FLEET_MACHINES            JSON list of machine hostnames (auto-detected if unset)
    ORCH_FLEET_SUBS                JSON list of subscription configs (delegates to subscription_tracker)
    ORCH_COWORK_PER_SUB            Max Cowork terminals per subscription account (default 2)
    ORCH_TARGET_THROUGHPUT         Target tasks/hour to plan for (default 500)
    ORCH_FLEET_TOPOLOGY_ENABLED    "true"/"false" (default "true") — gate for hardware profiling
    RUNNER_ID                      Current runner identifier (auto-detected if unset)
"""
import os, sys, shutil, json, time, threading, logging, socket

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import log as _log_mod
_log = _log_mod.get("fleet_topology")
log = logging.getLogger(__name__)
import db

# ---------------------------------------------------------------------------
# Fleet model
# ---------------------------------------------------------------------------

# Execution channel throughput estimates (tasks/hour per channel)
CHANNEL_THROUGHPUT = {
    "cli_runner":     8,    # CLI subprocess path: ~80 calls/hr shared across ~10 tasks/hr effective
    "sdk_runner":     12,   # Agent SDK path: slightly faster, same rate limits
    "cowork_agent":   180,  # Cowork terminal: bypasses CLI rate limits entirely, bounded only by
                            # model inference time (~15-30s/task). 120-200 tasks/hr per terminal.
                            # 6 terminals (3 Max × 2 each) = ~1080 tasks/hr at $0 marginal cost.
    "api_direct":     200,  # Direct API: no rate limits, bounded by spend
}

# Vendor subscription catalog — what's available to buy
SUBSCRIPTION_CATALOG = [
    {"vendor": "anthropic", "tier": "max",      "monthly_cost": 100, "est_tasks_hour": 180,
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
    """Drop the cached FleetTopology so the next call rebuilds from fresh DB state."""
    global _topo
    _topo = None


# ---------------------------------------------------------------------------
# Machine capability profiling & task routing
# ---------------------------------------------------------------------------

_COMPLEXITY_ORDER = ["simple", "moderate", "complex", "very_complex"]


def _complexity_rank(c):
    """Return numeric rank for a complexity string (higher = harder)."""
    try:
        return _COMPLEXITY_ORDER.index(c)
    except (ValueError, TypeError):
        return 0


def _topology_enabled():
    return os.environ.get("ORCH_FLEET_TOPOLOGY_ENABLED", "true").lower() in ("true", "1", "yes")


# ── Thread-safe profiling stats ──────────────────────────────────────────────

_profile_lock = threading.Lock()
_profile_stats = {
    "redirects": 0,
    "profile_updates": 0,
    "last_profile_ts": 0.0,
}
_cached_profile = None


# ── Hardware detection ───────────────────────────────────────────────────────

def _detect_ram_gb():
    """Detect total physical RAM in GB. Fail-soft: returns 8.0 on error."""
    try:
        page_size = os.sysconf("SC_PAGE_SIZE")
        phys_pages = os.sysconf("SC_PHYS_PAGES")
        if page_size > 0 and phys_pages > 0:
            return round(page_size * phys_pages / (1024 ** 3), 1)
    except (ValueError, OSError, AttributeError):
        pass
    try:
        import psutil
        return round(psutil.virtual_memory().total / (1024 ** 3), 1)
    except Exception:
        pass
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    kb = int(line.split()[1])
                    return round(kb / (1024 ** 2), 1)
    except Exception:
        pass
    return 8.0


def _detect_disk_free_gb():
    """Detect free disk space on / in GB. Fail-soft: returns 50.0 on error."""
    try:
        usage = shutil.disk_usage("/")
        return round(usage.free / (1024 ** 3), 1)
    except Exception:
        return 50.0


def _detect_cpu_count():
    """Detect CPU count. Fail-soft: returns 4 on error."""
    try:
        return os.cpu_count() or 4
    except Exception:
        return 4


def _detect_tools():
    """Detect which developer tools are installed on this machine."""
    candidates = ["git", "claude", "aider", "node", "python3", "cargo", "go"]
    found = []
    for tool in candidates:
        if shutil.which(tool):
            found.append(tool)
    return found


def _compute_max_complexity(ram_gb):
    """Determine the maximum task complexity this machine can handle."""
    if ram_gb >= 32:
        return "very_complex"
    elif ram_gb >= 16:
        return "complex"
    elif ram_gb >= 8:
        return "moderate"
    else:
        return "simple"


def _runner_id():
    return os.environ.get("RUNNER_ID", socket.gethostname() + "-" + str(os.getpid()))


# ── Public profiling API ─────────────────────────────────────────────────────

def profile():
    """Build a capability profile for this machine.

    Returns {"runner_id", "hostname", "ram_gb", "disk_free_gb", "cpu_count",
             "tools", "max_complexity"}.
    Always returns a dict with best-effort values; never raises.
    """
    global _cached_profile
    try:
        ram_gb = _detect_ram_gb()
        disk_free_gb = _detect_disk_free_gb()
        cpu_count = _detect_cpu_count()
        tools = _detect_tools()
        p = {
            "runner_id": _runner_id(),
            "hostname": socket.gethostname(),
            "ram_gb": ram_gb,
            "disk_free_gb": disk_free_gb,
            "cpu_count": cpu_count,
            "tools": tools,
            "max_complexity": _compute_max_complexity(ram_gb),
        }
        with _profile_lock:
            _cached_profile = p
        return p
    except Exception:
        _log.warning("profile: detection failed, returning defaults")
        p = {
            "runner_id": _runner_id(),
            "hostname": socket.gethostname(),
            "ram_gb": 8.0,
            "disk_free_gb": 50.0,
            "cpu_count": 4,
            "tools": [],
            "max_complexity": "moderate",
        }
        with _profile_lock:
            _cached_profile = p
        return p


def register_profile():
    """Write this machine's profile to the fleet_topology DB table.

    Called once at runner startup.  Uses db.upsert (ON CONFLICT UPDATE)
    so re-registrations are idempotent.
    """
    if not _topology_enabled():
        _log.debug("register_profile: topology disabled")
        return
    p = profile()
    try:
        row = {
            "runner_id": p["runner_id"],
            "hostname": p["hostname"],
            "ram_gb": p["ram_gb"],
            "disk_free_gb": p["disk_free_gb"],
            "cpu_count": p["cpu_count"],
            "tools": json.dumps(p["tools"]),
            "max_complexity": p["max_complexity"],
            "updated_at": "now()",
        }
        db.upsert("fleet_topology", row)
        with _profile_lock:
            _profile_stats["profile_updates"] += 1
            _profile_stats["last_profile_ts"] = time.time()
        _log.info("registered profile: %s ram=%.1fGB disk=%.1fGB cpus=%d complexity=%s tools=%s",
                  p["runner_id"], p["ram_gb"], p["disk_free_gb"], p["cpu_count"],
                  p["max_complexity"], p["tools"])
    except Exception:
        _log.warning("register_profile: db write failed (non-fatal)")


def can_handle(task, complexity=None):
    """Check if THIS runner can handle the task's complexity.

    Fail-soft: returns True on any error so tasks are never dropped.
    """
    if not _topology_enabled():
        return True
    try:
        requested = complexity or (task.get("complexity") if isinstance(task, dict) else None)
        if not requested:
            return True
        with _profile_lock:
            p = _cached_profile
        if not p:
            p = profile()
        return _complexity_rank(requested) <= _complexity_rank(p.get("max_complexity", "moderate"))
    except Exception:
        _log.debug("can_handle: error, returning True (fail-soft)")
        return True


def best_runner_for(task, complexity=None):
    """Find the best runner for a task, considering capacity and history.

    Returns runner_id of a better-fit runner, or None if the current runner
    is already the best fit (meaning: don't redirect).
    """
    if not _topology_enabled():
        return None
    try:
        requested = complexity or (task.get("complexity") if isinstance(task, dict) else None)
        if not requested:
            return None

        runners = db.select("fleet_topology", {"select": "*"}) or []
        if not runners:
            return None

        my_id = _runner_id()
        req_rank = _complexity_rank(requested)

        # Filter to runners that can handle the complexity
        capable = [r for r in runners
                   if _complexity_rank(r.get("max_complexity", "simple")) >= req_rank]
        if not capable:
            return None

        # If we're already capable, no redirect needed
        if any(r.get("runner_id") == my_id for r in capable):
            return None

        # Prefer runners that have worked on this project before
        project_id = task.get("project_id") if isinstance(task, dict) else None
        if project_id:
            try:
                outcomes = db.select("outcomes", {
                    "select": "account",
                    "project_id": f"eq.{project_id}",
                    "limit": "50",
                    "order": "created_at.desc",
                }) or []
                past_runners = {o.get("account") for o in outcomes if o.get("account")}
                for r in capable:
                    if r.get("runner_id") in past_runners:
                        with _profile_lock:
                            _profile_stats["redirects"] += 1
                        _log.info("best_runner_for: redirecting to %s (project affinity)",
                                  r["runner_id"])
                        return r["runner_id"]
            except Exception:
                _log.debug("best_runner_for: project affinity lookup failed")

        # Fall back to the runner with the most RAM headroom
        best = max(capable, key=lambda r: r.get("ram_gb", 0))
        with _profile_lock:
            _profile_stats["redirects"] += 1
        _log.info("best_runner_for: redirecting to %s (best capacity)", best["runner_id"])
        return best["runner_id"]
    except Exception:
        _log.debug("best_runner_for: error, returning None (fail-soft)")
        return None


def topology_stats():
    """Return a snapshot of hardware-profiling statistics.

    Separated from the existing module-level stats() to avoid collision with
    the FleetTopology class's capacity/allocation stats.
    """
    if not _topology_enabled():
        return {"enabled": False}
    fleet_size = 0
    complexity_dist = {}
    try:
        rows = db.select("fleet_topology", {"select": "runner_id,max_complexity"}) or []
        fleet_size = len(rows)
        for r in rows:
            mc = r.get("max_complexity", "simple")
            complexity_dist[mc] = complexity_dist.get(mc, 0) + 1
    except Exception:
        _log.debug("topology_stats: db query failed")
    with _profile_lock:
        return {
            "enabled": True,
            "fleet_size": fleet_size,
            "complexity_distribution": complexity_dist,
            "redirects": _profile_stats["redirects"],
            "profile_updates": _profile_stats["profile_updates"],
        }


# Alias: the spec calls for stats() → {fleet_size, complexity_distribution, redirects}
stats = topology_stats
