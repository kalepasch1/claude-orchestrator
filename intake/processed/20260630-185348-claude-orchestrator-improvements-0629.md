PROJECT: claude-orchestrator

# Meta-layer 10-200X improvements to the orchestrator itself (the fleet's learning rate + operator bandwidth).
# Builds on existing runner modules: roi.py, bandit.py, meta_loop.py, auto_experiment.py, eval_harness.py (+ evals.json),
# planner.py, capability.py, demand_mining.py, opportunity_scout.py, regression.py, canary.py, watchdog.py, chaos.py,
# fix_propagation.py, approval_merge.py, cost_ledger.py, model_router.py; the `outcomes` table; web/pages/index.vue + MissionControl.vue;
# and the shared darwin-kernel proof substrate (public verifier route).
# Test convention: pytest (see runner/tests/test_safety.py). Each task adds its own runner/tests/test_*.py.
# Contract-first: contracts-portfolio-telemetry pins the value/telemetry schema everything else reads.

- id: contracts-portfolio-telemetry
  title: Portfolio value/telemetry schema + shared interface (contract-first)
  material: yes
  model: sonnet
  depends: []
  proof: `test -f supabase/migrations/*portfolio_value*.sql && python3 -m pytest runner/tests/test_portfolio_telemetry.py -q` exits 0
  prompt: |
    Add the value signal the whole fleet will allocate on. Migration supabase/migrations/<ts>_portfolio_value.sql:
    extend `outcomes` with value_usd numeric default 0 and value_kind text (e.g. capital_freed, avoided_loss,
    matter_closed, opinion_shipped); add a `portfolio_value` view aggregating spend (cost_ledger/outcomes.usd) vs
    value_usd per project + per kind over time. Add runner/portfolio_telemetry.py: pure helpers
    record_value(task_id, value_usd, value_kind) and value_per_dollar(project) reading the view; no behavior change
    yet. Unit-test the pure helpers with a stubbed db. Human applies the migration to prod (material).

- id: portfolio-roi-allocator
  title: ROI allocator — distribute the daily budget across apps by realized value-per-dollar
  material: yes
  model: opus
  depends: [contracts-portfolio-telemetry]
  proof: `python3 -m pytest runner/tests/test_roi_allocator.py -q` exits 0
  prompt: |
    Today bandit.py picks a MODEL per task; nothing allocates spend ACROSS projects. Add runner/roi_allocator.py
    extending roi.py: a Thompson-sampling/UCB allocator that, given portfolio_value.value_per_dollar per project and
    the remaining daily budget (resource_governor/cost_ledger), returns the next project to pull a QUEUED task from
    (claim_task becomes ROI-weighted, not just created_at order). Cold-start = uniform; explore-exploit with a floor
    so no project starves. Pure, deterministic given seed. Test: a high-value project gets a higher pull probability;
    floor guarantees every project is eventually served. Material: changes how budget/spend is allocated.

- id: meta-learning-build-loop
  title: Optimize cost-per-shipped-feature (self-tuning build strategy)
  material: yes
  model: opus
  depends: [contracts-portfolio-telemetry]
  proof: `python3 -m pytest runner/tests/test_meta_build_loop.py -q && python3 runner/eval_harness.py --candidate runner/tests/fixtures/cand_prefix.txt` exits 0
  prompt: |
    Elevate meta_loop.py + auto_experiment.py + eval_harness.py from prompt A/B to optimizing cost-per-shipped-value.
    Define the objective = value_usd shipped per $ spent per merged task. Let the orchestrator A/B its own knobs
    (model-per-kind via model_router/bandit, speculative N-best vs single, planner granularity, prompt prefixes) and
    adopt a variant only if eval_harness shows >= pass-rate AND lower cost-per-shipped (populate evals.json with a
    held-out task set). Test: given two synthetic strategy arms with known value/cost, the loop selects the cheaper-
    per-value arm and never adopts a regression. Material: modifies the self-improvement adoption path.

- id: capability-reuse-planner
  title: Reuse-before-rebuild — planner searches the capability registry first
  material: no
  model: sonnet
  depends: []
  proof: `python3 -m pytest runner/tests/test_capability_reuse.py -q` exits 0
  prompt: |
    Make planner.py query capability.py (the cross-app registry, pgvector dedup) BEFORE decomposing, so a task that
    matches an existing capability emits a "reuse/instantiate" sub-task instead of a "build from scratch" one. Add
    capability.publish() calls on successful merges that distill the winning diff+test into a reusable capability
    (privacy.scrub + provenance already enforced). Add a thin semver contract so consumers pin versions. Test: a task
    whose embedding matches a registered capability is planned as reuse (not rebuild); an unmatched task still builds.

- id: demand-to-backlog-loop
  title: Close the demand -> intake loop (build what the market wants, gated)
  material: yes
  model: sonnet
  depends: [portfolio-roi-allocator]
  proof: `python3 -m pytest runner/tests/test_demand_backlog.py -q` exits 0
  prompt: |
    Wire demand_mining.py + opportunity_scout.py outputs into intake: when a demand/opportunity signal clears a
    confidence threshold, auto-draft an intake/*.md file (canonical format, material=yes by default) for the relevant
    project, ranked by the ROI allocator's value model. NEVER auto-queue material work without a human — drop the file
    and raise an approval card summarizing the opportunity + projected value. Test: a high-confidence demand signal
    produces a well-formed intake draft + a pending approval; a low-confidence one does not. Material: spawns work/spend.

- id: cross-app-contract-ci
  title: Portfolio contract + golden-set gate before any merge
  material: yes
  model: sonnet
  depends: []
  proof: `python3 -m pytest runner/tests/test_contract_ci.py -q` exits 0
  prompt: |
    A change in one app can silently break a shared interface (e.g. Tomorrow<->Apparently xappSignal/S2S). Add
    runner/contract_ci.py invoked by pr_integrate/confidence before merge: it runs each app's shared-contract tests
    (the contracts-* interfaces) + that app's golden set (regression.py/eval_harness) and BLOCKS the merge on any
    cross-app contract break, attaching the failing contract to the task note. Test: a simulated contract drift blocks
    the merge; a compatible change passes. Material: modifies the merge gate.

- id: shadow-prod-replay
  title: Prove material changes safe in a shadow before raising the approval card
  material: yes
  model: opus
  depends: []
  proof: `python3 -m pytest runner/tests/test_shadow_replay.py -q` exits 0
  prompt: |
    For material tasks (migrations/money/auth), add runner/shadow_replay.py: apply the change to a prod-faithful shadow
    DB and replay a captured/synthetic request set, asserting no errors + invariants hold, BEFORE the human approval
    card is created. The card then shows "shadow: PASS (N requests, 0 errors)" so the human approves something already
    proven. Fail-closed: no shadow pass => card flagged high-risk, never auto-anything. Test (stubbed shadow): a safe
    change yields PASS and a green card; a breaking change yields FAIL and a high-risk card. Material: deploy/migration path.

- id: self-healing-prod-loop
  title: Canary -> auto-rollback -> auto-fix-task (close the production loop)
  material: yes
  model: opus
  depends: []
  proof: `python3 -m pytest runner/tests/test_self_healing.py -q` exits 0
  prompt: |
    Close the loop across canary.py + watchdog.py + chaos.py + fix_propagation.py: on a failed canary or watchdog
    breach post-deploy, automatically (1) roll back to the last-good revision, (2) open a fix task via fix_propagation
    with the failure signature + logs, (3) raise an FYI approval card (not a gate). Production telemetry becomes a gate,
    not just tests. Test: a simulated canary failure triggers rollback + a fix task + an FYI card; a healthy canary does
    nothing. Material: touches deploy/rollback.

- id: approval-intelligence-engine
  title: Trust-ratchet for the orchestrator's own approvals (learn, batch, risk-rank)
  material: yes
  model: opus
  depends: [contracts-portfolio-telemetry]
  proof: `python3 -m pytest runner/tests/test_approval_intel.py -q` exits 0
  prompt: |
    Apply the trust-ratchet to approval_merge.py: learn from the operator's past decide() history which (project, kind,
    pattern) classes are always-approved and auto-approve those below a risk threshold (logged, reversible); cluster
    near-identical pending cards into ONE batched card ("approve all 6 DARWIN env-sets?"); risk-rank the queue so the few
    high-stakes cards float to the top; attach a one-paragraph "why this is safe" digest per card. NEVER auto-approve
    legal/secret/material-high-risk. Test: a repeatedly-approved low-risk class auto-approves; a legal card never does;
    duplicates collapse into one batch. Material: modifies the runner's own approval path (review before enabling live).

- id: approval-intelligence-ui
  title: Dashboard — batched cards, risk-ranking, one-click execute
  material: yes
  model: sonnet
  depends: [approval-intelligence-engine]
  proof: `cd web && npx nuxt build` exits 0
  prompt: |
    Update web/pages/index.vue + components/MissionControl.vue "Needs your approval" panel to render batched cards
    (expand to see members; Approve-all / Approve-some), show the risk rank + the engine's safety digest, and add a
    one-click "Run it" button for cards whose action is mechanical and carries an exact command (calls a new
    CRON_SECRET/service-gated runner endpoint that executes the command and records the result on the card). Legal/secret
    cards never get one-click execute. Proof: web builds. Material: can trigger execution from the dashboard.

- id: fleet-pnl-dashboard
  title: Fleet P&L — spend -> shipped value -> realized outcome per app
  material: no
  model: sonnet
  depends: [contracts-portfolio-telemetry]
  proof: `cd web && npx nuxt build` exits 0
  prompt: |
    Add a web page /fleet reading the portfolio_value view: per-project and portfolio-wide spend vs value_usd vs
    realized outcomes over time, value-per-dollar leaderboard, and the ROI allocator's current weights. Read-only,
    one screen, so one operator can see where to scale or kill. Proof: web builds.

- id: provable-autonomy-trust-api
  title: Unified external verify/audit API over the darwin-kernel proofs
  material: yes
  model: opus
  depends: []
  proof: `cd web && npx nuxt build` exits 0
  prompt: |
    Generalize the darwin-kernel public verifier into one portfolio audit API: server route GET /api/verify/:proofId
    (Ed25519-verify a proof from any app offline) and GET /api/audit/:project (paginated, signed action log) so
    customers/regulators/partners can independently verify any autonomous action across all seven apps. Read-only,
    rate-limited, no secrets exposed. Proof: web builds. Material: exposes a public data surface (review scope before deploy).

OPERATOR:
  - Register a `claude-orchestrator` project in the projects table (name: claude-orchestrator, repo_path: /Users/kpasch/Documents/beethoven/claude-orchestrator) if not already present, so these tasks attach.
  - approval-intelligence-engine + approval-intelligence-ui + self-healing-prod-loop modify the runner's own approval/merge/deploy path — review the diffs and enable behind a flag in the live runner before trusting them.
  - Apply the contracts-portfolio-telemetry migration to the orchestrator Supabase; provision a prod-faithful shadow DB + a captured request set for shadow-prod-replay.
  - Deploy the fleet-pnl page + provable-autonomy-trust-api to the orchestrator's Vercel web project; decide the public/rate-limit scope of the audit API before exposing it externally.
  - Seed evals.json with a held-out task set so meta-learning-build-loop and eval_harness can gate adoptions.
