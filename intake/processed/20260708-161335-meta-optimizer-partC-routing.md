PROJECT: beethoven

- id: metaopt-c1-clean-bandit-reward-signal
  title: Exclude rate-limited/toolchain-failed/paused-window outcomes from bandit.py rewards
  material: no
  model: sonnet
  depends: []
  proof: a unit test seeds bandit.py with a mix of clean and rate-limited/paused outcomes and asserts the reward computation excludes the latter; existing bandit tests still pass
  prompt: |
    bandit.py (61 lines as of 2026-07-08) computes routing rewards from raw outcomes —
    read it first to confirm current state before changing anything. The problem: outcomes
    produced while a lane was rate-limited, mid toolchain-failure (see
    backlog-blitz-toolchain-preflight-verify in an earlier intake drop), or during a
    pause_arbiter-tracked pause window measure the ENVIRONMENT, not the model — training the
    router on them teaches it "this model is bad" when actually "the fleet was paused/throttled
    at the time."

    1. Identify what signal on an outcome row indicates a contaminated run (kill_switch pause
       overlap, a 429/rate-limit marker if outcomes records that, a toolchain-preflight-red
       project at the time). If outcomes doesn't currently record enough to detect this
       retroactively, add the minimal column/flag needed going forward (schema change ->
       material, needs one approval card) rather than guessing from indirect signals.
    2. Exclude those rows from reward computation in bandit.py.
    3. Backfill: re-tag historical outcomes you can identify as contaminated (best-effort; don't
       block on perfect historical detection).

    20+ tests: reward math with/without contamination, boundary cases (a run that started clean
    but got paused mid-flight), and that exclusion never silently drops ALL data for a
    model/task-class combo (fail-soft: if everything looks contaminated, keep the raw signal
    rather than starving the router of any data).

- id: metaopt-c2-single-route-function
  title: Merge bandit.py + model_router.py + agentic_coders.py vendor table into one route(task_class, budget, urgency)
  material: no
  model: opus
  depends: [metaopt-c1-clean-bandit-reward-signal]
  proof: route() unit tests cover all 6 task classes and existing callers (runner.py's agentic_coders.pick call site) still route correctly per their existing tests
  prompt: |
    Three routing decision points currently exist and overlap: bandit.py (61 lines),
    model_router.py (70 lines), and agentic_coders.py's pick() function (which already does
    cost x capability x task-difficulty routing with a learned-router hook via router_stats.py —
    read agentic_coders.py's pick() fully first, it's more sophisticated than the mission brief
    assumed and already covers much of what this item asks for).

    Rather than a risky from-scratch merge, evaluate whether agentic_coders.pick() can become
    the ONE route(task_class, budget, urgency) entrypoint by absorbing bandit.py's reward-learned
    posteriors and model_router.py's model-selection logic as inputs, OR whether a genuinely new
    thin wrapper over all three makes more sense. Either way: per-task-class posteriors persist
    in fleet_config as ORCH_ROUTE_* keys (fleet-wide via the existing fleet_control.py gateway,
    per repo convention — never manual per-machine config). Task classes: mechanical-batch,
    feature, refactor, test-fix, docs, self-improvement.

    Do not delete bandit.py/model_router.py/agentic_coders.py wholesale in the same change as
    building the new entrypoint — land the new route() alongside the old paths, verify it
    produces sane decisions against real recent task history, THEN switch callers over, THEN
    remove the superseded paths in a follow-up once you're confident. A one-shot rip-and-replace
    of the fleet's live routing is exactly the kind of change that could quietly tank throughput
    for days before anyone notices (no scoreboard/KPI watchdog existed for this before D1/D3).

    20+ tests across the merged decision surface: one per task class minimum, budget exhaustion
    behavior, urgency escalation, fallback when fleet_config posteriors are empty/missing.

- id: metaopt-c3-weekly-vendor-probe
  title: Fixed 5-task calibration suite across coder lanes, updates ORCH_ROUTE_* posteriors weekly
  material: no
  model: sonnet
  depends: [metaopt-c2-single-route-function]
  proof: a dry-run of the probe against a sandboxed/mocked coder pool produces a score per lane without making real spend, and a real weekly run (rate-limited to once per 7 days) updates fleet_config
  prompt: |
    New periodic job, weekly: run a fixed 5-task calibration suite through each available coder
    lane (subscription Claude, aider/deepseek, aider/gemini — check agentic_coders.available()
    for what's actually configured before assuming all three exist in this environment). Score
    speed/cost/first-pass-rate per lane, update the ORCH_ROUTE_* posteriors from C2. Alert (one
    material approval card, not a page per lane) if a lane's quality drops >20% vs its trailing
    average — this is the mission's explicit ask and doubles as an early-warning if a coder CLI
    breaks silently.

    The 5 calibration tasks should be small, cheap, deterministic-ish (e.g. a known mechanical
    fix in a scratch/smoke-test project — check for an existing "smoke-test" project row, one
    was seen in the projects table as of 2026-07-08) so this doesn't burn real budget weekly.

    20+ tests: scoring math, the >20% regression alert threshold (boundary + over/under),
    fail-soft when a lane is unavailable (skip it, don't crash the whole probe), idempotency
    (don't re-run mid-week if already run this week).

- id: metaopt-c4-wire-causal-attribution-into-eval-harness
  title: Route routing-change credit/blame through causal_attribution.py in eval_harness.py
  material: no
  model: sonnet
  depends: [metaopt-c2-single-route-function]
  proof: eval_harness.py's before/after comparison for a routing change calls causal_attribution and the resulting credit/blame is distinguishable from a raw before/after throughput delta in a test
  prompt: |
    causal_attribution.py (61 lines) and eval_harness.py (49 lines) both already exist — read
    both fully first. As of this writing eval_harness.py does NOT call causal_attribution
    anywhere (grep confirms zero references). Wire it in: when eval_harness evaluates a routing
    change (from C2/C3), use causal_attribution to separate "this change caused the KPI delta"
    from "throughput moved for an unrelated reason during the same window" before crediting or
    blaming the change. This directly feeds D3's KPI regression watchdog — a routing change that
    LOOKS bad only because of a concurrent unrelated event must not get auto-reverted for the
    wrong reason.

    20+ tests: attribution correctly isolates a routing-change-caused delta from a
    concurrent-unrelated-event delta in synthetic data, fail-soft when causal_attribution errors
    (falls back to raw before/after, doesn't block eval_harness entirely).
