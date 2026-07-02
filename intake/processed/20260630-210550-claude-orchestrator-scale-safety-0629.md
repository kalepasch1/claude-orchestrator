PROJECT: claude-orchestrator

# NOTE: orchestrator-self work (runner/ + web/ + packages/ + supabase/). Adjust PROJECT routing if
# your runner only accepts product repos (you have self-projects 'beethoven'/'ORCHESTRATOR'). Second
# batch — scale, safety-ceiling, revenue-loop, and self-improvement. One deliverable per task.

- id: runner-atomic-claim-and-container
  title: Make task claiming atomic + containerize the runner for always-on horizontal scale
  material: yes
  model: opus
  depends: []
  proof: `python3 -m pytest runner/tests/test_atomic_claim.py` exits 0
  prompt: |
    Prereq for moving off the Mac to an always-on multi-worker VM. (1) Make task claiming atomic so N
    workers never double-run a task: claim via a conditional update (compare-and-set state QUEUED->RUNNING
    with worker_id + claimed_at; reclaim stale RUNNING after a lease TTL). (2) Add runner/Dockerfile and a
    headless entrypoint reading env (SUPABASE_URL/SERVICE_KEY, account creds). Add
    runner/tests/test_atomic_claim.py simulating 2 workers racing one task -> exactly one wins; stale-lease
    reclaim works. Actual cloud VM provisioning + secrets are OPERATOR.

- id: cost-arbitrage-scheduler
  title: Route each task to the cheapest capable model/account + enforce a prompt-cache hit-rate SLO
  material: no
  model: opus
  depends: []
  proof: `python3 -m pytest runner/tests/test_cost_scheduler.py` exits 0
  prompt: |
    Build runner/cost_scheduler.py composing bandit.py (success-prob per model/task-type), model_router.py
    (capability floor), account_pool.py (rotate authorized accounts), and caching.py. For each ready task
    pick the cheapest model/account that clears the capability floor at acceptable success-prob, batch
    compatible API calls, and target a configurable prompt-cache hit-rate. Expose tasks-per-dollar metric.
    Add runner/tests/test_cost_scheduler.py: never selects below the capability floor; prefers lower
    $/expected-success; respects the global cap. Stay within Anthropic usage policy (authorized accounts only).

- id: portfolio-error-budget
  title: Per-repo error budget that auto-throttles risky changes when burn is high
  material: no
  model: sonnet
  depends: []
  proof: `python3 -m pytest runner/tests/test_error_budget.py` exits 0
  prompt: |
    Add an error-budget governor: per project, compute recent failure/rollback rate from outcomes; when
    burn exceeds the budget, the scheduler down-prioritizes material/risky tasks and prefers stability work
    until burn recovers (SRE-style). Surface budget state for the console. Add runner/tests/test_error_budget.py:
    high burn throttles risky tasks; healthy burn does not.

- id: coverage-gap-test-backfill
  title: Detect hot untested code paths and emit test-writing tasks to raise the merge gate
  material: no
  model: sonnet
  depends: []
  proof: `python3 -m pytest runner/tests/test_coverage_backfill.py` exits 0
  prompt: |
    "Tests as the gate" only protects tested code. Build runner/coverage_backfill.py that ranks files by
    (change-frequency x absence-of-tests) per repo (use git churn + a test-presence heuristic) and emits
    intake tasks to write characterization tests for the top N, gated by the repo's own test command. Add
    runner/tests/test_coverage_backfill.py for the ranking + task emission (do not run the target repos here).

- id: adversarial-redteam-gate
  title: Pre-merge red-team agent (prompt-injection, compliance bypass, auth/RLS holes)
  material: yes
  model: opus
  depends: []
  proof: `python3 -m pytest runner/tests/test_redteam.py` exits 0
  prompt: |
    Extend chaos.py into an adversarial pre-merge gate: for each change, an agent actively attempts to
    break it — prompt-injection against the legal/pricing bots, compliance/ECP-gate bypass, auth/RLS
    escapes, secret exfiltration. Findings above a severity block the merge and route to human. Add
    runner/tests/test_redteam.py with a planted vulnerable diff blocked and a clean diff passed (mock the agent).

- id: reversibility-classifier
  title: Classify each change reversible vs irreversible; gate ONLY the irreversible/regulated
  material: yes
  model: opus
  depends: []
  proof: `python3 -m pytest runner/tests/test_reversibility.py` exits 0
  prompt: |
    The principled basis for all approval rules. Build runner/reversibility.py classifying a change as
    reversible (code/tests, behind a flag, revertible commit) vs irreversible/regulated (data migration,
    money movement, external send/filing, schema drop, prod secret). Reversible flows freely (auto + 
    rollback-gated); irreversible/regulated always stops for human. Feed the policy engine. Add
    runner/tests/test_reversibility.py: migration/money/legal => irreversible; flagged code change => reversible.

- id: invariant-merge-gate
  title: Require property/invariant proofs on any money/risk function before merge
  material: yes
  model: opus
  depends: []
  proof: `python3 -m pytest runner/tests/test_invariant_gate.py` exits 0
  prompt: |
    Tomorrow already ships property-based invariant harnesses (e.g. netting conservation, ES subadditivity,
    floor H1/H2). Generalize: the verify step blocks a merge that touches a money/risk function (path/tag
    allowlist) unless its invariant test set runs and passes. Maintain a registry mapping functions->invariant
    suites. Add runner/tests/test_invariant_gate.py: a money-fn change without passing invariants is blocked.

- id: market-regulatory-signal-generation
  title: Drive proposal generation from real product analytics, support, and regulator feeds
  material: no
  model: sonnet
  depends: []
  proof: `python3 -m pytest runner/tests/test_signal_ingest.py` exits 0
  prompt: |
    Wire demand_mining.py to real signals instead of internal heuristics: product analytics, support
    tickets, and regulator feeds (Apparently already has regulatory-scrape; Tomorrow tracks CFTC/Basel).
    A regulator change auto-files a cited "rule changed -> update X" proposal; a recurring support theme
    files a fix/feature proposal. Each carries source + citation in detail. Add runner/tests/test_signal_ingest.py:
    a regulator delta yields a cited proposal; dedup against open ones.

- id: cross-product-identity-flywheel
  title: Verify-a-fact-once, reuse-everywhere with consent + provenance (darwin-kernel)
  material: yes
  model: opus
  depends: []
  proof: `npx vitest run packages/darwin-kernel/test/flywheel.test.ts` exits 0
  prompt: |
    Productize the flywheel already proven in packages/darwin-kernel/test/flywheel.test.ts (KYC-once ->
    underwrite-everywhere with scoped consent). Build a consent-gated claim/passport exchange so a fact
    verified by one product (e.g. Galop KYC, Pareto financial profile) is reusable by another ONLY with an
    explicit consent grant + provenance, never silently. Enforce: no claim crosses a product boundary
    without a matching consent record; PII never travels, only signed claims. Extend the existing test to
    cover a denied (no-consent) cross-use and a granted one. Material: PII/consent.

- id: meta-prompt-learning
  title: Auto-refine the runner's own task-prompt templates from pass/rework outcomes
  material: no
  model: sonnet
  depends: []
  proof: `python3 -m pytest runner/tests/test_meta_prompt.py` exits 0
  prompt: |
    The highest-order loop: improve the self-improver's instructions. Track per task-template the
    first-try-pass rate vs rework/turn-count (from outcomes). When a template underperforms, propose a
    refined template (human-gated) and A/B it via auto_experiment.py; promote the winner. Add
    runner/tests/test_meta_prompt.py for the scoring + challenger proposal (no live model calls in the test).

- id: operator-preference-model
  title: Calibrated "operator twin" that pre-decides the routine and escalates only novelty
  material: yes
  model: opus
  depends: []
  proof: `python3 -m pytest runner/tests/test_operator_twin.py` exits 0
  prompt: |
    Turn the existing "approval likelihood" prediction into a calibrated decision policy trained on real
    decided approvals: it may auto-decide only where calibrated confidence is very high AND the
    reversibility classifier says reversible AND policy floor allows; everything novel/low-confidence
    escalates. Track calibration (predicted vs actual) and auto-widen the escalation band if calibration
    drifts. Add runner/tests/test_operator_twin.py: high-confidence-reversible auto-decided; novel/legal escalated.

- id: cross-project-schema-contracts
  title: Contract tests + shared registry across the 10 Supabase projects to stop cross-project drift
  material: yes
  model: sonnet
  depends: []
  proof: `python3 -m pytest runner/tests/test_schema_contracts.py` exits 0
  prompt: |
    Cross-project schema drift is a recurring prod-failure source. Build a shared schema/contract registry:
    for each cross-project dependency (e.g. shared table shapes, S2S payloads, the corpus service used by
    apparently+tomorrow), define a contract; a CI check fails when a migration in one project violates a
    consumer's contract. Add runner/tests/test_schema_contracts.py for contract definition + a violating
    change detected. (Read-only against project schemas; no migrations here.)

OPERATOR:
  - Provision the always-on cloud VM + worker autoscaling and set runner secrets there (atomic-claim + Dockerfile make it safe; provisioning itself is operator).
  - Approve prod-merge of the material tasks (atomic-claim, red-team gate, reversibility, invariant gate, identity flywheel, operator twin, schema contracts) after CI + eval.
  - Identity flywheel: confirm the consent model + data-residency/PII policy with counsel before any real cross-product claim reuse.
  - Provide held-out datasets: legal opinions (Apparently) and pricing/quotes (Tomorrow) for shadow + invariant + operator-twin calibration.
  - Confirm only Anthropic-authorized accounts feed account_pool for the cost-arbitrage scheduler.
