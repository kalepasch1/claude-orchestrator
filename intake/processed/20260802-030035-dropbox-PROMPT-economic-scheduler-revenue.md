# Economic-Scheduler-Revenue: Revenue-Focused Task Prioritization

SUBMITTED-BY: kale@heretomorrow.us (operator) 2026-08-01. CONTEXT: Prior session (2026-07-06) hit max_turns with permission denials, committing error telemetry instead of implementation. This PROMPT clarifies the actual scope and routes it through the normal orchestrator queue.

## Business Requirement

The fleet has multiple independent schedulers (ev_scheduler, marginal_value_scheduler, dynamic_test_scheduler, lane_scheduler, predictive_scheduler) that each optimize for different signals (expected value per token, priority/duration tradeoffs, test flakiness, deployment lanes, etc.). None explicitly optimize for **revenue-generating work** — i.e., work that demonstrably moves the business's MRR/ARR metrics forward.

Current state:
- `revenue_attribution.py` learns POST-MERGE which task kinds moved revenue (via correlation: before/after MRR snapshots)
- `ev_scheduler.py` uses that learning to boost EV scores for high-ROI kinds
- `canary_economics.py` gates deploys on cost/quality SLOs during the canary window
- No scheduler pre-filters the queue to favor revenue-generating tasks, nor does one use revenue predictions to route work

**Goal:** Build an economic-scheduler-revenue that:
1. Scores QUEUED tasks by **predicted revenue impact** (not just cost/success-rate heuristics)
2. Routes revenue-critical work to fast lanes (shorter SLA, dedicated capacity)
3. Deprioritizes speculative work if cost exceeds the expected revenue delta
4. Integrates with existing learnings (kind_roi from revenue_attribution) and telemetry (error spikes, usage trends)
5. Feeds back to ev_scheduler's context so economic signals inform all prioritization

## Acceptance Criteria

✓ Module `economic_scheduler.py` implements:
  - `predict_revenue(task, ctx)` — estimates $/merge impact for a task (returns float USD)
    - Base: look up kind's historical avg_delta from revenue_attribution.kind_roi() 
    - Adjust: if project is "high-growth" or "in-flight initiative" (via approvals table radar_tag), boost 2x
    - Adjust: if task mentions "pricing" / "payment" / "stripe" / "marketplace" keywords, boost 1.5x
    - Adjust: if error_rate spike detected for this project, boost bugfix-kind tasks 1.5x
    - Cap at $0 if no revenue signal; return confidence interval [low, high] as well as point estimate
  
  - `cost_benefit(task, ctx)` — returns {"predicted_revenue": USD, "estimated_cost": USD, "roi": ratio, "worthwhile": bool}
    - worthwhile = predicted_revenue > (1.5 × estimated_cost) — only pursue if 1.5x ROI threshold
    - Feed into park/deprioritize logic

  - `score(task, ctx)` — combined economic score (deterministic, unit-testable)
    - = (predicted_revenue / estimated_cost) × (1 + success_rate) × kind_outcome_weight(ctx)
    - Matches ev_scheduler's pure + deterministic pattern

  - `apply_routing(scored)` — route top revenue tasks to high-priority lane
    - Top 20 revenue-predicted tasks get lane="revenue-critical" annotation (create or update lane if needed)
    - Lane scheduling ensures these run in parallel, not queued behind lower-ROI work

  - `run()` — daily job: compute revenue scoring, apply routing, log stats

✓ Tests (`test_economic_scheduler.py`):
  - 15+ cases: predict_revenue for high-growth projects, revenue keywords, bugfix w/ error spikes
  - cost_benefit threshold logic (worthwhile / not worthwhile edge cases)
  - Consistent scoring across projects with/without revenue history
  - Fail-soft: missing revenue data → return 0 score, task stays queued but unprioritized
  - Verify score is deterministic (same task+ctx → same score every time)

✓ Integration:
  - `ev_scheduler.load_ctx()` calls `economic_scheduler.predict_revenue_bulk(tasks)` → feeds back into app_signals context
  - `lane_scheduler.py` reads lane annotations set by apply_routing(), respects "revenue-critical" lane
  - `approvals` table radar_tag "revenue-initiative" / "high-growth" gated by `canary_economics` rollback checks (cost must stay in SLO even for critical revenue work)

✓ No regressions:
  - Existing ev_scheduler behavior unchanged if ORCH_ECONOMIC_SCHEDULER_ENABLED=false (default OFF)
  - economic_scheduler runs as opt-in daemon, not injected into hot path

## Files Touched

- **runner/economic_scheduler.py** — new, 250–350 LOC
- **runner/test_economic_scheduler.py** — new, 400–500 LOC (20+ assertions)
- **runner/ev_scheduler.py** — patch: add call to economic_scheduler context in load_ctx() [2 LOC]
- **runner/lane_scheduler.py** — patch: add logic to read/respect "revenue-critical" lane [3 LOC]

## Proof

1. Unit test suite passes: `python3 -m pytest runner/test_economic_scheduler.py -v`
2. Integration: `python3 runner/ev_scheduler.py` logs economic signal context without error
3. Manual: drop a revenue-tagged task in intake, observe it's routed to revenue-critical lane within 60s

## Why This Matters

The orchestrator optimizes for **cost per merge** and **success rate**, but the business is optimized for **revenue per merge**. A task that costs $15 but moves $100 MRR is a 6.6x ROI, yet the queue might deprioritize it if another task is faster/cheaper. This scheduler makes the economic alignment explicit: cheap low-ROI speculative work deprioritized, high-ROI work routed to fast lanes, and team morale improves ("we work on things that matter").
