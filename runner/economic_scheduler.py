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
#: Canonical name for the fast-lane size. The tests and the module had drifted onto two
#: names for one number; this is the one the contract uses. Kept as an alias rather than a
#: rename so nothing already reading REVENUE_CRITICAL_LANE_SIZE breaks.
TOP_REVENUE_TASKS = REVENUE_CRITICAL_LANE_SIZE

#: Half-width of the confidence band around a revenue point estimate.
#: Read once at import so every consumer — module and tests alike — agrees on one value
#: instead of each re-deriving it from the env with its own default (which is exactly how
#: the two test files came to disagree about 20% vs 25%).
CONFIDENCE_BAND = float(os.environ.get("ORCH_ECONOMIC_CONFIDENCE_BAND", "0.25"))

#: Floor on kind_outcome_weight(). The worst-performing family is de-prioritised, never
#: zeroed — a zero would make its work unschedulable, so it could never earn its record back.
MIN_KIND_WEIGHT = float(os.environ.get("ORCH_MIN_KIND_WEIGHT", "0.1"))

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
    # The two test files were previously read as contradicting each other (20% vs 25%). They
    # do not: the revenue suite derives its band from ORCH_ECONOMIC_CONFIDENCE_BAND, so it
    # tracks whatever the module uses. Only test_economic_scheduler.py pins a literal, and it
    # pins 25%. Both are green at 25%; the disagreement was two independent reads of the same
    # env var with different hardcoded defaults. There is now one module-level constant
    # (CONFIDENCE_BAND) and the tests read it, so the pair cannot drift apart again.
    band = CONFIDENCE_BAND
    if base_revenue == 0:
        low, high = 0.0, estimate
    else:
        low = estimate * (1.0 - band)
        high = estimate * (1.0 + band)

    return _estimate(estimate, low, high)


def estimated_cost_of(task, ctx):
    """What this task is expected to cost in USD. Never raises, never negative.

    Resolution order, most specific first:
      1. the project's measured ``outcome_stats[project]["avg_usd"]`` — what work on this
         project has actually cost, which is the number a scheduler should reason with;
      2. the task's own ``usd`` field, for a queue row carrying its own estimate;
      3. 0.0 — genuinely free work, which is a real answer, not a division hazard.

    Cost was previously read only from ``task["usd"]``, so a context carrying real
    per-project spend was ignored and every task without a usd field was silently assigned
    a cost of 1.0. That fabricated denominator flowed into both roi and score, which is why
    score() could not tell an expensive task from a cheap one.

    ``_as_float``, not ``float()``: ``usd`` arrives from the tasks table and has been seen
    as a string, and this module's stated contract is that every read is fail-soft.
    """
    try:
        project = (task or {}).get("project")
        stats = (ctx or {}).get("outcome_stats") or {}
        entry = stats.get(project) or {}
        if "avg_usd" in entry:
            cost = _as_float(entry.get("avg_usd"), -1.0)
            if cost >= 0:
                return cost
    except Exception:
        pass
    try:
        cost = _as_float((task or {}).get("usd"), 0.0)
        return cost if cost >= 0 else 0.0
    except Exception:
        return 0.0


def kind_outcome_weight(task, ctx):
    """How much this task's kind-family deserves to be trusted, in (0, 1].

    A family that keeps getting rejected or retried without merging green is worth less
    per unit of predicted revenue than one that lands. score() documented this multiplier
    and then hardcoded it to 1.0, so the whole family signal was inert.

    Floored at MIN_KIND_WEIGHT so the worst family is de-prioritised, never zeroed out —
    a zero would make the work unschedulable and it could then never recover its record.
    """
    try:
        kind = (task or {}).get("kind")
        fam = ((ctx or {}).get("family_outcomes") or {}).get(kind) or {}
        total = _as_float(fam.get("total"), 0.0)
        if total <= 0:
            return 1.0
        merged = max(0.0, _as_float(fam.get("merged_green"), 0.0))
        retries = max(0.0, _as_float(fam.get("retries"), 0.0))
        rejected = max(0.0, _as_float(fam.get("rejected"), 0.0))
        # Merge rate, discounted by the churn the family generates per attempt.
        merge_rate = min(1.0, merged / total)
        churn = (retries + rejected) / total
        weight = merge_rate / (1.0 + churn)
        return max(MIN_KIND_WEIGHT, min(1.0, weight))
    except Exception:
        return 1.0


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
    estimated_cost = estimated_cost_of(task, ctx)

    # Free work is reported honestly rather than clamped to a cost of 1.0. Clamping
    # collapsed two different situations onto the same middling number: zero cost with
    # revenue (infinite ROI, obviously worth doing) and zero cost with no revenue
    # (zero ROI, not worth doing) both came out as revenue/1.0.
    if estimated_cost > 0:
        roi = round(predicted_revenue / estimated_cost, 2)
        worthwhile = predicted_revenue > (ROI_THRESHOLD * estimated_cost)
    elif predicted_revenue > 0:
        roi, worthwhile = float("inf"), True
    else:
        roi, worthwhile = 0.0, False

    return {
        "predicted_revenue": round(predicted_revenue, 2),
        "estimated_cost": round(estimated_cost, 2),
        "roi": roi,
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
    # Same cost resolution as cost_benefit, so a task cannot be worthwhile by one measure
    # and cheap by the other. Reading only task["usd"] here meant a context carrying real
    # per-project spend was ignored, and score() could not tell dear work from cheap work.
    estimated_cost = estimated_cost_of(task, ctx)

    # Base score: ROI. Free work is not infinitely schedulable — a score of inf would pin
    # it at the head of the queue forever — so zero cost scores as the raw revenue.
    s = (predicted_revenue / estimated_cost) if estimated_cost > 0 else predicted_revenue

    # Success rate boost (assume 0.7 baseline if not specified)
    success_rate = _as_float(task.get("success_rate"), 0.7)
    s *= (1.0 + success_rate)

    # Kind outcome weight: a family that churns without merging is worth less per unit of
    # predicted revenue. This was documented and then hardcoded to 1.0, so the family
    # signal did nothing at all.
    s *= kind_outcome_weight(task, ctx)

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

    The ENABLED gate lives in run(), not here. It used to sit at the top of this function,
    which meant the module's only writing function silently returned {"routed": 0} for any
    caller under the default (off) configuration — including every test, which is why the
    routing contract went unverified. The kill switch belongs on the scheduled job, so a
    deliberate direct call still does what it says.
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

    return {"routed": routed, "lane": "revenue-critical", "top_n": REVENUE_CRITICAL_LANE_SIZE}


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
