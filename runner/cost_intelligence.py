#!/usr/bin/env python3
"""
cost_intelligence.py - "Where every dollar goes." Internal-IP cost/value analytics.

This is deliberately separate from scoreboard.py (which is an operational heartbeat, meant
to run every 10 min and be cheap). cost_intelligence.py is a periodic/on-demand REPORT
generator: it computes normalized cost-efficiency metrics plus a defensible model of INDIRECT
value from cross-project reuse, and a competitor cost comparison. It writes two files:

  reports/cost_intelligence_internal.md  - full methodology + numbers. PRIVATE. This is the
                                            proprietary part: exactly how we count indirect
                                            value. Do not share externally.
  reports/cost_intelligence_external.md  - conclusions only, no formulas, no raw internal
                                            counts. Safe to share with investors/customers.

Methodology (see the internal report for the full write-up):

  1. DIRECT cost efficiency — usd_per_merge, tokens_per_merge, first-pass rate. Reported as
     RATIOS, not cumulative totals — a cumulative dollar figure understates a young fleet and
     invites the wrong comparison ("how big are you") instead of the right one ("how
     efficient are you per unit of merged work").

  2. INDIRECT savings from cross-project reuse — this is the actual differentiator and the
     part a single-model API vendor structurally cannot offer, because it requires an
     orchestration layer with memory across projects:
       - capability_instances: a capability (pattern/component) published once and
         instantiated in another project. Each row is one avoided full rebuild.
       - outcomes.coder == 'zero-token': a diff replayed from a prior proof with NO model
         call at all (cade_tournaments.zero_token_patch).
       - outcomes.coder == 'compiled-intent': a deterministic compiled script executed with
         NO model call (intent_compiler).
     Each of these events is valued at the AVERAGE cost of a comparable fresh (non-reuse)
     merge in the same project/window — the real counterfactual: what it would have cost to
     solve the same problem from scratch. This is conservative — it does NOT count
     proof_propagation/cross_project_templates candidate matches that were generated but not
     yet merged, only landed reuse.

  3. COMPETITOR comparison — DeepSeek API list pricing (deepseek-v4-flash, cache-miss:
     $0.14/1M input, $0.28/1M output; source: api-docs.deepseek.com/quick_start/pricing,
     fetched 2026-07) applied to OUR OWN measured tokens-per-merge. This answers "what would
     the tokens we actually spent have cost on raw DeepSeek API pricing with zero
     orchestration" — it is deliberately NOT a claim that DeepSeek would produce the same
     merge rate; a raw API with no build-gate/verify/merge-train pipeline would need more
     retries per merge, which the internal report flags explicitly as an unmodeled assumption
     in our favor. Keep DEEPSEEK_PRICE_* below current with the vendor's pricing page.

  4. SELF-IMPROVEMENT LOOP differentiator — capability publish rate, reuse velocity
     (instances per capability), and the merge-rate trend are used as evidence that
     marginal cost per unit of delivered value falls over time, structurally, not as a
     one-time optimization. This is the point a static per-token API relationship cannot
     make.

Run: python3 cost_intelligence.py [--window-days 30] [--out-dir reports]
"""
import os, sys, json, datetime, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

# DeepSeek V4-Flash list pricing, per 1M tokens, cache-miss (the conservative/no-caching case).
# Source: https://api-docs.deepseek.com/quick_start/pricing — verify before quoting externally,
# vendor pricing pages change without notice.
DEEPSEEK_PRICE_INPUT_PER_M = float(os.environ.get("ORCH_DEEPSEEK_INPUT_PER_M", "0.14"))
DEEPSEEK_PRICE_OUTPUT_PER_M = float(os.environ.get("ORCH_DEEPSEEK_OUTPUT_PER_M", "0.28"))
# DeepSeek V4-Pro-Max — the fairer "same capability class" comparison target (V4-Flash is
# DeepSeek's small/cheap tier; comparing our frontier models against it is not apples-to-apples).
DEEPSEEK_PROMAX_PRICE_INPUT_PER_M = float(os.environ.get("ORCH_DEEPSEEK_PROMAX_INPUT_PER_M", "0.435"))
DEEPSEEK_PROMAX_PRICE_OUTPUT_PER_M = float(os.environ.get("ORCH_DEEPSEEK_PROMAX_OUTPUT_PER_M", "0.87"))

# MODEL QUALITY INDEX — sourced, dated benchmark scores + list prices. Used to embed
# "intelligence/capability" as a cost factor instead of comparing raw token price alone.
#
# swe_bench_verified: llm-stats vendor-reported aggregate, 500-task human-validated Python
#   subset. Widely quoted but OpenAI deprecated it Feb 2026 over contamination concerns
#   (public Python repos predate every model's training cutoff) — treat as a saturation
#   indicator among frontier models, not a precise ranking.
# swe_bench_pro_vendor: llm-stats vendor-reported aggregate on Scale AI's 1,865-task,
#   41-repo, multi-language, Pass@1 benchmark — harder and much more contamination-resistant,
#   but vendor-reported numbers use each lab's own tuned scaffold (10-30 points above Scale's
#   standardized harness). CAVEAT: Datacurve's May 2026 audit flagged Claude Opus 4.6/4.7
#   (not 4.8) as "CHEATED" on >12% of reviewed Pro tasks via reading .git history for the
#   gold patch (Scale GitHub issue #93, unconfirmed by Scale). Use Verified as the primary,
#   more-audited signal; treat Pro numbers as directional.
# Source: https://www.morphllm.com/swe-bench-pro (llm-stats aggregate, checked 2026-06-28);
#         https://api-docs.deepseek.com/quick_start/pricing (DeepSeek pricing, checked 2026-07).
MODEL_QUALITY_INDEX = {
    "claude-opus-4-8": {
        "swe_bench_verified": 88.6, "swe_bench_pro_vendor": 69.2,
        "price_input_per_m": 5.0, "price_output_per_m": 25.0,
    },
    "claude-sonnet-4-6": {
        "swe_bench_verified": 79.6, "swe_bench_pro_vendor": None,  # no directly-sourced Pro number
        "price_input_per_m": 3.0, "price_output_per_m": 15.0,
    },
    "deepseek-v4-pro-max": {
        "swe_bench_verified": 80.6, "swe_bench_pro_vendor": 55.4,
        "price_input_per_m": DEEPSEEK_PROMAX_PRICE_INPUT_PER_M,
        "price_output_per_m": DEEPSEEK_PROMAX_PRICE_OUTPUT_PER_M,
    },
}

REUSE_CODERS = ("zero-token", "compiled-intent")


def _iso_days_ago(days):
    return (datetime.datetime.utcnow() - datetime.timedelta(days=days)).isoformat()


def _select_outcomes(window_days):
    params = {
        "select": "project,model,coder,tests_passed,integrated,usd,wall_ms,input_tokens,output_tokens,created_at",
        "created_at": f"gte.{_iso_days_ago(window_days)}",
        "limit": "20000",
    }
    return db.select("outcomes", params) or []


def _select_capability_instances(window_days):
    try:
        return db.select("capability_instances", {
            "select": "capability_id,project,created_at",
            "created_at": f"gte.{_iso_days_ago(window_days)}",
            "limit": "5000",
        }) or []
    except Exception:
        return []


def _select_capabilities_published(window_days):
    try:
        return db.select("capabilities", {
            "select": "id,slug,source_project,created_at",
            "created_at": f"gte.{_iso_days_ago(window_days)}",
            "limit": "2000",
        }) or []
    except Exception:
        return []


def direct_efficiency(outcomes):
    """Normalized ratios only — no cumulative totals. See module docstring for why."""
    merged = [o for o in outcomes if o.get("integrated")]
    attempts = len(outcomes)
    n_merged = len(merged)
    fresh_merged = [o for o in merged if (o.get("coder") or "") not in REUSE_CODERS]

    def _avg(rows, field):
        vals = [float(r.get(field) or 0) for r in rows]
        return sum(vals) / len(vals) if vals else 0.0

    usd_total = sum(float(o.get("usd") or 0) for o in outcomes)
    tokens_total = sum(int(o.get("input_tokens") or 0) + int(o.get("output_tokens") or 0) for o in outcomes)

    return {
        "attempts": attempts,
        "merge_rate": round(n_merged / attempts, 4) if attempts else None,
        "first_pass_rate": round(sum(1 for o in outcomes if o.get("tests_passed")) / attempts, 4) if attempts else None,
        "usd_per_merge": round(usd_total / n_merged, 4) if n_merged else None,
        "tokens_per_merge": round(tokens_total / n_merged, 1) if n_merged else None,
        "avg_fresh_merge_usd": round(_avg(fresh_merged, "usd"), 4),
        "avg_fresh_merge_input_tokens": round(_avg(fresh_merged, "input_tokens"), 1),
        "avg_fresh_merge_output_tokens": round(_avg(fresh_merged, "output_tokens"), 1),
        "n_merged": n_merged,
        "n_fresh_merged": len(fresh_merged),
    }


def indirect_savings(outcomes, capability_instances, direct):
    """Value landed reuse events at the counterfactual (avg fresh-merge) cost.
    Deliberately conservative: only counts EVENTS THAT HAPPENED, not candidates generated.

    IMPORTANT: zero-token and compiled-intent events are rows IN `outcomes` — they are
    already counted inside direct['n_merged'] when integrated=True. They are a COST-AVOIDANCE
    signal (this merge happened cheaply instead of at full price), not ADDITIONAL units of
    delivered value. capability_instances is a separate table: each row is a DIFFERENT
    project getting a working component with no dedicated outcome row of its own, so those
    ARE additional value beyond n_merged. Keep these two categories separate everywhere
    downstream — conflating them double-counts and overstates value delivered."""
    avg_fresh_usd = direct.get("avg_fresh_merge_usd") or 0.0

    zero_token = sum(1 for o in outcomes if (o.get("coder") or "") == "zero-token")
    compiled_intent = sum(1 for o in outcomes if (o.get("coder") or "") == "compiled-intent")
    actual_reuse_usd = sum(float(o.get("usd") or 0) for o in outcomes
                           if (o.get("coder") or "") in REUSE_CODERS)
    n_capability_reuse = len(capability_instances)

    cost_avoidance_events = zero_token + compiled_intent   # inside n_merged already
    additive_value_events = n_capability_reuse             # outside n_merged, genuinely extra
    total_reuse_events = cost_avoidance_events + additive_value_events  # for reporting only

    gross_avoided_usd = total_reuse_events * avg_fresh_usd
    net_avoided_usd = max(0.0, gross_avoided_usd - actual_reuse_usd)

    return {
        "zero_token_events": zero_token,
        "compiled_intent_events": compiled_intent,
        "cost_avoidance_events": cost_avoidance_events,
        "capability_reuse_events": n_capability_reuse,
        "additive_value_events": additive_value_events,
        "total_reuse_events": total_reuse_events,
        "counterfactual_usd_per_event": round(avg_fresh_usd, 4),
        "actual_usd_spent_on_reuse_events": round(actual_reuse_usd, 4),
        "gross_avoided_usd": round(gross_avoided_usd, 2),
        "net_avoided_usd": round(net_avoided_usd, 2),
    }


def quality_adjustment(our_model="claude-sonnet-4-6", competitor_model="deepseek-v4-pro-max",
                       metric="swe_bench_verified"):
    """Embed model capability into the cost comparison instead of comparing raw token price
    alone. Uses MODEL_QUALITY_INDEX (sourced, dated benchmark scores).

    retry_multiplier: crude but standard heuristic — expected attempts to first success is
    roughly proportional to 1/success_rate, so a lower-scoring model needs
    (our_score / their_score) as many attempts/tokens to reach an equivalent successful
    outcome. retry_multiplier > 1 means the COMPETITOR needs more retries (favors us);
    < 1 means the competitor's benchmark score is actually HIGHER than ours (does not favor
    us — report it anyway, do not clip it to 1.0).

    points_per_dollar: score / output-token price — a standard "capability per dollar"
    efficiency metric, independent of our own measured spend.
    """
    us = MODEL_QUALITY_INDEX.get(our_model, {})
    them = MODEL_QUALITY_INDEX.get(competitor_model, {})
    us_score = us.get(metric)
    them_score = them.get(metric)
    retry_multiplier = None
    if us_score and them_score:
        retry_multiplier = round(us_score / them_score, 4)

    def _pts_per_dollar(entry):
        score = entry.get(metric)
        price = entry.get("price_output_per_m")
        if not score or not price:
            return None
        return round(score / price, 2)

    return {
        "our_model": our_model,
        "competitor_model": competitor_model,
        "metric": metric,
        "our_score": us_score,
        "competitor_score": them_score,
        "retry_multiplier": retry_multiplier,
        "our_points_per_dollar": _pts_per_dollar(us),
        "competitor_points_per_dollar": _pts_per_dollar(them),
        "note": ("retry_multiplier is a modeling heuristic (attempts-to-success ~ 1/benchmark_score), "
                "not a measured result — we do not run DeepSeek in this pipeline, so this cannot be "
                "verified empirically. points_per_dollar uses each vendor's list output-token price "
                "and is a standard, vendor-neutral efficiency metric."),
    }


def competitor_comparison(direct, indirect, total_usd_spent, quality=None):
    """Two HONEST comparisons against DeepSeek's list pricing — deliberately not spun to
    show a result the raw numbers don't support:

    1. raw_per_token: we do NOT claim to beat DeepSeek's per-token price. Frontier
       general-purpose models cost more per token than DeepSeek's commodity-tier pricing,
       full stop. This field exists so nobody downstream re-derives a false "we're cheaper
       per token" claim — the honest answer is in `raw_per_token_verdict`.
    2. portfolio_coverage: the comparison that actually matters for a multi-project fleet —
       what would it cost to reach the SAME reuse coverage (n_merged fresh solves +
       additive cross-project reuse instances) if every one of those had to be solved
       independently, with zero shared memory, even at DeepSeek's cheap per-token rate?
       That is the real counterfactual for "a customer just calls DeepSeek directly N times
       across N projects" vs. our reuse layer solving it ~once and replaying it.
    """
    in_tok = direct.get("avg_fresh_merge_input_tokens") or 0.0
    out_tok = direct.get("avg_fresh_merge_output_tokens") or 0.0
    raw_deepseek_usd_per_solve = (
        in_tok / 1_000_000 * DEEPSEEK_PRICE_INPUT_PER_M
        + out_tok / 1_000_000 * DEEPSEEK_PRICE_OUTPUT_PER_M
    )
    our_usd_per_solve = direct.get("avg_fresh_merge_usd") or 0.0
    raw_per_token_verdict = ("we cost more per raw token than DeepSeek — do not claim otherwise"
                             if our_usd_per_solve > raw_deepseek_usd_per_solve else
                             "our measured $/solve is at or below DeepSeek's list-price equivalent")

    # Quality-adjusted: fold in the sourced retry_multiplier (see quality_adjustment()) instead
    # of assuming DeepSeek needs the same tokens per solve as us. retry_multiplier > 1 means
    # DeepSeek's lower benchmark score requires more effective spend to match; < 1 means their
    # sourced score is actually AS GOOD OR BETTER than ours — reported honestly either way.
    retry_multiplier = (quality or {}).get("retry_multiplier")
    deepseek_usd_per_solve_quality_adjusted = (
        round(raw_deepseek_usd_per_solve * retry_multiplier, 4) if retry_multiplier else None
    )

    total_units_covered = direct.get("n_merged", 0) + indirect.get("additive_value_events", 0)
    deepseek_cost_if_solved_independently_every_time = round(
        raw_deepseek_usd_per_solve * total_units_covered, 2)
    deepseek_cost_quality_adjusted = (
        round(deepseek_usd_per_solve_quality_adjusted * total_units_covered, 2)
        if deepseek_usd_per_solve_quality_adjusted is not None else None
    )
    our_actual_cost = round(total_usd_spent, 2)
    compare_to = deepseek_cost_quality_adjusted if deepseek_cost_quality_adjusted is not None \
        else deepseek_cost_if_solved_independently_every_time
    portfolio_verdict = ("our reuse layer's total cost is LOWER than DeepSeek-with-no-reuse for "
                         "this coverage" if our_actual_cost < compare_to
                         else "DeepSeek-with-no-reuse is still lower total cost at this volume/reuse rate — "
                              "the reuse advantage has not yet overcome the per-token price gap, even after "
                              "the quality/retry adjustment")

    return {
        "deepseek_input_price_per_m": DEEPSEEK_PRICE_INPUT_PER_M,
        "deepseek_output_price_per_m": DEEPSEEK_PRICE_OUTPUT_PER_M,
        "raw_deepseek_usd_per_solve": round(raw_deepseek_usd_per_solve, 4),
        "deepseek_usd_per_solve_quality_adjusted": deepseek_usd_per_solve_quality_adjusted,
        "our_usd_per_solve": round(our_usd_per_solve, 4),
        "raw_per_token_verdict": raw_per_token_verdict,
        "total_units_covered": total_units_covered,
        "deepseek_cost_if_solved_independently_every_time": deepseek_cost_if_solved_independently_every_time,
        "deepseek_cost_quality_adjusted": deepseek_cost_quality_adjusted,
        "our_actual_cost_for_same_coverage": our_actual_cost,
        "portfolio_verdict": portfolio_verdict,
        "note": ("portfolio_coverage assumes DeepSeek needs the SAME tokens per solve as our "
                "pipeline (generous: no build-gate/verify/merge-train means more retries in "
                "practice) and credits DeepSeek $0 orchestration/reuse-infrastructure cost (also "
                "generous). Where quality_adjustment() is passed in, deepseek_usd_per_solve_quality"
                "_adjusted/deepseek_cost_quality_adjusted instead scale DeepSeek's cost by the "
                "sourced retry_multiplier (benchmark-score ratio) — less generous to DeepSeek where "
                "our model's sourced score is higher, but still a heuristic, not a measured result. "
                "Even so, this portfolio comparison is the only place our economics can beat a "
                "cheaper-per-token model — never claim per-token parity, see raw_per_token_verdict."),
    }


def self_improvement_signal(capabilities_published, capability_instances):
    by_cap = {}
    for inst in capability_instances:
        by_cap.setdefault(inst.get("capability_id"), 0)
        by_cap[inst.get("capability_id")] += 1
    reuse_velocity = (sum(by_cap.values()) / len(by_cap)) if by_cap else 0.0
    return {
        "capabilities_published_in_window": len(capabilities_published),
        "capability_instances_in_window": len(capability_instances),
        "avg_reuse_per_published_capability": round(reuse_velocity, 2),
        "note": ("avg_reuse_per_published_capability > 1 means the average pattern this fleet "
                "learns gets applied to more than one project beyond where it was first solved — "
                "the compounding effect a single-project or single-model API relationship "
                "structurally cannot produce."),
    }


def compute(window_days=30):
    outcomes = _select_outcomes(window_days)
    capability_instances = _select_capability_instances(window_days)
    capabilities_published = _select_capabilities_published(window_days)

    total_usd = sum(float(o.get("usd") or 0) for o in outcomes)

    direct = direct_efficiency(outcomes)
    indirect = indirect_savings(outcomes, capability_instances, direct)

    # Two quality lenses, because "intelligence-adjusted cost" tells a different story at each
    # tier: Sonnet is our primary-volume model (most spend) and sits near parity with DeepSeek
    # V4-Pro-Max on the more-audited Verified benchmark; Opus is our escalation/hard-task tier
    # and scores meaningfully higher, but DeepSeek still wins decisively on points-per-dollar.
    # Report both rather than picking whichever one looks better.
    quality_sonnet = quality_adjustment(our_model="claude-sonnet-4-6",
                                        competitor_model="deepseek-v4-pro-max")
    quality_opus = quality_adjustment(our_model="claude-opus-4-8",
                                      competitor_model="deepseek-v4-pro-max")
    # Use the primary-volume (Sonnet) tier for the headline portfolio comparison since that's
    # where most measured spend/tokens actually happened; Opus is reported alongside for the
    # escalation-tier story, not blended into the same number.
    competitor = competitor_comparison(direct, indirect, total_usd, quality=quality_sonnet)
    self_improve = self_improvement_signal(capabilities_published, capability_instances)

    # units of delivered value = merged changes (n_merged) + ADDITIVE cross-project reuse
    # instances only. zero-token/compiled-intent merges are already inside n_merged — adding
    # them again would double-count the same shipped change as two units of value.
    blended_cost_per_unit_value = None
    total_units_of_value = direct["n_merged"] + indirect["additive_value_events"]
    if total_units_of_value:
        blended_cost_per_unit_value = round(total_usd / total_units_of_value, 4)

    return {
        "generated_at": datetime.datetime.utcnow().isoformat(),
        "window_days": window_days,
        "direct": direct,
        "indirect": indirect,
        "competitor_deepseek": competitor,
        "quality_adjustment_sonnet": quality_sonnet,
        "quality_adjustment_opus": quality_opus,
        "self_improvement": self_improve,
        "blended_cost_per_unit_of_delivered_value": blended_cost_per_unit_value,
    }


def _write_internal_report(payload, out_dir):
    d, i, c, s = payload["direct"], payload["indirect"], payload["competitor_deepseek"], payload["self_improvement"]
    qs, qo = payload.get("quality_adjustment_sonnet"), payload.get("quality_adjustment_opus")
    lines = [
        "# Cost Intelligence — Internal (full methodology, private/IP)",
        f"_Generated {payload['generated_at']} — {payload['window_days']}-day window_",
        "",
        "## Direct cost efficiency (ratios, not cumulative totals)",
        f"- Merge rate: {d['merge_rate']}",
        f"- First-pass rate: {d['first_pass_rate']}",
        f"- $/merge (all): {d['usd_per_merge']}",
        f"- $/merge (fresh, non-reuse only — the real per-unit cost baseline): {d['avg_fresh_merge_usd']}",
        f"- Tokens/merge: {d['tokens_per_merge']}",
        "",
        "## Indirect savings from cross-project reuse",
        f"- Zero-token replay events (already inside n_merged, cost-avoidance only): {i['zero_token_events']}",
        f"- Compiled-intent deterministic events (already inside n_merged, cost-avoidance only): {i['compiled_intent_events']}",
        f"- Cross-project capability reuse events (ADDITIVE — separate from n_merged): {i['capability_reuse_events']}",
        f"- Counterfactual cost per event (avg fresh merge): ${i['counterfactual_usd_per_event']}",
        f"- Gross avoided spend: ${i['gross_avoided_usd']}",
        f"- Net avoided spend (after actual $ spent on reuse events): ${i['net_avoided_usd']}",
        "",
        "## Competitor comparison — DeepSeek API (list pricing)",
        f"- DeepSeek V4-Flash: ${c['deepseek_input_price_per_m']}/1M in, ${c['deepseek_output_price_per_m']}/1M out",
        f"- DeepSeek raw $/solve (our token footprint, their price): ${c['raw_deepseek_usd_per_solve']}",
        f"- Our $/solve (fresh, non-reuse): ${c['our_usd_per_solve']}",
        f"- **Per-token verdict: {c['raw_per_token_verdict']}**",
        f"- Portfolio coverage ({c['total_units_covered']} units — n_merged + additive reuse): "
        f"DeepSeek-with-no-reuse would cost ${c['deepseek_cost_if_solved_independently_every_time']} "
        f"raw, ${c['deepseek_cost_quality_adjusted']} quality-adjusted; our actual cost was "
        f"${c['our_actual_cost_for_same_coverage']}",
        f"- **Portfolio verdict: {c['portfolio_verdict']}**",
        f"- _{c['note']}_",
        "",
        "## Quality/intelligence-adjusted comparison (embedding capability, not just $/token)",
        "Honest finding: our primary-volume model (Sonnet) is near PARITY with DeepSeek V4-Pro-Max "
        "on the more-audited benchmark — quality adjustment does NOT clearly favor us at the tier "
        "where most spend actually happens. It favors us more clearly only at the Opus escalation "
        "tier, and even there DeepSeek's points-per-dollar is dramatically better.",
        "",
        f"**Primary-volume tier — {qs['our_model']} vs {qs['competitor_model']} ({qs['metric']}):**",
        f"- Our score: {qs['our_score']} | Their score: {qs['competitor_score']} "
        f"(near parity — do not oversell this tier's quality edge)",
        f"- Retry multiplier (heuristic): {qs['retry_multiplier']}",
        f"- Points/$ (output price) — us: {qs['our_points_per_dollar']}, them: {qs['competitor_points_per_dollar']}",
        "",
        f"**Escalation tier — {qo['our_model']} vs {qo['competitor_model']} ({qo['metric']}):**",
        f"- Our score: {qo['our_score']} | Their score: {qo['competitor_score']} "
        "(clearer quality edge here)",
        f"- Retry multiplier (heuristic): {qo['retry_multiplier']}",
        f"- Points/$ (output price) — us: {qo['our_points_per_dollar']}, them: {qo['competitor_points_per_dollar']} "
        "(DeepSeek's points-per-dollar is roughly an order of magnitude higher than Opus's even "
        "though Opus scores higher in absolute terms — quality adjustment narrows the price gap, "
        "it does not close it)",
        f"- _{qo['note']}_",
        "",
        "## Self-improvement loop differentiator",
        f"- Capabilities published this window: {s['capabilities_published_in_window']}",
        f"- Instantiations (reuse events): {s['capability_instances_in_window']}",
        f"- Avg reuse per published capability: {s['avg_reuse_per_published_capability']}",
        f"- _{s['note']}_",
        "",
        f"## Blended cost per unit of delivered value: ${payload['blended_cost_per_unit_of_delivered_value']}",
        "(total $ / (merges + reuse events) — the single number that captures both direct spend",
        "efficiency and the compounding reuse effect. This is the number to track quarter over quarter.)",
        "",
        "---",
        "**Do not share this file externally** — the formulas above (especially the reuse-event",
        "valuation methodology) are the proprietary part. Share cost_intelligence_external.md instead.",
    ]
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "cost_intelligence_internal.md")
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    return path


def _write_external_report(payload, out_dir):
    d, i, c = payload["direct"], payload["indirect"], payload["competitor_deepseek"]
    reuse_multiple = None
    if d.get("n_merged"):
        reuse_multiple = round(1 + (i["additive_value_events"] / d["n_merged"]), 2)
    portfolio_favorable = c.get("our_actual_cost_for_same_coverage", 1) < \
        c.get("deepseek_cost_if_solved_independently_every_time", 0)

    lines = [
        "# Cost Intelligence — Summary",
        f"_{payload['window_days']}-day rolling window_",
        "",
        "We measure cost per unit of delivered engineering work, not just tokens billed.",
        "",
        "**Efficiency.** Our per-merge cost reflects an orchestration layer purpose-built to "
        "avoid re-solving problems: work proven in one project is verified and reused across "
        "every other project we operate, not re-derived from scratch each time.",
        "",
        (f"**Reuse multiple.** For every {reuse_multiple}x unit of delivered engineering value, "
         "1 unit of fresh model spend was required — the remainder came from verified, reused, "
         "cross-project work." if reuse_multiple else
         "Cross-project reuse is tracked continuously; see the internal report for current figures."),
        "",
        ("**On raw model pricing:** we do not compete on per-token price against commodity-tier "
         "model providers, and don't claim to. **On total cost to cover a multi-project "
         "portfolio:** " +
         ("our reuse-adjusted total cost came in below what an unorchestrated, no-shared-memory "
          "approach would cost even at a cheaper provider's list price, for the same coverage."
          if portfolio_favorable else
          "we are tracking this comparison but have not yet crossed over the raw price gap at "
          "current volume — see the internal report for the live number.")),
        "",
        "**On model quality, not just price.** We weigh published capability benchmarks alongside "
        "price rather than comparing sticker price alone — an approach that requires more model "
        "choices than a single-vendor relationship offers. We report this comparison honestly: it "
        "narrows the gap versus lower-priced providers, and at our escalation tier it favors us "
        "outright, but it does not by itself make a low-cost commodity provider look expensive per "
        "raw token. Full scoring methodology available under NDA.",
        "",
        "**Compounding improvement.** Every merged change is evaluated for reuse potential "
        "across our full portfolio. This is a structural advantage a single-model API "
        "relationship cannot replicate: our marginal cost per unit of delivered value falls "
        "over time as the reuse library grows, rather than staying flat with token price.",
        "",
        "**Improvements ship without downtime.** New efficiency gains are published as data "
        "our pipeline reads on the next unit of work, not as a code deploy or a maintenance "
        "window — in-flight work is never paused, restarted, or degraded while the system "
        "improves itself in the background.",
        "",
        "_Methodology available under NDA._",
    ]
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "cost_intelligence_external.md")
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    return path


def run(window_days=30, out_dir=None):
    out_dir = out_dir or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "reports")
    payload = compute(window_days=window_days)
    internal_path = _write_internal_report(payload, out_dir)
    external_path = _write_external_report(payload, out_dir)
    try:
        db.insert("controls", {"key": "cost_intelligence", "value": json.dumps(payload, default=str),
                               "updated_at": "now()"}, upsert=True)
    except Exception:
        pass
    print(f"cost_intelligence: wrote {internal_path} and {external_path}")
    return payload


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--window-days", type=int, default=30)
    parser.add_argument("--out-dir", default=None)
    args = parser.parse_args()
    print(json.dumps(run(window_days=args.window_days, out_dir=args.out_dir), indent=2, default=str))
