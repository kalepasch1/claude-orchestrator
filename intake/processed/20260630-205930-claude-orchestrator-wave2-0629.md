PROJECT: claude-orchestrator

# Wave 2 — break the throughput / trust / intelligence / economic ceilings of the fleet itself.
# Builds on Wave 1 (intake/claude-orchestrator-improvements-0629.md: portfolio telemetry, ROI allocator, approval
# intelligence, contract CI, shadow-replay, self-healing, trust API) and existing runner modules: resource_governor.py,
# model_router.py, claim_task (db.py), capability.py, knowledge.py/knowledge_embed.py, chaos.py, canary.py, regression.py,
# cost_ledger.py, provenance.py, privacy.py; web/pages/index.vue; the shared darwin-kernel proof substrate.
# Test convention: pytest (runner/tests/). Contract-first: contracts-fleet-substrate pins the governance/graph/revenue schema.

- id: contracts-fleet-substrate
  title: Pin governance + invariant + portfolio-graph + revenue interfaces (contract-first)
  material: yes
  model: sonnet
  depends: []
  proof: `test -f supabase/migrations/*fleet_substrate*.sql && python3 -m pytest runner/tests/test_fleet_substrate.py -q` exits 0
  prompt: |
    Interfaces only (no behavior). Migration supabase/migrations/<ts>_fleet_substrate.sql + runner/fleet_substrate.py
    pinning: (1) fleet_constitution rules (what may auto-merge / auto-deploy / auto-spend, with limits + escalation),
    (2) an invariant-registry record {project, name, checker_ref, severity}, (3) portfolio_graph node/edge tables
    (entity, capability, outcome, proof; edges with type), (4) a revenue_ledger {project, source, amount_usd, realized_at}
    that the self-funding loop reads. Pure helpers + a stubbed-db unit test. Human applies the migration (material).

- id: orchestrator-constitution
  title: Machine-checkable constitution governing auto-merge/deploy/spend
  material: yes
  model: opus
  depends: [contracts-fleet-substrate]
  proof: `python3 -m pytest runner/tests/test_orchestrator_constitution.py -q` exits 0
  prompt: |
    runner/governance.py: load the fleet_constitution and evaluate every auto-merge (pr_integrate), auto-deploy, and
    auto-spend (resource_governor) against it — allow / escalate / deny, fail-closed, bound by the existing kill switch,
    emitting a darwin-kernel receipt per decision. This is the safety substrate that lets autonomy go HIGHER safely.
    Test: an action within limits is allowed with a receipt; one exceeding a limit escalates to an approval card; kill
    switch forces deny. Material: changes the runner's own merge/deploy/spend authority — enable behind a flag.

- id: portfolio-invariant-registry
  title: Portfolio-wide invariant gate before merge
  material: yes
  model: sonnet
  depends: [contracts-fleet-substrate]
  proof: `python3 -m pytest runner/tests/test_invariant_registry.py -q` exits 0
  prompt: |
    runner/invariant_registry.py: each app registers machine-checked invariants (no-PII-egress, ECP-gating,
    value-conservation, RLS-on). pr_integrate/confidence runs the full registry for the touched app(s) before merge and
    BLOCKS on any violation, attaching the failing invariant to the task. Generalizes Tomorrow's failingInvariants to
    the portfolio. Test: a violating change is blocked; a clean one passes. Material: merge gate.

- id: adversarial-redteam-agent
  title: Standing adversary that attacks every merge (semantic, not infra)
  material: yes
  model: opus
  depends: [orchestrator-constitution]
  proof: `python3 -m pytest runner/tests/test_redteam.py -q` exits 0
  prompt: |
    runner/redteam.py: before a material merge, spawn an adversarial pass that tries to break the change — posture-
    invariant violations, prompt-injection on the legal/financial paths, auth/RLS holes, secret leakage — and files a
    blocking finding (with repro) if it succeeds. Distinct from chaos.py (infra). Gate behind the constitution. Test: a
    known-injectable diff is caught and blocked; a safe diff passes clean. Material: merge/security gate.

- id: multi-runner-fleet
  title: Horizontal multi-runner scale-out (elastic by ROI + budget)
  material: yes
  model: opus
  depends: [orchestrator-constitution]
  proof: `python3 -m pytest runner/tests/test_multi_runner.py -q` exits 0
  prompt: |
    Make N identical runners safe to run concurrently: harden claim_task for race-free optimistic claims under
    contention, partition by runner_id, respect a GLOBAL budget via resource_governor (not per-process), and add
    runner/scale.py that recommends runner count from queue depth x ROI-weighted value within budget. Add a launch
    script + docs (cloud VM, same code). Test: 50 simulated concurrent claims yield no double-claim and respect the
    global cap. Material: infra/spend. OPERATOR provisions the VMs.

- id: agent-personas
  title: Specialized agent personas auto-routed by task kind
  material: no
  model: sonnet
  depends: []
  proof: `python3 -m pytest runner/tests/test_personas.py -q` exits 0
  prompt: |
    Extend model_router.py with personas (security, performance, legal-drafting, migration, generalist): each a tuned
    system-prefix + tool/permission set + review checklist, auto-selected by task kind/labels (override allowed). A
    migration persona always name-checks + shadow-tests; a security persona always runs the redteam checklist. Test:
    a migration-kind task routes to the migration persona with its checklist; unknown kind -> generalist.

- id: portfolio-knowledge-graph
  title: Cross-app knowledge graph with entity resolution
  material: yes
  model: opus
  depends: [contracts-fleet-substrate]
  proof: `python3 -m pytest runner/tests/test_portfolio_graph.py -q` exits 0
  prompt: |
    Populate portfolio_graph: resolve entities across apps (a bank in Tomorrow == the same entity in Apparently/Smarter)
    via deterministic keys + embedding match (reuse knowledge_embed/capability dedup), and link capabilities, outcomes,
    and proofs. Add graph_query() and wire planner.py to consult it (reuse a capability, find related prior work) before
    decomposing. privacy.scrub on every write. Test: two app records for the same entity resolve to one node; a planner
    query returns linked prior work. Material: cross-app data + schema.

- id: digital-twin-sim
  title: Synthetic-market digital twins for pre-prod feature + change testing
  material: no
  model: opus
  depends: []
  proof: `python3 -m pytest runner/tests/test_digital_twin.py -q` exits 0
  prompt: |
    runner/digital_twin.py: generators for synthetic markets per app (banks/loan-tapes for Tomorrow, matters for
    Smarter, players for gaming) + a sim runner that exercises a feature/material change against the twin and reports
    correctness + value metrics BEFORE real users / before shadow-replay. Deterministic seeds. Test: a feature run
    against a seeded twin produces stable metrics; a known-bad change is flagged. Read-only (no prod), so material=no.

- id: counterfactual-roadmap-planner
  title: Simulate build-X-vs-Y -> expected portfolio value before committing
  material: no
  model: sonnet
  depends: [portfolio-knowledge-graph]
  proof: `python3 -m pytest runner/tests/test_counterfactual.py -q` exits 0
  prompt: |
    runner/roadmap.py: given candidate tasks/initiatives with cost estimates + the portfolio value model (Wave-1
    portfolio_value) and graph, simulate expected portfolio value-per-dollar and dependency-compounding for each, and
    output a ranked roadmap with rationale. Decision-quality at the portfolio level. Test: given two candidates with
    known value/cost/deps, the higher compounding-ROI one ranks first.

- id: self-funding-flywheel
  title: Realized revenue funds the build budget (remove the spend ceiling)
  material: yes
  model: opus
  depends: [orchestrator-constitution, contracts-fleet-substrate]
  proof: `python3 -m pytest runner/tests/test_self_funding.py -q` exits 0
  prompt: |
    runner/self_funding.py: read revenue_ledger (Tomorrow premiums, Smarter billables, Apparently opinions) and let
    resource_governor raise the daily build budget as a constitution-bounded fraction of realized revenue (hard ceiling,
    kill-switch, never below the safe floor). The fleet pays for its own compute from value shipped. Test: rising
    realized revenue raises the cap within the constitutional bound; the bound is never exceeded; kill switch resets to
    floor. Material: money/budget authority. OPERATOR connects the revenue/accounting sources.

- id: autonomy-product-tenancy
  title: Multi-tenant gated task submission (autonomy-as-a-product backend)
  material: yes
  model: opus
  depends: [orchestrator-constitution]
  proof: `python3 -m pytest runner/tests/test_tenancy.py -q` exits 0
  prompt: |
    Add tenant isolation so external customers (banks, law firms) can queue GATED tasks against their own tenant:
    tenants table + RLS, per-tenant budget + constitution + approval routing, and a signed submission API
    (server route) that creates QUEUED tasks scoped to the tenant. No cross-tenant data; every action proof-signed.
    Test: a tenant can submit only within its budget/scope; cross-tenant access is denied by RLS. Material: multi-tenant
    auth/RLS/data + external surface. OPERATOR decides commercial + legal terms before exposing.

- id: autonomy-product-ui
  title: Customer console — submit, track, verify (autonomy-as-a-product frontend)
  material: yes
  model: sonnet
  depends: [autonomy-product-tenancy]
  proof: `cd web && npx nuxt build` exits 0
  prompt: |
    Add a tenant-scoped web console (web/pages/tenant/*) to submit gated tasks, watch status/cost, approve their own
    material cards, and independently verify any action via the Wave-1 provable-autonomy-trust-api. Reuse the existing
    dashboard components; tenant auth only sees its own rows. Proof: web builds. Material: customer-facing surface.

- id: fleet-auto-reporting
  title: Auto-generate regulator / board / investor reports from proofs + P&L
  material: no
  model: sonnet
  depends: [contracts-fleet-substrate]
  proof: `python3 -m pytest runner/tests/test_fleet_reporting.py -q` exits 0
  prompt: |
    runner/fleet_reporting.py: point the report generator at the darwin-kernel proof log + portfolio_value + outcomes to
    produce audit packs, board decks, and (template-gated) regulator filings — each line backed by a verifiable proof id.
    Generation only (a human reviews/sends); no auto-filing. Test: a report renders with every figure carrying a proof
    reference and totals reconciling to portfolio_value.

- id: continuous-cost-down
  title: Standing objective — re-implement hot paths cheaper over time
  material: no
  model: sonnet
  depends: []
  proof: `python3 -m pytest runner/tests/test_cost_down.py -q` exits 0
  prompt: |
    A standing loop that finds the fleet's most expensive recurring call patterns (cost_ledger) and proposes cheaper
    equivalents — prompt caching, result_cache reuse, distilled/smaller models via model_router, batching — adopting
    only via eval_harness (no quality regression). Trends cost-per-feature down. Test: given a costly pattern with a
    cheaper equal-quality alternative, the loop proposes the swap; a cheaper-but-worse alternative is rejected.

- id: daily-fleet-brief
  title: One-page daily fleet brief (radical attention compression)
  material: no
  model: haiku
  depends: [contracts-fleet-substrate]
  proof: `python3 -m pytest runner/tests/test_fleet_brief.py -q` exits 0
  prompt: |
    runner/fleet_brief.py + a /api/brief route: a once-daily one-pager — what shipped, what it cost, what it earned
    (revenue_ledger/portfolio_value), what needs you (top risk-ranked approvals), and what the fleet plans next — so one
    operator runs seven apps in five minutes. Delivered via the existing notify path. Test: the brief renders with all
    five sections from stubbed data.

OPERATOR:
  - orchestrator-constitution, self-funding-flywheel, multi-runner-fleet, adversarial-redteam-agent, and the tenancy tasks change the runner's own merge/deploy/spend/auth authority — review each diff and enable behind a flag in the live runner before trusting it.
  - Apply the contracts-fleet-substrate migration to the orchestrator Supabase; for multi-runner, provision cloud VM(s) with the runner code + CLAUDE_CONFIG_DIR logins.
  - self-funding-flywheel: connect the realized-revenue/accounting sources (Tomorrow premiums, Smarter billables, Apparently opinions) and set the constitutional max-fraction + hard ceiling before enabling.
  - autonomy-product-tenancy/ui: decide commercial terms, customer legal agreements, and the public/rate-limit scope before exposing the tenant console externally.
  - fleet-auto-reporting: counsel/finance review of any regulator or investor-facing report before it is sent (generation is automated; sending is not).
