#!/usr/bin/env python3
"""
outcome_router.py - outcome-weighted model router.

Tracks per-slug-prefix success rates by model and routes tasks to the cheapest
model whose historical success rate exceeds a configurable threshold.  Falls
back to model_router.route() when data is insufficient or on any error.

Env knobs:
    ORCH_OUTCOME_ROUTER_ENABLED      "true" (default) / "false"
    ORCH_OUTCOME_ROUTER_THRESHOLD    minimum success rate to trust a tier (default 0.8)
    ORCH_OUTCOME_ROUTER_MIN_SAMPLES  minimum observations before trusting a tier (default 5)
    ORCH_OUTCOME_ROUTER_TTL          cache TTL in seconds (default 300)
"""
import os, sys, time, threading
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import log as _log_mod
_log = _log_mod.get("outcome_router")
import db
import model_router

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ENABLED       = os.environ.get("ORCH_OUTCOME_ROUTER_ENABLED", "true").lower() == "true"
THRESHOLD     = float(os.environ.get("ORCH_OUTCOME_ROUTER_THRESHOLD", "0.8"))
MIN_SAMPLES   = int(os.environ.get("ORCH_OUTCOME_ROUTER_MIN_SAMPLES", "5"))
TTL           = int(os.environ.get("ORCH_OUTCOME_ROUTER_TTL", "300"))

# Cheapest first
TIER_ORDER = [model_router.HAIKU, model_router.SONNET, model_router.OPUS]

# Rough cost multipliers for savings estimates (relative to Haiku = 1)
_COST_MULT = {model_router.HAIKU: 1.0, model_router.SONNET: 5.0, model_router.OPUS: 15.0}


def _slug_prefix(slug: str) -> str:
    """First two hyphen-delimited segments: 'add-field-users-email' -> 'add-field'."""
    parts = (slug or "").split("-")
    return "-".join(parts[:2]) if len(parts) >= 2 else (slug or "unknown")


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
class _OutcomeRouter:
    def __init__(self):
        self._lock = threading.Lock()
        self._cache: dict = {}          # prefix -> {model -> {total, success}}
        self._cache_ts: float = 0.0
        self._decisions: int = 0
        self._savings: float = 0.0      # estimated cost-units saved
        self._inmemory: dict = {}        # prefix -> {model -> {total, success}}

    # ----- cache refresh ---------------------------------------------------
    def _refresh(self):
        now = time.time()
        if now - self._cache_ts < TTL:
            return
        try:
            rows = db.select("outcomes", {
                "select": "slug,model,integrated,tests_passed",
                "limit": "10000",
            }) or []
            agg: dict = {}
            for r in rows:
                prefix = _slug_prefix(r.get("slug") or "")
                mdl = r.get("model") or ""
                bucket = agg.setdefault(prefix, {}).setdefault(mdl, {"total": 0, "success": 0})
                bucket["total"] += 1
                if r.get("integrated") or r.get("tests_passed"):
                    bucket["success"] += 1
            self._cache = agg
            self._cache_ts = now
        except Exception as exc:
            _log.warning("outcome_router refresh failed: %s", exc)

    def _merged_stats(self, prefix: str) -> dict:
        """Merge DB-cache and in-memory stats for a prefix."""
        merged: dict = {}
        for src in (self._cache.get(prefix, {}), self._inmemory.get(prefix, {})):
            for mdl, bucket in src.items():
                m = merged.setdefault(mdl, {"total": 0, "success": 0})
                m["total"] += bucket["total"]
                m["success"] += bucket["success"]
        return merged

    # ----- public API ------------------------------------------------------
    def recommend(self, task: dict, attempt: int = 1) -> dict:
        if not ENABLED:
            return model_router.route(task.get("prompt") or task.get("slug") or "", attempt)
        try:
            with self._lock:
                self._refresh()
                prefix = _slug_prefix(task.get("slug") or "")
                stats = self._merged_stats(prefix)

                fallback = model_router.route(task.get("prompt") or task.get("slug") or "", attempt)

                if not stats:
                    return fallback

                # Find cheapest model above threshold with enough samples
                chosen = None
                for mdl in TIER_ORDER:
                    bucket = stats.get(mdl)
                    if not bucket or bucket["total"] < MIN_SAMPLES:
                        continue
                    rate = bucket["success"] / bucket["total"]
                    if rate >= THRESHOLD:
                        chosen = mdl
                        break  # cheapest first

                if chosen is None:
                    return fallback

                # Handle retries: escalate from chosen tier
                tier_idx = TIER_ORDER.index(chosen)
                escalated_idx = min(tier_idx + max(0, attempt - 1), len(TIER_ORDER) - 1)
                final = TIER_ORDER[escalated_idx]

                # Compute confidence from sample size
                bucket = stats[chosen]
                confidence = min(1.0, bucket["total"] / (MIN_SAMPLES * 4))
                rate = bucket["success"] / bucket["total"]

                # Track savings (vs what model_router would have picked)
                fb_cost = _COST_MULT.get(fallback.get("model", model_router.SONNET), 5.0)
                chosen_cost = _COST_MULT.get(final, 1.0)
                if chosen_cost < fb_cost:
                    self._savings += fb_cost - chosen_cost

                self._decisions += 1
                reason = (f"outcome-routed: prefix={prefix} model={final} "
                          f"rate={rate:.2f} n={bucket['total']} "
                          f"(attempt {attempt})")
                _log.info(reason)
                return {"model": final, "reason": reason, "confidence": round(confidence, 3)}
        except Exception as exc:
            _log.warning("outcome_router.recommend failed: %s", exc)
            return model_router.route(task.get("prompt") or task.get("slug") or "", attempt)

    def record_outcome(self, slug: str, model: str, success: bool):
        try:
            with self._lock:
                prefix = _slug_prefix(slug)
                bucket = self._inmemory.setdefault(prefix, {}).setdefault(
                    model, {"total": 0, "success": 0})
                bucket["total"] += 1
                if success:
                    bucket["success"] += 1
        except Exception as exc:
            _log.warning("outcome_router.record_outcome failed: %s", exc)

    def stats(self) -> dict:
        try:
            with self._lock:
                self._refresh()
                # Count prefixes with enough data
                all_prefixes = set(self._cache.keys()) | set(self._inmemory.keys())
                covered = 0
                for p in all_prefixes:
                    merged = self._merged_stats(p)
                    if any(b["total"] >= MIN_SAMPLES for b in merged.values()):
                        covered += 1
                return {
                    "routing_decisions": self._decisions,
                    "cost_savings_estimate": round(self._savings, 2),
                    "prefix_coverage": {
                        "total_prefixes": len(all_prefixes),
                        "prefixes_with_data": covered,
                    },
                    "enabled": ENABLED,
                    "threshold": THRESHOLD,
                    "min_samples": MIN_SAMPLES,
                    "ttl": TTL,
                }
        except Exception as exc:
            _log.warning("outcome_router.stats failed: %s", exc)
            return {"routing_decisions": 0, "cost_savings_estimate": 0, "prefix_coverage": {}}


# ---------------------------------------------------------------------------
# Module-level singleton + delegation
# ---------------------------------------------------------------------------
_instance = _OutcomeRouter()


def recommend(task: dict, attempt: int = 1) -> dict:
    """Route a task to the cheapest model with proven success for its slug prefix."""
    return _instance.recommend(task, attempt)


def record_outcome(slug: str, model: str, success: bool):
    """Record a task outcome for future routing decisions."""
    _instance.record_outcome(slug, model, success)


def stats() -> dict:
    """Return routing statistics."""
    return _instance.stats()
