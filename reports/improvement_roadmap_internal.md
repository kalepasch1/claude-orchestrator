# Improvement Roadmap - 50x-500x claim, disclosed assumptions (internal)

Live data used for baseline: True
Baseline gap vs DeepSeek (quality-adjusted, per unit of value): Nonex

## Stage 0 - baseline (measured or last-computed)
- Projected blended cost/unit: $0.0067
- Gap vs DeepSeek (quality-adjusted): Nonex
- _No projected change applied. This is the input, not a target._

## Stage 1 - near-term (levers already merged, not yet at scale)
- Projected blended cost/unit: $0.0022
- Gap vs DeepSeek (quality-adjusted): Nonex
- _Assumes: capability reuse velocity roughly doubles as more of the existing 5-project portfolio picks up already-published capabilities (no new mechanism required, just wider adoption of proof_propagation/cross_project_templates); zero-token+compiled-intent share of merges rises to 45% as intent_compiler matures more intents past its promotion threshold; fresh-merge cost falls 15% from context_cache_distill.py trimming input tokens (already-measured: 879->765 cache entries, ~13% reduction, on the one repo distilled so far)._

## Stage 2 - mid-term (portfolio scale + quality-aware routing)
- Projected blended cost/unit: $0.001
- Gap vs DeepSeek (quality-adjusted): Nonex
- _Assumes: reuse velocity grows 5x baseline as the fleet scales to more projects (each new project is a new instantiation surface for existing capabilities, so reuse should scale faster than linear with project count, but this is a projection, not observed); zero-token+compiled-intent share reaches 65% as the compiled-intent library covers most repeat problem shapes; fresh-merge cost falls 35% combining deeper context distillation with cade_tournaments routing lower-complexity tasks to Sonnet/Haiku-tier instead of defaulting to Opus._

## Stage 3 - aggressive/aspirational (upper bound of the 50-500x claim)
- Projected blended cost/unit: $0.0002
- Gap vs DeepSeek (quality-adjusted): Nonex
- _Assumes: reuse velocity reaches 15x baseline (requires materially more projects on the fleet than exist today, and mature enough capabilities that near-zero customization is needed — NOT demonstrated at current scale); zero-token share reaches 85% (would require most of the queue to be repeat problem shapes, which is a property of the eventual steady-state workload mix, not something we control); fresh-merge cost falls 55% via aggressive distillation + routing nearly all non-escalation work to the cheapest model that clears the quality bar. This stage is explicitly the upper bound of plausibility, not a committed target or timeline._

## Verdict
Insufficient data to state a verdict.
