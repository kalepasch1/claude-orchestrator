#!/usr/bin/env python3
"""
subscription_tracker.py - track subscription capacity across multiple AI vendors
(Claude, ChatGPT/OpenAI, Gemini, DeepSeek, etc.) so the orchestrator routes tasks
to the cheapest execution tier with available capacity.

Each subscription has estimated rate limits (calls/hour, calls/day), a monthly cost,
and cooldown state. The tracker records every call outcome (success/fail/rate_limited),
detects exhaustion, and sorts available subscriptions by cost-effectiveness.

Config: env var ORCH_SUBSCRIPTIONS (JSON array) or ~/.claude-orchestrator/subscriptions.json
[
  {"name": "claude-max", "vendor": "anthropic", "tier": "max", "monthly_cost": 100,
   "est_calls_hour": 80, "est_calls_day": 500,
   "models": ["claude-opus-4-8", "claude-sonnet-4-6", "claude-haiku-4-5-20251001"],
   "exec_method": "cli"},
  ...
]

API (module-level singletons):
  record_call(sub_name, outcome, model=None)
  available_subscriptions()          -> list sorted by cost-effectiveness
  recommend_subscriptions(api_spend) -> list of ROI-positive subscription suggestions
  capacity_report()                  -> dict of all subscription states
"""
import os, json, time, threading, datetime

HOME = os.environ.get("CLAUDE_ORCH_HOME", os.path.expanduser("~/.claude-orchestrator"))
CFG_FILE = os.path.join(HOME, "subscriptions.json")
STATE_FILE = os.path.join(HOME, "subscriptions_state.json")
COOLDOWN_BASE = int(os.environ.get("ORCH_SUB_COOLDOWN", str(10 * 60)))       # 10 min
COOLDOWN_MAX = int(os.environ.get("ORCH_SUB_COOLDOWN_MAX", str(4 * 3600)))   # 4 hr
HISTORY_DAYS = int(os.environ.get("ORCH_SUB_HISTORY_DAYS", "30"))

# Vendor catalog: subscriptions that COULD be purchased (for recommend_subscriptions).
# Keep this lightweight; the operator can override via env or config file.
_DEFAULT_CATALOG = [
    {"name": "claude-max", "vendor": "anthropic", "tier": "max", "monthly_cost": 100,
     "est_calls_hour": 80, "est_calls_day": 500,
     "models": ["claude-opus-4-8", "claude-sonnet-4-6", "claude-haiku-4-5-20251001"],
     "exec_method": "cli"},
    {"name": "chatgpt-pro", "vendor": "openai", "tier": "pro", "monthly_cost": 200,
     "est_calls_hour": 100, "est_calls_day": 600,
     "models": ["gpt-5.5", "gpt-5.4-mini", "o3"], "exec_method": "aider"},
    {"name": "gemini-sub", "vendor": "google", "tier": "advanced", "monthly_cost": 20,
     "est_calls_hour": 60, "est_calls_day": 400,
     "models": ["gemini-2.5-pro", "gemini-2.0-flash"], "exec_method": "aider"},
    {"name": "deepseek-sub", "vendor": "deepseek", "tier": "pro", "monthly_cost": 10,
     "est_calls_hour": 120, "est_calls_day": 800,
     "models": ["deepseek-r1", "deepseek-v3"], "exec_method": "aider"},
]


class SubscriptionTracker:
    """Thread-safe tracker for multi-vendor subscription capacity."""

    def __init__(self):
        self._lock = threading.Lock()
        self.subs = self._load_cfg()
        self.state = self._load_state()

    # ── config / state persistence ──────────────────────────────────────

    def _load_cfg(self):
        # 1) env var (JSON)
        env = os.environ.get("ORCH_SUBSCRIPTIONS", "")
        if env:
            try:
                return json.loads(env)
            except Exception:
                pass
        # 2) config file (~/.claude-orchestrator/subscriptions.json)
        if os.path.exists(CFG_FILE):
            try:
                with open(CFG_FILE, errors="replace") as f:
                    return json.load(f)
            except Exception:
                pass
        # 3) bundled default (runner/subscriptions_default.json)
        _bundled = os.path.join(os.path.dirname(os.path.abspath(__file__)), "subscriptions_default.json")
        if os.path.exists(_bundled):
            try:
                with open(_bundled, errors="replace") as f:
                    return json.load(f)
            except Exception:
                pass
        return []

    def _load_state(self):
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE, errors="replace") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _save_state(self):
        try:
            os.makedirs(HOME, exist_ok=True)
            with open(STATE_FILE, "w") as f:
                json.dump(self.state, f)
        except Exception:
            pass

    # ── call recording ──────────────────────────────────────────────────

    def record_call(self, sub_name, outcome, model=None):
        """Record a call outcome: 'success', 'fail', or 'rate_limited'."""
        with self._lock:
            st = self.state.setdefault(sub_name, {"history": [], "cooldown_until": 0, "exh_hits": 0})
            entry = {"ts": time.time(), "outcome": outcome}
            if model:
                entry["model"] = model
            st.setdefault("history", []).append(entry)
            # prune history older than HISTORY_DAYS
            cutoff = time.time() - HISTORY_DAYS * 86400
            st["history"] = [h for h in st["history"] if h.get("ts", 0) > cutoff]
            if outcome == "rate_limited":
                self._apply_cooldown(sub_name, st)
            elif outcome == "success":
                st["cooldown_until"] = 0
                st["exh_hits"] = 0
            self._save_state()

    def _apply_cooldown(self, sub_name, st):
        hits = int(st.get("exh_hits", 0)) + 1
        st["exh_hits"] = hits
        st["cooldown_until"] = time.time() + min(COOLDOWN_BASE * (2 ** (hits - 1)), COOLDOWN_MAX)

    # ── availability / routing ──────────────────────────────────────────

    def _is_available(self, sub):
        st = self.state.get(sub["name"], {})
        if time.time() < float(st.get("cooldown_until", 0)):
            return False
        # check hourly / daily rate estimates
        now = time.time()
        history = st.get("history", [])
        hour_ago = now - 3600
        day_ago = now - 86400
        calls_hour = sum(1 for h in history if h.get("ts", 0) > hour_ago)
        calls_day = sum(1 for h in history if h.get("ts", 0) > day_ago)
        if calls_hour >= sub.get("est_calls_hour", 9999):
            return False
        if calls_day >= sub.get("est_calls_day", 99999):
            return False
        return True

    def _cost_per_call(self, sub):
        """Lower is better. Monthly cost / estimated daily calls * 30."""
        daily = sub.get("est_calls_day", 1)
        monthly_calls = daily * 30
        cost = sub.get("monthly_cost", 0)
        if monthly_calls <= 0:
            return float("inf")
        return cost / monthly_calls

    def available_subscriptions(self):
        """Return subscriptions with remaining capacity, sorted cheapest-per-call first."""
        with self._lock:
            avail = [s for s in self.subs if self._is_available(s)]
            avail.sort(key=self._cost_per_call)
            return avail

    # ── recommendations ─────────────────────────────────────────────────

    def recommend_subscriptions(self, api_spend=None):
        """Analyze spend and suggest subscriptions that would save money.

        api_spend: dict mapping vendor name -> monthly API spend in USD.
                   If None, attempts to pull from usage_meter.
        """
        if api_spend is None:
            api_spend = self._fetch_api_spend()
        catalog = self._load_catalog()
        active_vendors = {s["vendor"] for s in self.subs}
        recs = []
        for candidate in catalog:
            vendor = candidate.get("vendor", "")
            if vendor in active_vendors:
                continue  # already subscribed
            vendor_spend = float(api_spend.get(vendor, 0))
            sub_cost = float(candidate.get("monthly_cost", 0))
            if vendor_spend <= 0 or sub_cost <= 0:
                continue
            savings = vendor_spend - sub_cost
            roi_pct = (savings / sub_cost) * 100 if sub_cost else 0
            if savings > 0:
                recs.append({
                    "subscription": candidate["name"],
                    "vendor": vendor,
                    "tier": candidate.get("tier", ""),
                    "monthly_cost": sub_cost,
                    "current_api_spend": vendor_spend,
                    "monthly_savings": round(savings, 2),
                    "roi_pct": round(roi_pct, 1),
                    "models": candidate.get("models", []),
                })
        recs.sort(key=lambda r: r["monthly_savings"], reverse=True)
        return recs

    def _fetch_api_spend(self):
        """Best-effort pull from usage_meter; returns {} on any failure."""
        try:
            import usage_meter
            rows = usage_meter.spend()
            out = {}
            for r in rows:
                prov = r.get("provider", "")
                out[prov] = out.get(prov, 0) + float(r.get("spent", 0))
            return out
        except Exception:
            return {}

    def _load_catalog(self):
        cat_env = os.environ.get("ORCH_SUB_CATALOG", "")
        if cat_env:
            try:
                return json.loads(cat_env)
            except Exception:
                pass
        cat_file = os.path.join(HOME, "subscription_catalog.json")
        if os.path.exists(cat_file):
            try:
                with open(cat_file, errors="replace") as f:
                    return json.load(f)
            except Exception:
                pass
        return list(_DEFAULT_CATALOG)

    # ── reporting ───────────────────────────────────────────────────────

    def capacity_report(self):
        """Return current state of all subscriptions."""
        with self._lock:
            now = time.time()
            report = []
            for sub in self.subs:
                st = self.state.get(sub["name"], {})
                history = st.get("history", [])
                hour_ago = now - 3600
                day_ago = now - 86400
                calls_hour = sum(1 for h in history if h.get("ts", 0) > hour_ago)
                calls_day = sum(1 for h in history if h.get("ts", 0) > day_ago)
                successes = sum(1 for h in history if h.get("outcome") == "success")
                fails = sum(1 for h in history if h.get("outcome") == "fail")
                rate_limits = sum(1 for h in history if h.get("outcome") == "rate_limited")
                total = len(history)
                cooldown_until = float(st.get("cooldown_until", 0))
                cooling = now < cooldown_until
                report.append({
                    "name": sub["name"],
                    "vendor": sub.get("vendor", ""),
                    "tier": sub.get("tier", ""),
                    "monthly_cost": sub.get("monthly_cost", 0),
                    "available": not cooling and calls_hour < sub.get("est_calls_hour", 9999)
                                 and calls_day < sub.get("est_calls_day", 99999),
                    "cooling_down": cooling,
                    "cooldown_remaining_s": max(0, int(cooldown_until - now)) if cooling else 0,
                    "calls_last_hour": calls_hour,
                    "calls_last_day": calls_day,
                    "est_calls_hour": sub.get("est_calls_hour", 0),
                    "est_calls_day": sub.get("est_calls_day", 0),
                    "success_rate": round(successes / total, 3) if total else None,
                    "total_calls_period": total,
                    "successes": successes,
                    "fails": fails,
                    "rate_limits": rate_limits,
                    "models": sub.get("models", []),
                    "exec_method": sub.get("exec_method", ""),
                })
            return report

    def stats(self):
        """Operator/test introspection."""
        return {"subscriptions": len(self.subs), "state_keys": list(self.state.keys())}

    def invalidate(self, sub_name=None):
        """Clear state for one or all subscriptions."""
        with self._lock:
            if sub_name:
                self.state.pop(sub_name, None)
            else:
                self.state.clear()
            self._save_state()


# ── module-level singleton ──────────────────────────────────────────────

_tracker = None
_init_lock = threading.Lock()


def _get():
    global _tracker
    if _tracker is None:
        with _init_lock:
            if _tracker is None:
                _tracker = SubscriptionTracker()
    return _tracker


def record_call(sub_name, outcome, model=None):
    """Record a call outcome: 'success', 'fail', or 'rate_limited'."""
    try:
        _get().record_call(sub_name, outcome, model)
    except Exception:
        pass


def available_subscriptions():
    """Return subscriptions with capacity, cheapest first."""
    try:
        return _get().available_subscriptions()
    except Exception:
        return []


def recommend_subscriptions(api_spend=None):
    """Suggest new subscriptions that would save money vs current API spend."""
    try:
        return _get().recommend_subscriptions(api_spend)
    except Exception:
        return []


def capacity_report():
    """Current state of all tracked subscriptions."""
    try:
        return _get().capacity_report()
    except Exception:
        return []


def stats():
    try:
        return _get().stats()
    except Exception:
        return {}


def invalidate(sub_name=None):
    try:
        _get().invalidate(sub_name)
    except Exception:
        pass


if __name__ == "__main__":
    import pprint
    t = SubscriptionTracker()
    print(f"Loaded {len(t.subs)} subscriptions")
    avail = t.available_subscriptions()
    print("Available:", [s["name"] for s in avail])
    print("\nCapacity report:")
    pprint.pprint(t.capacity_report())
    recs = t.recommend_subscriptions({"openai": 350, "google": 50})
    if recs:
        print("\nRecommendations:")
        pprint.pprint(recs)
