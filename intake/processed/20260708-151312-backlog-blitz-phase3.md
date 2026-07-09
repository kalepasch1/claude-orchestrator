PROJECT: beethoven

- id: backlog-blitz-governor-ram-floor
  title: Lower resource governor RAM floor to 4GB fleet-wide via fleet_config, target 6-8 lanes
  material: yes
  model: sonnet
  depends: []
  proof: `python3 -c "import db; print([r for r in db.select('fleet_config',{'select':'*','key':'eq.RAM_FLOOR_GB'})])"` shows value 4, and autopilot_state.json snapshots show sustained lane count without OOM/thermal incidents over the following hour
  prompt: |
    Current `fleet_config` has RAM_FLOOR_GB=6 and ORCH_RUNNER_FLEET_TARGET=8 (already at the
    mission's target lane count — verify what's actually constraining concurrency to 16-ish
    "running" if the target is already 8; the constraint may not be RAM floor at all, check
    resource_governor.py's actual clamp logic before assuming this is the bottleneck).

    This is a MATERIAL change (governor floor, per repo guardrails) — file ONE approval card
    describing: current floor (6GB), proposed floor (4GB), the risk (higher OOM/thrash risk on
    Mac 1 under concurrent load), and the rollback (bump the fleet_config row back to 6). Do not
    apply the change until approved. Once approved, change via `fleet_control`/`fleet_config`
    (never manual SSH, never hand-edit a machine's local env) so Mac 2 picks it up too. Confirm
    Mac 2 is on current code first via a `fleet_control` git_pull + restart row before assuming
    it'll pick up the new floor correctly — Mac 2 sync status is unverified as of this writing.

- id: backlog-blitz-routing-cheap-lanes
  title: Confirm judgment-heavy tasks route to subscription lanes, mechanical batches to cheap coders
  material: no
  model: sonnet
  depends: [backlog-blitz-batch-fusion-unpause]
  proof: sample 20 recent task outcomes and confirm model/lane assignment matches task class (mechanical->cheap lane, feature/judgment->subscription) at >=80% agreement
  prompt: |
    `fleet_config` already has `ORCH_EXTRA_CODERS` configured with ollama/gemini/deepseek/gpt
    cheap lanes and cost/cap/daily_usd fields, so most of the routing table already exists —
    don't rebuild it. Verify (not necessarily rebuild) that: (a) judgment-heavy task classes
    (feature, refactor, architecture-touching) are actually routed to subscription Claude lanes,
    not cheap coders; (b) fused mechanical batches from the batch_fusion task land on the cheap
    lanes; (c) the billing firewall from Phase 0 holds — grep recent outcomes for any
    ANTHROPIC_API_KEY usage that isn't explicitly ORCH_ALLOW_API_BILLING-opted-in. If routing
    already does this correctly, this task is a verification-only close with evidence attached,
    not a rewrite.

- id: backlog-blitz-context-diet-verify
  title: Verify context_cache_distill.py replaces the 13.8MB .orch-context-cache.json as task context
  material: no
  model: sonnet
  depends: []
  proof: `git check-ignore .orch-context-cache.json` exits 0 (file is gitignored) AND per-task input token counts in outcomes drop measurably vs the pre-distillation baseline
  prompt: |
    context_cache_distill.py and its test already exist as of 2026-07-08, built by a concurrent
    fleet agent — check current state before rebuilding. Confirm it actually: (1) generates a
    distilled per-project brief (<=4KB) instead of dumping the full context cache into task
    prompts, (2) is wired into whatever assembles the prompt sent to coders (prompt_assembler.py
    if it exists yet from the separate meta-optimizer mission, otherwise wherever claude_cli.py /
    agentic_coders.py currently build the prompt), and (3) `.orch-context-cache.json` is added to
    .gitignore and removed from git tracking (`git rm --cached` if it's tracked — check first,
    don't blindly rm). If any of these three are missing, add them; if all present, this is a
    verification close.
