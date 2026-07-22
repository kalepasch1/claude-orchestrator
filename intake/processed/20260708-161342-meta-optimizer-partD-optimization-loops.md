PROJECT: beethoven

- id: metaopt-d1-scoreboard-persist-and-dashboard
  title: Verify/extend scoreboard.py to persist hourly for 30+ days and surface a dashboard card
  material: no
  model: sonnet
  depends: []
  proof: querying the scoreboard's storage 31 days after a snapshot still returns it, and the web dashboard renders a card sourced from it
  prompt: |
    scoreboard.py already exists (180 lines as of 2026-07-08) and already computes most of D1's
    target metrics from the `outcomes` table over a rolling window (queue mix, merge rate,
    first-pass rate, spend, tokens, paused minutes) — read it fully before assuming this is
    greenfield; D1 as originally scoped ("new table + dashboard card... snapshot hourly...
    persist >=30 days") is LARGELY ALREADY BUILT. Your job is verification + the specific gaps:

    1. Confirm it's actually scheduled hourly (check runner.py's schedule table) and that
       whatever it writes to (a `controls` heartbeat row per its docstring, "and an optional
       table insert if present") actually persists >=30 days of history, not just the latest
       snapshot overwriting itself. If it only keeps latest, add real history (a dedicated table
       via migration — material, one approval card — or an append-only JSONL if a full table is
       overkill; your call, document why).
    2. Add the remaining D1 metrics if missing: objective->prompt lead time, prompt->merged lead
       time (both newly measurable once prompt_factory.py/prompt_assembler.py, already shipped,
       have been running a while — token_estimate logging from prompt_assembler.stats() feeds
       tokens/task already), knowledge reuse hit-rate (depends on metaopt B4/retrieval telemetry
       if that's landed by the time you pick this up — check first), deploy success rate.
    3. Surface on the dashboard: reuse existing card/table components in web/pages, don't invent
       a new pattern.

- id: metaopt-d2-loop-cadence
  title: Wire hourly/nightly/weekly optimization cadence into the existing scheduler
  material: no
  model: opus
  depends: [metaopt-d1-scoreboard-persist-and-dashboard, metaopt-c3-weekly-vendor-probe]
  proof: runner.py's schedule table shows generator_feedback+queue_velocity on an hourly cadence, self_review with an auto-apply tier gated by blast_radius.py nightly, and meta_loop/prompt_distillation refresh/C3 probe/template-A-B weekly — each verified by a dedicated test asserting the schedule-table entry and the gating logic
  prompt: |
    Extend the EXISTING scheduler (runner.py's big schedule table, ~1550+ lines in — grep
    for the table near other "-daily"/"-interval" entries; do not add a second scheduler).

    - hourly: generator_feedback.py (148 lines, exists) + queue_velocity.py (186 lines, exists)
      already run periodically per runner.py's schedule — verify their cadence is actually
      hourly and that they're actually coordinated (generation matched to execution capacity),
      not just both independently scheduled near an hour mark.
    - nightly: self_review.py (109 lines, exists) proposals need an auto-apply tier: a proposal
      scoring low blast-radius (config/prompt-template/cadence changes, no schema/security
      surface — blast_radius.py, 52 lines, exists, read its current scoring logic) auto-merges
      through eval_harness.py's A/B gating (49 lines, exists — extend, this is a small module).
      Everything else lands in ONE clustered approval digest, not one card per proposal (repo
      guardrail: batch material approvals).
    - weekly: meta_loop.py (146 lines, exists) cross-deploys best loop configs; prompt_distillation
      "refreshes project briefs" — NOTE: prompt_distillation.py already exists but does per-TASK
      template distillation, not project briefs (see prompt_assembler.py's module docstring for
      why "project brief" ended up living in prompt_assembler._project_brief instead) — the
      weekly refresh here should mean re-running prompt_distillation.run() to recompute
      template-library stats, and separately confirming prompt_assembler's per-project brief
      generation is fresh (it's generated live per-call already, not cached, so "refresh" may be
      a no-op for that piece — verify, don't assume more work is needed than there is); C3's
      vendor probes (see partC intake); template A/B rotation (keep 1 challenger template per
      task class live at 10% traffic — this is new, no existing template-variant infra found as
      of 2026-07-08, will need real design).

    20+ tests total across the cadence wiring and the auto-apply tier's blast-radius gate
    specifically (that's the highest-risk piece — a mis-scored "low blast radius" auto-merge is
    exactly the kind of thing that should never silently touch billing_guard/kill_switch/schema/
    deploy wiring; the auto-apply hard limits from the mission's own guardrails section apply
    here verbatim).

- id: metaopt-d3-kpi-regression-watchdog
  title: Auto-revert an auto-applied self-improvement that fails to move its declared KPI in 24h
  material: no
  model: sonnet
  depends: [metaopt-d1-scoreboard-persist-and-dashboard, metaopt-d2-loop-cadence, metaopt-c4-wire-causal-attribution-into-eval-harness]
  proof: a synthetic auto-applied change with a declared target KPI that doesn't move (or regresses any KPI >10%) within a simulated 24h window produces a logged postmortem row and a revert
  prompt: |
    Depends on D2's auto-apply tier existing first (nothing to watchdog without it) and C4's
    causal attribution (so a KPI miss is correctly attributed to the change itself, not a
    coincidental concurrent event — see metaopt-c4 for why this matters). Every auto-applied
    self-improvement from D2's nightly tier must declare its target KPI at apply time (reuse
    whatever KPI schema D1's scoreboard settled on). eval_harness.py compares 24h before/after;
    if the KPI didn't move (or ANY KPI regressed >10%), auto-revert with a logged postmortem row
    (what changed, what KPI was targeted, what actually happened, why it was reverted).

    20+ tests: the "didn't move" threshold (noise band vs real miss), the >10% regression
    trigger on a KPI that WASN'T the declared target, revert mechanics (must be a clean git
    revert of the specific auto-applied commit, not a broader rollback), and the postmortem row
    schema.

- id: metaopt-d4-objective-intake
  title: Simple objectives flow (dashboard or intake/objectives.md) feeding prompt_factory
  material: no
  model: haiku
  depends: []
  proof: writing one line to intake/objectives.md results in a new row in the goals table (or wherever prompt_factory.gather_objectives() reads from) without any other manual step
  prompt: |
    prompt_factory.py (shipped 2026-07-08) already reads objectives from the `goals` table
    (status='active') — this item is much smaller than it looks: just need an ingestion path
    INTO that table from a plain-text drop. Add support for `intake/objectives.md` (a flat list
    of one-line objectives, distinct from the canonical task-DAG format — don't overload the
    existing PROJECT:/- id: parser for this, it's a different shape) that intake_watcher.py (or
    a tiny new sibling function) turns into `goals` table rows (status='active', priority
    assigned by position in the file or a simple heuristic). A dashboard text-input calling the
    same insert path is a nice-to-have if time allows, not required for this item's proof.

    20+ tests: parsing the flat objectives.md format, idempotency (same objective line dropped
    twice doesn't duplicate), malformed lines fail-soft (skip, don't crash the whole file).

- id: metaopt-d5-monthly-subsystem-audit
  title: Rank periodic jobs by KPI contribution vs incidents caused; propose disabling bottom decile
  material: yes
  model: opus
  depends: [metaopt-d1-scoreboard-persist-and-dashboard]
  proof: a monthly report lists every periodic job in runner.py's schedule table with a KPI-contribution score and an incident count, and the bottom-decile disable proposal is a single material approval card (not auto-applied)
  prompt: |
    Extend self_review.py (109 lines, exists) with a monthly pass: enumerate every job in
    runner.py's schedule table (there are 100+ as of 2026-07-08 — this module count is itself
    named as a KPI drag in the mission that spawned this item), attribute KPI contribution
    (from D1's scoreboard) and incidents caused (pause_arbiter trips, revert postmortems from
    D3, build failures attributable to the job) to each, and propose disabling the bottom decile.
    This is explicitly MATERIAL (disabling live periodic jobs) — one approval card for the whole
    monthly batch, never auto-applied, per repo guardrails.

    20+ tests: the ranking/scoring math, that a job with zero incidents but also zero measurable
    KPI contribution is treated differently from a job with negative contribution (don't punish
    jobs that are pure infrastructure/safety with no direct KPI line, e.g. kill_switch or
    pause_arbiter itself — hard-exclude jobs the guardrails already say auto-apply may never
    touch: subscription_guard, billing_guard, kill_switch, pause_arbiter, worktree_gc).
