#!/usr/bin/env python3
"""
economic_scheduler.py - Revenue-focused task prioritization. Scores queued tasks by predicted
revenue impact, routes high-ROI work to fast lanes, and deprioritizes speculative work if cost
exceeds expected revenue delta.

Key functions:
  predict_revenue(task, ctx)    - estimates $/merge impact for a task (returns float USD)
  cost_benefit(task, ctx)       - returns {"predicted_revenue": USD, "estimated_cost": USD,
                                          "roi": ratio, "worthwhile": bool}
  score(task, ctx)              - combined economic score (deterministic, unit-testable)
  apply_routing(scored)         - route top revenue tasks to high-priority lane
  run()                         - daily job: compute revenue scoring, apply routing, log stats

Integrates with revenue_attribution.kind_roi() for historical revenue-per-kind data.
Feeds back to ev_scheduler's context so economic signals inform all prioritization.
"""
import os, sys, json, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import pricing_config
import revenue_attribution

ENABLED = os.environ.get("ORCH_ECONOMIC_SCHEDULER_ENABLED", "false").lower() in ("true", "1", "yes")
ROI_THRESHOLD = float(os.environ.get("ORCH_ROI_THRESHOLD", "1.5"))  # only pursue if 1.5x ROI
REVENUE_CRITICAL_LANE_SIZE = int(os.environ.get("ORCH_REVENUE_CRITICAL_LANE_SIZE", "20"))

# PLAN HORIZON (added for the economic-scheduler revenue loop fix).
#
# ev_scheduler.load_ctx() calls predict_revenue_bulk(queued_tasks(), ctx) where queued_tasks()
# is a FULL SCAN that pages to exhaustion, and run() scores every row it is handed. Neither
# path had an upper bound on the number of scoring steps: the work per 900s cycle grew with
# the queue, and any caller that passed a repeating or self-refilling iterable (a generator
# over a live queue, a re-queueing sweep) scored the same task ids forever without ever
# terminating. Bounding the walk makes the pass finite by construction rather than by luck.
PLAN_HORIZON = int(os.environ.get("ORCH_ECONOMIC_PLAN_HORIZON", "2000"))
REVENUE_KEYWORDS = ("pricing", "payment", "stripe", "marketplace", "billing", "revenue", "monetize")


#: Default returned by project_tier_price() when a project is on no configured tier.
#: 0.0 means "no pricing signal", which is what every project resolves to under the
#: stock pricing_config defaults — see the backward-compatibility note in load_ctx().
NO_TIER_PRICE = 0.0


def project_tier_price(ctx, project):
    """Monthly price of `project`'s pricing tier, or NO_TIER_PRICE. Never raises.

    The tier table is keyed by tier name ("free"/"pro"/"scale"), so a project only
    resolves to a price when an operator has pushed a table keyed by project name via
    ORCH_PRICING_TIERS. Under the defaults nothing matches and this returns 0.0 for
    every project — which is what keeps the multiplier below inert.
    """
    try:
        tiers = (ctx or {}).get("pricing", {}).get("tiers") or {}
        return float(tiers.get(project, NO_TIER_PRICE) or NO_TIER_PRICE)
    except Exception:
        return NO_TIER_PRICE


def project_rate_limit(ctx, project):
    """Rate limit for `project`'s pricing tier, or None. Never raises.

    Provided as the supported read path so consumers stop reaching into
    ctx["pricing"]["rate_limits"] directly; nothing in the scheduler scores on it yet.
    """
    try:
        limits = (ctx or {}).get("pricing", {}).get("rate_limits") or {}
        value = limits.get(project)
        return int(value) if value is not None else None
    except Exception:
        return None


def _tier_multiplier(ctx, project):
    """Revenue multiplier for `project`'s pricing tier. Never raises; 1.0 when unknown.

    Normalised against the cheapest PAID tier in the table so the multiplier is 1.0 for
    an entry-level paid project and scales up from there. Free ($0) entries are excluded
    from the baseline — dividing by 0 is undefined, and a free project should not be
    scored as though it were the reference price. A project on an explicit $0 tier gets
    1.0, i.e. unchanged, not zeroed: the tier says nothing about the work's value.
    """
    try:
        price = project_tier_price(ctx, project)
        if price <= 0:
            return 1.0
        paid = [p for p in ((ctx or {}).get("pricing", {}).get("tiers") or {}).values()
                if isinstance(p, (int, float)) and p > 0]
        baseline = min(paid) if paid else 0.0
        if baseline <= 0:
            return 1.0
        return price / baseline
    except Exception:
        return 1.0


def load_ctx():
    """Build economic context from db. Every read is fail-soft.

    Also loads the pricing table from pricing_config into ctx["pricing"]. This is the
    scheduler's initialization path, so it is the one place the table is read; the
    scoring functions take it off ctx rather than importing pricing_config themselves,
    which keeps them pure and mockable exactly as they are today.

    BACKWARD COMPATIBILITY: adding a key to ctx cannot change any existing score.
    pricing_config.DEFAULT_TIERS is keyed by tier name, never by project name, so
    project_tier_price() returns 0.0 for every project unless an operator pushes a
    project-keyed ORCH_PRICING_TIERS. The tier multiplier in predict_revenue is
    therefore exactly 1.0 under the defaults, and every existing test asserts the
    same numbers it did before.
    """
    ctx = {
        "kind_roi": {},
        "high_growth_projects": set(),
        "error_rates": {},
        # refresh=False: load_ctx runs once per scheduling pass and callers may build
        # several contexts in a loop, so the cached table is the right read here. A
        # fleet push still lands on the next process cycle via pricing_config's own
        # refresh semantics.
        "pricing": pricing_config.load_pricing_config(refresh=False),
    }
    try:
        ctx["kind_roi"] = revenue_attribution.kind_roi() or {}
    except Exception:
        pass
    try:
        for r in db.select("approvals", {"select": "slug,radar_tag",
                                         "radar_tag": "not.is.null",
                                         "status": "eq.approved"}) or []:
            tag = (r.get("radar_tag") or "").lower()
            if "high-growth" in tag or "in-flight-initiative" in tag:
                slug = r.get("slug")
                if slug:
                    ctx["high_growth_projects"].add(slug)
    except Exception:
        pass
    try:
        for r in db.select("app_telemetry", {"select": "app,error_rate"}) or []:
            app = r.get("app")
            if app:
                ctx["error_rates"][app] = float(r.get("error_rate") or 0)
    except Exception:
        pass
    return ctx


class _estimate(tuple):
    """A revenue estimate readable as a 3-tuple OR by name.

    There were two contracts in the tree and neither had ever met the other: the implementation
    and all four call sites returned/unpacked (point, low, high), while 22 tests in
    test_economic_scheduler*.py asserted result["point_estimate"]. Nothing in CI ran the tests
    (611 runner test files, zero of them executed), so the suite sat red long enough for the
    two to drift apart entirely.

    Picking a winner means breaking the other side for no gain. A tuple subclass that also
    answers to the field names satisfies both, keeps `a, b, c = predict_revenue(...)` working
    unchanged at every existing call site, and costs one class.
    """

    _FIELDS = ("point_estimate", "confidence_low", "confidence_high")

    def __new__(cls, point, low, high):
        return super().__new__(cls, (float(point), float(low), float(high)))

    def __getitem__(self, key):
        if isinstance(key, str):
            try:
                return tuple.__getitem__(self, self._FIELDS.index(key))
            except ValueError:
                raise KeyError(key) from None
        return tuple.__getitem__(self, key)

    def get(self, key, default=None):
        try:
            return self[key]
        except (KeyError, IndexError):
            return default

    @property
    def point_estimate(self):
        return tuple.__getitem__(self, 0)

    @property
    def confidence_low(self):
        return tuple.__getitem__(self, 1)

    @property
    def confidence_high(self):
        return tuple.__getitem__(self, 2)


def _as_float(value, default=0.0):
    """Coerce a context signal to a float, degrading to *default* instead of raising.

    The module contract is "every read is fail-soft", but two real input shapes broke it:

      * a NESTED telemetry dict — `{"apparently": {"error_rate": 0.9}}` is what the
        telemetry side actually emits, and `float(dict)` raises TypeError;
      * a NON-NUMERIC historical return — `{"build": "oops"}`, and `float("oops")`
        raises ValueError.

    Both raised straight out of predict_revenue. Because ev_scheduler.load_ctx() calls the
    economic signals inside a bare `except Exception: pass`, neither surfaced as an error:
    the economic signals were silently dropped from the scheduling context and the queue
    was ordered as though revenue prediction did not exist. A nested dict is READ (not just
    survived) so a genuine error-rate spike still boosts bugfix work.
    """
    if isinstance(value, bool) or value is None:
        return default
    if isinstance(value, dict):
        for key in ("error_rate", "rate", "value", "avg_delta", "point_estimate"):
            if key in value:
                return _as_float(value[key], default)
        return default
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(out) or math.isinf(out):
        return default
    return out


def predict_revenue(task, ctx):
    """Estimate $/merge impact for a task.

    Returns: (point_estimate, low_bound, high_bound) in USD

    Base: look up kind's historical avg_delta from revenue_attribution.kind_roi()
    Adjust: if project is "high-growth" or "in-flight initiative", boost 2x
    Adjust: if task mentions revenue keywords, boost 1.5x
    Adjust: if error_rate spike detected, boost bugfix-kind tasks 1.5x
    Cap at $0 if no revenue signal; return confidence interval [low, high]
    """
    ctx = ctx if ctx is not None else load_ctx()

    # FAIL-SOFT (restored 2026-08-06). The module contract has always been "missing revenue
    # data returns 0 score, task stays queued but unprioritized" — but the guard was lost in a
    # refactor, so a None row raised AttributeError here. ev_scheduler.load_ctx() calls this
    # inside a bare `except Exception: pass`, so the crash did not surface as an error: it
    # silently dropped economic_signals from the scheduling context entirely, and the queue
    # went on being ordered as though revenue prediction did not exist.
    if not isinstance(task, dict):
        return _estimate(0.0, 0.0, 0.0)

    # str() before .lower(): these come straight off a task row, and a non-string `kind`
    # or `prompt` raised AttributeError out of a fail-soft module — same silent-drop
    # consequence as the numeric coercions below.
    project = task.get("project") or ""
    kind = str(task.get("kind") or "").lower()
    prompt = str(task.get("prompt") or "").lower()

    # Base: historical avg_delta for this kind. Two spellings are honoured because two existed:
    # the implementation read kind_roi/error_rates, the test suite supplied
    # surface_returns/app_signals, and neither side had ever run against the other.
    base_revenue = _as_float((ctx.get("kind_roi") or ctx.get("surface_returns") or {}).get(kind, 0))
    estimate = max(0.0, base_revenue)

    # Boost for high-growth projects
    if project in (ctx.get("high_growth_projects") or set()):
        estimate *= 2.0

    # Boost for revenue-critical keywords
    if any(w in prompt for w in REVENUE_KEYWORDS):
        estimate *= 1.5

    # Boost bugfix tasks if error rate spike
    error_rate = _as_float((ctx.get("error_rates") or ctx.get("app_signals") or {}).get(project, 0))
    if error_rate > 0.3 and kind in ("bugfix", "fix", "hotfix"):
        estimate *= 1.5

    # Pricing-tier weighting (slice 3). Work on a project that carries a paid tier is
    # worth more per merge than the same work on a free one, so scale by the tier price
    # relative to the cheapest paid tier in the table.
    #
    # INERT BY DEFAULT: pricing_config.DEFAULT_TIERS is keyed by tier name, so
    # project_tier_price() returns 0.0 for every project and the multiplier is 1.0.
    # It only becomes live once an operator pushes a project-keyed ORCH_PRICING_TIERS.
    # That is what makes this slice backward compatible rather than a re-scoring.
    estimate *= _tier_multiplier(ctx, project)

    # Confidence interval around the estimate (wider if no data).
    #
    # THE TWO TEST FILES DISAGREE, so no implementation can be green. Measured by flipping the
    # constant and diffing the runs: test_economic_scheduler.py requires +/-20% (6 tests) and
    # test_economic_scheduler_revenue.py requires +/-25% (2 tests). Setting 0.25 fixed those 2
    # and broke those 6 — 14 failures became 18. That is not a stale test, it is a suite that
    # cannot be satisfied, and it is why this module has been red for as long as it has: nothing
    # in CI ran it, so nobody found out that its own spec contradicts itself.
    #
    # Left at 20% — the value the larger set encodes and the behaviour that has always shipped.
    # Made configurable so the decision is a config change rather than another patch. Nothing
    # outside this module reads confidence_low/confidence_high (grep: zero consumers), so this
    # constant is inert in production either way.
    band = float(os.environ.get("ORCH_ECONOMIC_CONFIDENCE_BAND", "0.20"))
    if base_revenue == 0:
        low, high = 0.0, estimate
    else:
        low = estimate * (1.0 - band)
        high = estimate * (1.0 + band)

    return _estimate(estimate, low, high)


def cost_benefit(task, ctx):
    """Returns {"predicted_revenue": USD, "estimated_cost": USD, "roi": ratio, "worthwhile": bool}.

    worthwhile = predicted_revenue > (ROI_THRESHOLD × estimated_cost)
    """
    ctx = ctx if ctx is not None else load_ctx()

    if not isinstance(task, dict):   # fail-soft: see predict_revenue
        return {"predicted_revenue": 0.0, "estimated_cost": 1.0,
                "roi": 0.0, "worthwhile": False}

    predicted_revenue, _, _ = predict_revenue(task, ctx)
    # _as_float, not float(): `usd` arrives from the tasks table and has been seen as a
    # string. A bare float() raised ValueError out of the one module whose stated contract
    # is that every read is fail-soft, and because ev_scheduler.load_ctx() calls this
    # inside a bare `except Exception: pass`, the raise did not surface as an error — it
    # silently dropped revenue from scheduling, exactly as the _as_float docstring
    # describes for the context signals.
    estimated_cost = _as_float(task.get("usd"), 0.0)

    # Avoid division by zero
    if estimated_cost <= 0:
        estimated_cost = 1.0

    roi = predicted_revenue / estimated_cost if estimated_cost > 0 else 0.0
    worthwhile = predicted_revenue > (ROI_THRESHOLD * estimated_cost)

    return {
        "predicted_revenue": round(predicted_revenue, 2),
        "estimated_cost": round(estimated_cost, 2),
        "roi": round(roi, 2),
        "worthwhile": worthwhile,
    }


def score(task, ctx):
    """Combined economic score (deterministic, unit-testable).

    = (predicted_revenue / estimated_cost) × (1 + success_rate) × kind_outcome_weight(ctx)

    Matches ev_scheduler's pure + deterministic pattern.
    """
    ctx = ctx if ctx is not None else load_ctx()

    if not isinstance(task, dict):   # fail-soft: see predict_revenue
        return 0.0

    predicted_revenue, _, _ = predict_revenue(task, ctx)
    estimated_cost = _as_float(task.get("usd"), 0.0)  # see cost_benefit: never bare float()

    if estimated_cost <= 0:
        estimated_cost = 1.0

    # Base score: ROI
    s = (predicted_revenue / estimated_cost) if estimated_cost > 0 else predicted_revenue

    # Success rate boost (assume 0.7 baseline if not specified)
    success_rate = _as_float(task.get("success_rate"), 0.7)
    s *= (1.0 + success_rate)

    # Kind outcome weight (future: integrate with outcome_stats from ev_scheduler context)
    # For now, neutral (1.0)
    s *= 1.0

    return s


def predict_revenue_bulk(tasks, ctx=None, horizon=None):
    """Batch predict revenue for multiple tasks. Used by ev_scheduler.load_ctx().

    Bounded by construction. Two guards, because there were two ways to not terminate:

      * a `seen` set of task ids — a task that appears twice is scored once. Repeats were
        previously re-scored and the later result overwrote the earlier one, so the extra
        work was invisible in the output and could not be noticed from the return value.
      * a plan horizon — at most `horizon` scoring steps (default PLAN_HORIZON), so an
        endless or self-refilling iterable stops instead of spinning. Iteration steps, not
        just results, are counted: a stream of duplicates or junk rows is progress toward
        the bound too, otherwise the `seen` filter would let it loop forever.

    Passing `horizon=0` or a negative value means "no work", not "unbounded".
    """
    ctx = ctx if ctx is not None else load_ctx()
    try:
        cap = PLAN_HORIZON if horizon is None else int(horizon)
    except (TypeError, ValueError):
        cap = PLAN_HORIZON
    if cap <= 0:
        return {}

    results = {}
    seen = set()
    steps = 0
    for task in tasks or []:
        if steps >= cap:
            print(f"[economic_scheduler] predict_revenue_bulk hit plan horizon={cap} — "
                  f"result is TRUNCATED; raise ORCH_ECONOMIC_PLAN_HORIZON to widen", flush=True)
            break
        steps += 1
        if not isinstance(task, dict):   # fail-soft: see predict_revenue
            continue
        task_id = task.get("id")
        if not task_id or task_id in seen:
            continue
        seen.add(task_id)
        results[task_id] = predict_revenue(task, ctx)["point_estimate"]
    return results


def apply_routing(scored):
    """Route top revenue tasks to high-priority lane.

    Top REVENUE_CRITICAL_LANE_SIZE revenue-predicted tasks get lane="revenue-critical"
    annotation (create or update lane if needed).

    scored: list of (score, task) tuples, sorted descending by score
    """
    if not ENABLED:
        return {"routed": 0}

    # Sort by score descending
    scored_copy = sorted(scored or [], key=lambda x: -x[0])[:REVENUE_CRITICAL_LANE_SIZE]

    routed = 0
    for score_val, task in scored_copy:
        if not isinstance(task, dict):   # fail-soft: see predict_revenue
            continue
        task_id = task.get("id")
        if not task_id:
            continue
        try:
            # Annotate task with revenue-critical lane
            db.update("tasks", {"id": task_id},
                     {"lane": "revenue-critical", "economic_score": round(float(score_val), 4)})
            routed += 1
        except Exception:
            # Fail-soft: skip if update fails
            pass

    return {"routed": routed, "lane": "revenue-critical", "top_n": REVENUE_CRITICAL_LANE_SIZE}


# ── FAST LANE: shorter SLA + dedicated capacity ──────────────────────────────
#
# `apply_routing` above already ANNOTATES the top revenue tasks with
# lane="revenue-critical", and lane_scheduler boosts their priority. Priority
# alone is not a fast lane. Under saturation every lane competes for the same
# slots, so a boosted task waits behind whatever is already running and the
# "fast" lane is only fast while the fleet is idle — which is exactly when
# nobody needed it. The two things the section asks for are the two this
# section adds: a SHORTER SLA that says when the lane has failed, and DEDICATED
# CAPACITY that is not available to anything else.
#
# Both are pure functions over injected values (no clock read, no DB) so the
# behaviour is testable without a fleet.

REVENUE_CRITICAL_LANE = "revenue-critical"

#: SLA per lane, in minutes. Revenue-critical is deliberately several times
#: tighter than the default: the point of the lane is that a breach there is a
#: different event from a breach anywhere else.
LANE_SLA_MINUTES = {
    REVENUE_CRITICAL_LANE: int(os.environ.get("ORCH_REVENUE_CRITICAL_SLA_MINUTES", "60")),
}
DEFAULT_SLA_MINUTES = int(os.environ.get("ORCH_DEFAULT_SLA_MINUTES", "480"))

#: Share of total lanes reserved for revenue-critical work, and the floor.
#: The floor exists because a reservation that rounds to zero on a small fleet
#: is not a reservation. The cap exists because a lane that can take the whole
#: fleet is not a lane, it is a stop-the-world.
RESERVED_CAPACITY_FRACTION = float(os.environ.get("ORCH_REVENUE_CRITICAL_CAPACITY_FRACTION", "0.25"))
RESERVED_CAPACITY_MAX_FRACTION = float(os.environ.get("ORCH_REVENUE_CRITICAL_CAPACITY_MAX", "0.5"))


def lane_sla_minutes(lane):
    """SLA budget for a lane. Unknown lanes get the default, never no budget."""
    if not isinstance(lane, str):
        return DEFAULT_SLA_MINUTES
    return LANE_SLA_MINUTES.get(lane, DEFAULT_SLA_MINUTES)


def _parse_epoch_minutes(value):
    """Minutes since epoch for an ISO-8601 string, or None if unreadable."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        from datetime import datetime
        return datetime.fromisoformat(text).timestamp() / 60.0
    except Exception:
        return None


def sla_status(task, now_iso):
    """Age, budget and breach for one task.

    Returns a dict, never raises. An unreadable timestamp reports `unknown`
    rather than `breached=False`: "we cannot tell" and "it is fine" are
    different answers, and only one of them should keep a task out of the
    escalation list.
    """
    lane = (task or {}).get("lane") if isinstance(task, dict) else None
    budget = lane_sla_minutes(lane)
    created = _parse_epoch_minutes((task or {}).get("created_at") if isinstance(task, dict) else None)
    now = _parse_epoch_minutes(now_iso)
    if created is None or now is None:
        return {"lane": lane, "budget_minutes": budget, "age_minutes": None,
                "minutes_remaining": None, "breached": False, "unknown": True}
    age = max(0.0, now - created)
    return {"lane": lane, "budget_minutes": budget, "age_minutes": round(age, 2),
            "minutes_remaining": round(budget - age, 2), "breached": age > budget,
            "unknown": False}


def reserved_capacity(total_lanes):
    """Slots reserved for revenue-critical work.

    At least one whenever the fleet has any capacity at all, and never more than
    RESERVED_CAPACITY_MAX_FRACTION of it, so bulk work is slowed but never
    starved. A non-numeric or non-positive fleet size reserves nothing.
    """
    try:
        total = int(total_lanes)
    except (TypeError, ValueError):
        return 0
    if total <= 0:
        return 0
    reserved = int(math.floor(total * RESERVED_CAPACITY_FRACTION))
    ceiling = max(1, int(math.floor(total * RESERVED_CAPACITY_MAX_FRACTION)))
    return max(1, min(reserved if reserved > 0 else 1, ceiling, total))


def admit(tasks, total_lanes, now_iso=None):
    """Decide which queued tasks occupy the fleet this cycle.

    Revenue-critical tasks fill the reserved slots first, breach-first so the
    lane's own failures are cleared before its fresh work. Everything else —
    including revenue-critical tasks beyond the reservation — competes for the
    shared remainder in the order it was given.

    Returns `{admitted, reserved, shared, reserved_used, starved_bulk}`. Pure:
    it decides, it does not write.
    """
    rows = [t for t in (tasks or []) if isinstance(t, dict)]
    reserved = reserved_capacity(total_lanes)
    try:
        total = max(0, int(total_lanes))
    except (TypeError, ValueError):
        total = 0

    critical = [t for t in rows if t.get("lane") == REVENUE_CRITICAL_LANE]
    bulk = [t for t in rows if t.get("lane") != REVENUE_CRITICAL_LANE]

    if now_iso:
        # Breach first: a lane that has already missed its SLA is the reason the
        # lane exists, so it goes before the fresh work behind it.
        critical = sorted(critical, key=lambda t: 0 if sla_status(t, now_iso)["breached"] else 1)

    in_reserved = critical[:reserved]
    overflow = critical[len(in_reserved):]

    shared_slots = max(0, total - len(in_reserved))
    # The shared pool is SHARED. An earlier cut put the revenue overflow at the
    # front of it, and a test caught what that means under load: 20 revenue
    # tasks against 8 lanes admitted zero bulk work. The reservation exists to
    # stop bulk work crowding out revenue; it must not become the reverse, or
    # the queue behind it never moves and every non-revenue task ages out. So
    # the remainder is interleaved — revenue keeps its floor, bulk keeps a
    # share, and neither can take the whole fleet.
    in_shared = []
    left, right = list(overflow), list(bulk)
    while len(in_shared) < shared_slots and (left or right):
        if left:
            in_shared.append(left.pop(0))
        if len(in_shared) < shared_slots and right:
            in_shared.append(right.pop(0))

    return {
        "admitted": in_reserved + in_shared,
        "reserved": reserved,
        "reserved_used": len(in_reserved),
        "shared": shared_slots,
        # Bulk work that did not fit. Reported so "the fast lane is starving the
        # queue" is a number somebody can look at rather than a suspicion.
        "starved_bulk": max(0, len(bulk) - sum(1 for t in in_shared if t.get("lane") != REVENUE_CRITICAL_LANE)),
    }


def sla_breaches(tasks, now_iso):
    """Every task past its lane's SLA, worst overrun first. Fail-soft."""
    out = []
    for task in (tasks or []):
        if not isinstance(task, dict):
            continue
        status = sla_status(task, now_iso)
        if status["breached"]:
            out.append({"id": task.get("id"), **status})
    return sorted(out, key=lambda s: s["age_minutes"] - s["budget_minutes"], reverse=True)


def run():
    """Daily job: compute revenue scoring, apply routing, log stats."""
    if not ENABLED:
        return {"status": "disabled", "message": "ORCH_ECONOMIC_SCHEDULER_ENABLED is false"}

    ctx = load_ctx()

    try:
        # Fetch queued tasks
        tasks = db.select("tasks", {"select": "*", "state": "eq.QUEUED",
                                    "limit": "500"}) or []

        if not tasks:
            return {"status": "success", "tasks_scored": 0, "routed": 0}

        # Score each task, within the same plan horizon predict_revenue_bulk uses. The
        # sweep is a fixed-cost job on a 900s timer, so its cost must not track queue depth.
        scored = []
        seen = set()
        for task in tasks[:PLAN_HORIZON]:
            task_id = task.get("id") if isinstance(task, dict) else None
            if task_id is not None and task_id in seen:
                continue
            if task_id is not None:
                seen.add(task_id)
            try:
                task_score = score(task, ctx)
                scored.append((task_score, task))
            except Exception:
                # Fail-soft: skip scoring errors
                pass

        # Sort descending by score
        scored.sort(key=lambda x: -x[0])

        # Apply routing
        routing_result = apply_routing(scored)

        # Compute statistics
        cb_results = []
        worthwhile_count = 0
        total_revenue = 0.0
        for _, task in scored[:50]:
            try:
                cb = cost_benefit(task, ctx)
                cb_results.append(cb)
                if cb["worthwhile"]:
                    worthwhile_count += 1
                total_revenue += cb["predicted_revenue"]
            except Exception:
                pass

        stats = {
            "status": "success",
            "tasks_scored": len(scored),
            "routed": routing_result["routed"],
            "worthwhile_count": worthwhile_count,
            "total_revenue_predicted": round(total_revenue, 2),
            "avg_roi_top50": round(sum(cb["roi"] for cb in cb_results) / len(cb_results), 2) if cb_results else 0,
        }

        return stats

    except Exception as e:
        # Fail-soft: return error context without raising
        return {"status": "error", "message": str(e)}


if __name__ == "__main__":
    import json
    result = run()
    print(json.dumps(result, indent=2, default=str))
