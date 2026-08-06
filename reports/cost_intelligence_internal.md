# Cost Intelligence — Internal (full methodology, private/IP)
_Generated 2026-08-05T12:45:07.873445+00:00 — 30-day window_

## Direct cost efficiency (ratios, not cumulative totals)
- Merge rate: 0.262
- First-pass rate: 0.325
- $/merge (all): 0.0069
- $/merge (fresh, non-reuse only — the real per-unit cost baseline): 0.005
- Tokens/merge: 234.8

## Indirect savings from cross-project reuse
- Zero-token replay events (already inside n_merged, cost-avoidance only): 0
- Compiled-intent deterministic events (already inside n_merged, cost-avoidance only): 0
- Cross-project capability reuse events (ADDITIVE — separate from n_merged): 9
- Counterfactual cost per event (avg fresh merge): $0.005
- Gross avoided spend: $0.04
- Net avoided spend (after actual $ spent on reuse events): $0.04

## Competitor comparison — DeepSeek API (list pricing)
- DeepSeek V4-Flash: $0.14/1M in, $0.28/1M out
- DeepSeek raw $/solve (our token footprint, their price): $0.0
- Our $/solve (fresh, non-reuse): $0.005
- **Per-token verdict: we cost more per raw token than DeepSeek — do not claim otherwise**
- Portfolio coverage (271 units — n_merged + additive reuse): DeepSeek-with-no-reuse would cost $0.01 raw, $0.0 quality-adjusted; our actual cost was $1.81
- **Portfolio verdict: DeepSeek-with-no-reuse is still lower total cost at this volume/reuse rate — the reuse advantage has not yet overcome the per-token price gap, even after the quality/retry adjustment**
- _portfolio_coverage assumes DeepSeek needs the SAME tokens per solve as our pipeline (generous: no build-gate/verify/merge-train means more retries in practice) and credits DeepSeek $0 orchestration/reuse-infrastructure cost (also generous). Where quality_adjustment() is passed in, deepseek_usd_per_solve_quality_adjusted/deepseek_cost_quality_adjusted instead scale DeepSeek's cost by the sourced retry_multiplier (benchmark-score ratio) — less generous to DeepSeek where our model's sourced score is higher, but still a heuristic, not a measured result. Even so, this portfolio comparison is the only place our economics can beat a cheaper-per-token model — never claim per-token parity, see raw_per_token_verdict._

## Quality/intelligence-adjusted comparison (embedding capability, not just $/token)
Honest finding: our primary-volume model (Sonnet) is near PARITY with DeepSeek V4-Pro-Max on the more-audited benchmark — quality adjustment does NOT clearly favor us at the tier where most spend actually happens. It favors us more clearly only at the Opus escalation tier, and even there DeepSeek's points-per-dollar is dramatically better.

**Primary-volume tier — claude-sonnet-4-6 vs deepseek-v4-pro-max (swe_bench_verified):**
- Our score: 79.6 | Their score: 80.6 (near parity — do not oversell this tier's quality edge)
- Retry multiplier (heuristic): 0.9876
- Points/$ (output price) — us: 5.31, them: 92.64

**Escalation tier — claude-opus-4-8 vs deepseek-v4-pro-max (swe_bench_verified):**
- Our score: 88.6 | Their score: 80.6 (clearer quality edge here)
- Retry multiplier (heuristic): 1.0993
- Points/$ (output price) — us: 3.54, them: 92.64 (DeepSeek's points-per-dollar is roughly an order of magnitude higher than Opus's even though Opus scores higher in absolute terms — quality adjustment narrows the price gap, it does not close it)
- _retry_multiplier is a modeling heuristic (attempts-to-success ~ 1/benchmark_score), not a measured result — we do not run DeepSeek in this pipeline, so this cannot be verified empirically. points_per_dollar uses each vendor's list output-token price and is a standard, vendor-neutral efficiency metric._

## Self-improvement loop differentiator
- Capabilities published this window: 0
- Instantiations (reuse events): 9
- Avg reuse per published capability: 1.0
- _avg_reuse_per_published_capability > 1 means the average pattern this fleet learns gets applied to more than one project beyond where it was first solved — the compounding effect a single-project or single-model API relationship structurally cannot produce._

## Blended cost per unit of delivered value: $0.0067
(total $ / (merges + reuse events) — the single number that captures both direct spend
efficiency and the compounding reuse effect. This is the number to track quarter over quarter.)

---
**Do not share this file externally** — the formulas above (especially the reuse-event
valuation methodology) are the proprietary part. Share cost_intelligence_external.md instead.
