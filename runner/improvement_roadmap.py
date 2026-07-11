#!/usr/bin/env python3
"""
improvement_roadmap.py - Staged, disclosed-assumption model of how far the levers already
built in this codebase (reuse velocity, zero-token/compiled-intent share, token distillation,
quality-aware model routing) could close the gap against DeepSeek's quality-adjusted portfolio
cost — and how far a 50x-500x improvement claim actually reaches.

THIS IS A ROADMAP MODEL, NOT A MEASURED RESULT. Every stage states its assumptions explicitly.
None of the stage numbers are claims about what has already happened; they are "if reuse
velocity reaches N and zero-token share reaches M, the blended cost per unit would be X" —
computed with the exact same formulas cost_intelligence.py uses for real data, just applied
prospectively. Do not present any stage beyond Stage 0 as a current or historical figure.

Baseline gap (see cost_intelligence.competitor_comparison): as of the last computed baseline,
our blended cost per unit of delivered value is roughly two-to-three orders of magnitude above
DeepSeek's quality-adjusted portfolio-equivalent cost. A "50x-500x improvement" claim therefore
spans everything from "a meaningful, plausible dent" (50x) to "roughly full parity with
DeepSeek's quality-adjusted cost, at current DeepSeek pricing" (500x) — these are very
different claims and this module keeps them separately labeled rather than picking one.

Levers modeled (each grounded in a real, already-built mechanism in this codebase):
  1. reuse_multiple      - cross-project capability reuse (capability_instances / self_improvement_signal).
                            Growth driver: as the capability library matures and more projects
                            come online, avg_reuse_per_published_capability rises.
  2. zero_token_share     - share of merges served by outcomes.coder in ('zero-token',
                            'compiled-intent') instead of a fresh model call
                            (cade_tournaments.zero_token_patch, intent_compiler). Growth driver:
                            proof_propagation and intent_compiler convert more mature patterns
                            to zero-cost replay over time.
  3. fresh_cost_reduction - reduction in $/fresh-merge via context_embed.distill() (smaller,
                            more relevant context -> fewer input tokens) and quality-aware model
                            routing (cade_tournaments routing lower-complexity tasks to cheaper
                            models instead of defaulting to the most expensive one).

Run: python3 improvement_roadmap.py [--out-dir reports]
"""
import os, sys, json, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cost_intelligence as ci

# Disclosed, named stages. Each is an assumption set, not a forecast with a claimed probability.
STAGES = [
    {
        "name": "Stage 0 - baseline (measured or last-computed)",
        "reuse_multiplier_of_baseline": 1.0,
        "zero_token_share_target": None,   # None = use whatever the baseline actually has
        "fresh_cost_reduction_pct": 0.0,
        "note": "No projected change applied. This is the input, not a target.",
    },
    {
        "name": "Stage 1 - near-term (levers already merged, not yet at scale)",
        "reuse_multiplier_of_baseline": 2.0,
        "zero_token_share_target": 0.45,
        "fresh_cost_reduction_pct": 0.15,
        "note": ("Assumes: capability reuse velocity roughly doubles as more of the existing "
                "5-project portfolio picks up already-published capabilities (no new mechanism "
                "required, just wider adoption of proof_propagation/cross_project_templates); "
                "zero-token+compiled-intent share of merges rises to 45% as intent_compiler "
                "matures more intents past its promotion threshold; fresh-merge cost falls 15% "
                "from context_cache_distill.py trimming input tokens (already-measured: 879->765 "
                "cache entries, ~13% reduction, on the one repo distilled so far)."),
    },
    {
        "name": "Stage 2 - mid-term (portfolio scale + quality-aware routing)",
        "reuse_multiplier_of_baseline": 5.0,
        "zero_token_share_target": 0.65,
        "fresh_cost_reduction_pct": 0.35,
        "note": ("Assumes: reuse velocity grows 5x baseline as the fleet scales to more projects "
                "(each new project is a new instantiation surface for existing capabilities, so "
                "reuse should scale faster than linear with project count, but this is a "
                "projection, not observed); zero-token+compiled-intent share reaches 65% as the "
                "compiled-intent library covers most repeat problem shapes; fresh-merge cost "
                "falls 35% combining deeper context distillation with cade_tournaments routing "
                "lower-complexity tasks to Sonnet/Haiku-tier instead of defaulting to Opus."),
    },
    {
        "name": "Stage 3 - aggressive/aspirational (upper bound of the 50-500x claim)",
        "reuse_multiplier_of_baseline": 15.0,
        "zero_token_share_target": 0.85,
        "fresh_cost_reduction_pct": 0.55,
        "note": ("Assumes: reuse velocity reaches 15x baseline (requires materially more projects "
                "on the fleet than exist today, and mature enough capabilities that near-zero "
                "customization is needed — NOT demonstrated at current scale); zero-token share "
                "reaches 85% (would require most of the queue to be repeat problem shapes, which "
                "is a property of the eventual steady-state workload mix, not something we "
                "control); fresh-merge cost falls 55% via aggressive distillation + routing "
                "nearly all non-escalation work to the cheapest model that clears the quality "
                "bar. This stage is explicitly the upper bound of plausibility, not a committed "
                "target or timeline."),
    },
]


def _project_stage(baseline, stage):
    """Apply one stage's assumptions to a baseline cost_intelligence.compute() payload and
    return the projected blended_cost_per_unit_of_delivered_value plus the gap multiple vs
    DeepSeek's quality-adjusted portfolio-equivalent cost. Uses the SAME arithmetic shape as
    cost_intelligence.py: total_usd / total_units. Only the two levers described in the module
    docstring are varied; everything else (baseline direct-cost structure, DeepSeek pricing,
    quality index) is held fixed at the baseline/sourced values."""
    d, i, c = baseline["direct"], baseline["indirect"], baseline["competitor_deepseek"]

    total_usd = (d.get("usd_per_merge") or 0.0) * (d.get("n_merged") or 0)
    baseline_reuse_events = i.get("additive_value_events", 0)
    baseline_n_merged = d.get("n_merged", 0)
    baseline_zero_token_share = (
        (i.get("cost_avoidance_events", 0) / baseline_n_merged) if baseline_n_merged else 0.0
    )

    reuse_mult = stage["reuse_multiplier_of_baseline"]
    projected_reuse_events = round(baseline_reuse_events * reuse_mult) if reuse_mult else baseline_reuse_events

    zt_target = stage["zero_token_share_target"]
    zero_token_share = zt_target if zt_target is not None else baseline_zero_token_share
    # Fresh-merge cost scales with (1 - zero_token_share) of merged work needing a real model call.
    fresh_reduction = stage["fresh_cost_reduction_pct"]
    avg_fresh_usd = (d.get("avg_fresh_merge_usd") or 0.0) * (1.0 - fresh_reduction)
    fresh_share = max(0.0, 1.0 - zero_token_share)
    projected_direct_usd = avg_fresh_usd * fresh_share * baseline_n_merged

    projected_total_usd = round(projected_direct_usd, 2)
    projected_total_units = baseline_n_merged + projected_reuse_events
    projected_blended = (round(projected_total_usd / projected_total_units, 4)
                         if projected_total_units else None)

    # Gap vs DeepSeek quality-adjusted portfolio-equivalent cost per unit (held fixed at the
    # sourced DeepSeek price + quality index — we are not projecting DeepSeek's price to fall).
    deepseek_unit_cost = None
    dq = c.get("deepseek_usd_per_solve_quality_adjusted") or c.get("raw_deepseek_usd_per_solve")
    if dq:
        deepseek_unit_cost = dq

    gap_multiple = None
    if projected_blended and deepseek_unit_cost:
        gap_multiple = round(projected_blended / deepseek_unit_cost, 1)

    return {
        "stage": stage["name"],
        "assumptions": stage["note"],
        "projected_total_usd": projected_total_usd,
        "projected_total_units_of_value": projected_total_units,
        "projected_blended_cost_per_unit": projected_blended,
        "deepseek_quality_adjusted_unit_cost_held_fixed": deepseek_unit_cost,
        "gap_multiple_vs_deepseek": gap_multiple,
        "reaches_50x_improvement": (
            None if gap_multiple is None or "baseline_gap_multiple" not in stage
            else stage["baseline_gap_multiple"] / gap_multiple >= 50
        ),
    }


def build_roadmap(baseline=None, window_days=30):
    """baseline: a cost_intelligence.compute()-shaped payload. If None, attempts a live
    compute() (requires Supabase reachability); falls back to a clearly-labeled illustrative
    baseline if that fails, so this module never silently produces numbers from nothing."""
    used_live_data = False
    if baseline is None:
        try:
            baseline = ci.compute(window_days=window_days)
            used_live_data = bool(baseline.get("direct", {}).get("attempts"))
        except Exception:
            baseline = None

    if not baseline or not baseline.get("direct", {}).get("attempts"):
        # No live data reachable — do not fabricate a baseline pretending to be measured.
        return {
            "used_live_data": False,
            "error": ("No live outcomes data available to build a baseline (Supabase "
                     "unreachable or empty outcomes table in window). Run this on a machine "
                     "with Supabase access, or pass an explicit baseline payload."),
            "stages": [],
        }

    baseline_blended = baseline.get("blended_cost_per_unit_of_delivered_value")
    c = baseline.get("competitor_deepseek", {})
    deepseek_unit_cost = (c.get("deepseek_usd_per_solve_quality_adjusted")
                          or c.get("raw_deepseek_usd_per_solve"))
    baseline_gap_multiple = (round(baseline_blended / deepseek_unit_cost, 1)
                             if baseline_blended and deepseek_unit_cost else None)

    stages_out = []
    for stage in STAGES:
        s = dict(stage)
        if baseline_gap_multiple is not None:
            s["baseline_gap_multiple"] = baseline_gap_multiple
        if stage["name"].startswith("Stage 0"):
            stages_out.append({
                "stage": stage["name"],
                "assumptions": stage["note"],
                "projected_total_usd": round(sum(
                    float(0) for _ in []), 2),  # baseline uses measured totals, not projected
                "projected_total_units_of_value": (baseline["direct"].get("n_merged", 0)
                                                   + baseline["indirect"].get("additive_value_events", 0)),
                "projected_blended_cost_per_unit": baseline_blended,
                "deepseek_quality_adjusted_unit_cost_held_fixed": deepseek_unit_cost,
                "gap_multiple_vs_deepseek": baseline_gap_multiple,
                "reaches_50x_improvement": False,
            })
        else:
            stages_out.append(_project_stage(baseline, s))

    return {
        "used_live_data": used_live_data,
        "baseline_gap_multiple": baseline_gap_multiple,
        "stages": stages_out,
        "verdict": _verdict(baseline_gap_multiple, stages_out),
    }


def _verdict(baseline_gap_multiple, stages_out):
    if baseline_gap_multiple is None:
        return "Insufficient data to state a verdict."
    best_stage = stages_out[-1]
    final_gap = best_stage.get("gap_multiple_vs_deepseek")
    if final_gap is None:
        return "Insufficient data to state a verdict."
    improvement_factor = round(baseline_gap_multiple / final_gap, 1) if final_gap else None
    reaches_50 = improvement_factor is not None and improvement_factor >= 50
    reaches_500 = improvement_factor is not None and improvement_factor >= 500
    reaches_parity = final_gap <= 1.0
    if reaches_parity:
        return (f"Under Stage 3's aggressive/aspirational assumptions, projected improvement is "
               f"{improvement_factor}x over baseline, which would reach or exceed cost parity "
               f"with DeepSeek's quality-adjusted portfolio-equivalent cost. This is the upper "
               f"bound of plausibility, not a committed target — see Stage 3 assumptions.")
    return (f"Under Stage 3's aggressive/aspirational assumptions, projected improvement is "
           f"{improvement_factor}x over baseline "
           f"({'reaches' if reaches_50 else 'does not reach'} the 50x threshold, "
           f"{'reaches' if reaches_500 else 'does not reach'} the 500x threshold). Even at this "
           f"upper bound we remain {final_gap}x DeepSeek's quality-adjusted portfolio-equivalent "
           f"cost per unit — closing the remainder requires either DeepSeek's price rising, our "
           f"quality edge widening beyond the sourced benchmark gap, or reuse/zero-token levers "
           f"exceeding what is modeled here as aggressive.")


def _write_report(roadmap, out_dir):
    lines = ["# Improvement Roadmap - 50x-500x claim, disclosed assumptions (internal)", ""]
    if not roadmap.get("stages"):
        lines.append(f"**No roadmap computed:** {roadmap.get('error')}")
    else:
        lines.append(f"Live data used for baseline: {roadmap['used_live_data']}")
        lines.append(f"Baseline gap vs DeepSeek (quality-adjusted, per unit of value): "
                    f"{roadmap['baseline_gap_multiple']}x")
        lines.append("")
        for s in roadmap["stages"]:
            lines += [
                f"## {s['stage']}",
                f"- Projected blended cost/unit: ${s['projected_blended_cost_per_unit']}",
                f"- Gap vs DeepSeek (quality-adjusted): {s['gap_multiple_vs_deepseek']}x",
                f"- _{s['assumptions']}_",
                "",
            ]
        lines.append(f"## Verdict\n{roadmap['verdict']}")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "improvement_roadmap_internal.md")
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    return path


def run(window_days=30, out_dir=None):
    out_dir = out_dir or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "reports")
    roadmap = build_roadmap(window_days=window_days)
    path = _write_report(roadmap, out_dir)
    print(f"improvement_roadmap: wrote {path}")
    return roadmap


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--window-days", type=int, default=30)
    parser.add_argument("--out-dir", default=None)
    args = parser.parse_args()
    print(json.dumps(run(window_days=args.window_days, out_dir=args.out_dir), indent=2, default=str))
