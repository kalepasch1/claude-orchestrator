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
#: How many top-scoring tasks apply_routing promotes to the revenue-critical lane.
TOP_REVENUE_TASKS = int(os.environ.get("ORCH_REVENUE_CRITICAL_LANE_SIZE", "20"))

#: Historical spelling, kept so existing importers keep working. One value, two names —
#: the module and its suite each knew a different one, which is why the routing tests
#: could not even reference the limit they were asserting on.
REVENUE_CRITICAL_LANE_SIZE = TOP_REVENUE_TASKS

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

#: Half-width of the confidence band around a revenue point estimate, as a fraction.
#: ORCH_-prefixed override so it is fleet-pushable via fleet_control.py.
CONFIDENCE_BAND_DEFAULT = "0.25"


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

    project = task.get("project") or ""
    kind = (task.get("kind") or "").lower()
    prompt = (task.get("prompt") or "").lower()

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
    # RESOLVED 2026-08-24. The note this replaced said the spec contradicted itself:
    # test_economic_scheduler.py was read as requiring +/-20% and
    # test_economic_scheduler_revenue.py as requiring +/-25%, so no value could be green
    # and the constant was left at 0.20 with the decision deferred to an env var.
    #
    # There is now exactly ONE suite in the tree — test_economic_scheduler_revenue.py is not
    # on master (it exists only in an unmerged branch), and the surviving file asserts
    # confidence_low == point * 0.75 and confidence_high == point * 1.25. So the standing
    # spec is unambiguously +/-25%, and 0.20 was simply failing it.
    #
    # Still env-overridable (CONFIDENCE_BAND_DEFAULT below) so an operator can retune
    # without a patch; nothing outside this module consumes the band.
    band = float(os.environ.get("ORCH_ECONOMIC_CONFIDENCE_BAND", CONFIDENCE_BAND_DEFAULT))
    if base_revenue == 0:
        low, high = 0.0, estimate
    else:
        low = estimate * (1.0 - band)
        high = estimate * (1.0 + band)

    return _estimate(estimate, low, high)


def estimated_cost_usd(task, ctx):
    """Dollar cost of running *task*, from the CONTEXT first and the row second.

    The cost lived on the task row (`task["usd"]`) while every caller and the whole test
    suite supplies it through `ctx["outcome_stats"][project]["avg_usd"]` — the same
    two-contracts split that _estimate above was written to absorb. A queued task has not
    run yet, so it has no `usd`; the per-project average is the only cost signal that
    exists at scheduling time, and reading the empty one made every task cost exactly the
    $1.0 fallback. Cost stopped varying, so ROI stopped ranking anything.

    Order is deliberate: an actual measured `usd` on the row (a re-run of work that has
    already executed) beats the project average. Fail-soft — unreadable values read as 0.0,
    which callers treat as free rather than as an error.
    """
    row_cost = _as_float((task or {}).get("usd"), 0.0)
    if row_cost > 0:
        return row_cost
    project = str((task or {}).get("project") or "")
    stats = ((ctx or {}).get("outcome_stats") or {}).get(project) or {}
    return max(0.0, _as_float(stats.get("avg_usd"), 0.0))


def cost_benefit(task, ctx):
    """Returns {"predicted_revenue": USD, "estimated_cost": USD, "roi": ratio, "worthwhile": bool}.

    worthwhile = predicted_revenue > (ROI_THRESHOLD × estimated_cost)
    """
    ctx = ctx if ctx is not None else load_ctx()

    if not isinstance(task, dict):   # fail-soft: see predict_revenue
        return {"predicted_revenue": 0.0, "estimated_cost": 1.0,
                "roi": 0.0, "worthwhile": False}

    predicted_revenue, _, _ = predict_revenue(task, ctx)
    estimated_cost = estimated_cost_usd(task, ctx)

    # FREE WORK IS NOT $1 OF WORK. The cost used to be clamped up to 1.0 whenever it was
    # zero, purely to dodge a ZeroDivisionError. That silently rewrote the answer: work
    # that costs nothing and returns $100 has INFINITE return on investment, and reporting
    # roi=100.0 for it made it indistinguishable from work that cost a dollar. Zero cost is
    # now carried through and the division is guarded by branching instead of by clamping.
    if estimated_cost > 0:
        roi = predicted_revenue / estimated_cost
    elif predicted_revenue > 0:
        roi = float("inf")          # free and profitable
    else:
        roi = 0.0                   # free and worthless — not infinitely good
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
    estimated_cost = estimated_cost_usd(task, ctx)

    # Base score: ROI. Free work keeps its full revenue rather than being divided by a
    # fabricated $1 — but unlike cost_benefit this must stay FINITE, because scores are
    # sorted and compared, and an inf would make every free task indistinguishable from
    # every other free task.
    s = (predicted_revenue / estimated_cost) if estimated_cost > 0 else predicted_revenue

    # Success-rate boost, read from the project's measured stats and only then from the
    # row. Same reason as the cost: at scheduling time the row has no history.
    project = str(task.get("project") or "")
    stats = (ctx.get("outcome_stats") or {}).get(project) or {}
    success_rate = _as_float(task.get("success_rate"), 0.0) or _as_float(
        stats.get("success_rate"), 0.7)
    s *= (1.0 + success_rate)

    s *= kind_outcome_weight(task, ctx)

    return max(0.0, s)


#: Floor for kind_outcome_weight. A family that has never merged is deprioritised, never
#: zeroed: a zero weight makes the task permanently unschedulable, so the family can never
#: produce the merge that would lift its own weight back up.
KIND_WEIGHT_FLOOR = float(os.environ.get("ORCH_ECONOMIC_KIND_WEIGHT_FLOOR", "0.2"))


def kind_outcome_weight(task, ctx):
    """How much this task's FAMILY has been worth historically, in [KIND_WEIGHT_FLOOR, 1.0].

    Reads ctx["family_outcomes"][kind] = {total, merged_green, retries, rejected}. The
    weight is the family's green-merge rate, penalised by retries and rejections, so a
    kind that burns ten attempts per merge ranks below one that lands first try.

    Neutral (1.0) when there is no history: an unmeasured family must not be punished for
    being new. Fail-soft — junk stats return 1.0 rather than raising inside the scorer.
    """
    kind = str((task or {}).get("kind") or "")
    stats = ((ctx or {}).get("family_outcomes") or {}).get(kind) or {}
    total = _as_float(stats.get("total"), 0.0)
    if total <= 0:
        return 1.0
    merged = max(0.0, _as_float(stats.get("merged_green"), 0.0))
    retries = max(0.0, _as_float(stats.get("retries"), 0.0))
    rejected = max(0.0, _as_float(stats.get("rejected"), 0.0))
    merge_rate = min(1.0, merged / total)
    # Attempts spent per unit of delivered work; 1.0 when everything landed first try.
    friction = total / (total + retries + rejected)
    return max(KIND_WEIGHT_FLOOR, min(1.0, merge_rate * friction))


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

    NO KILL-SWITCH HERE. This used to open with `if not ENABLED: return {"routed": 0}`,
    duplicating the gate run() already applies at line 508. The duplicate did nothing for
    safety — run() is the only production caller and it never reaches this line when the
    scheduler is off — while making the function impossible to exercise: every direct call,
    including the entire routing test class, silently returned "routed 0" because the
    scheduler defaults OFF. The switch belongs at the job boundary; this stays a pure
    function of its argument.
    """
    # Sort by score descending
    scored_copy = sorted(scored or [], key=lambda x: -x[0])[:TOP_REVENUE_TASKS]

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

    return {"routed": routed, "lane": "revenue-critical", "top_n": TOP_REVENUE_TASKS}


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
