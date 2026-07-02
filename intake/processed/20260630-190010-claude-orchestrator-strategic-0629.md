PROJECT: claude-orchestrator

# Strategic layer. Most tasks add new modules to packages/darwin-kernel (pure, additive
# TypeScript, node:test gates); the orchestrator-as-product + budget-loop + red-team tasks
# touch runner/ and web/. Keep the kernel's full suite green after each:
#   cd packages/darwin-kernel && node --test --experimental-strip-types test/*.test.ts
# Prerequisite modules referenced below (already queued/built): orchestratorClient (registry,
# metering, economics), governance (policyService, receipts), attestation (feed), federated,
# identity (rollups), flywheel.

- id: intent-router
  title: One natural-language intent → cross-product capability route plan
  material: no
  model: sonnet
  depends: []
  proof: `cd packages/darwin-kernel && node --test --experimental-strip-types test/intentRouter.test.ts` exits 0
  prompt: |
    Build the single front door: an intent string is decomposed into a governed plan over the
    capability registry spanning all products. Deterministic core (testable); LLM enrichment is
    a documented hook, not required for the core path.
    Steps:
    1. Add src/orchestratorClient/intentRouter.ts: routeIntent(intent, { capabilities, constitution })
       -> { steps: {capabilityId, owner, reason}[], blocked: string[] }. Match intent keywords/tags
       to published CapabilitySpecs (e.g. "hedge deposit book" -> tomorrow:price_swap +
       fabric_run; "plan retirement" -> pareto:monte_carlo + allocator; "review contract" ->
       smarter:obligation_extraction). Run each candidate step through evaluateConstitution; drop
       denied steps into `blocked`.
    2. Re-export from src/orchestratorClient/index.ts.
    3. Add test/intentRouter.test.ts: three intents each route to the expected product capabilities;
       a denied step lands in `blocked`, never `steps`.

- id: capability-program-composer
  title: Compose capabilities into higher-order DAG "programs"
  material: no
  model: sonnet
  depends: [intent-router]
  proof: `cd packages/darwin-kernel && node --test --experimental-strip-types test/program.test.ts` exits 0
  prompt: |
    Turn the library of leaf capabilities into reusable end-to-end workflows.
    Steps:
    1. Add src/orchestratorClient/program.ts: defineProgram(steps[]) where each step names a
       capabilityId + an input mapper from prior outputs (a small DAG with explicit deps);
       runProgram(program, registry, seedInput) executes in topological order via the registry
       and returns per-step outputs. Detect cycles (throw) and short-circuit on a step error.
    2. Ship one example program "underwrite_then_hedge" (pareto:financial_profile-ish input ->
       tomorrow:parametric_displacement) as a fixture.
    3. Add test/program.test.ts: a 3-step program runs in order through a memoryTransport registry;
       a cyclic program is rejected; a failing step short-circuits with a typed error.

- id: runtime-memory
  title: Cross-product runtime outcome memory (query before acting)
  material: no
  model: sonnet
  depends: []
  proof: `cd packages/darwin-kernel && node --test --experimental-strip-types test/runtimeMemory.test.ts` exits 0
  prompt: |
    Extend the orchestrator's code-regression-memory idea to RUNTIME outcomes so every agent
    queries institutional memory before acting.
    Steps:
    1. Add src/orchestratorClient/runtimeMemory.ts: recordOutcome({product, kind, context, result,
       success, lesson}) and queryMemory(context, {kind?, limit?}) ranked by TF-IDF/keyword
       overlap (pluggable embedding hook documented, keyword fallback default). In-memory + an
       injected transport interface (Supabase later).
    2. Re-export from the orchestratorClient barrel.
    3. Add test/runtimeMemory.test.ts: recording "hedge X failed to settle" then querying a similar
       context returns it ahead of an unrelated record; empty memory returns [].

- id: standing-intent
  title: Standing-intent primitive (perpetual governed instruction)
  material: no
  model: sonnet
  depends: []
  proof: `cd packages/darwin-kernel && node --test --experimental-strip-types test/standingIntent.test.ts` exits 0
  prompt: |
    A perpetual instruction that re-evaluates as inputs change and emits a governed receipt each
    time it would act. Pure engine (no scheduler here; the host wires cron).
    Steps:
    1. Add src/governance/standingIntent.ts: defineStandingIntent({id, product, predicate(world),
       action(world)}) and evaluateStandingIntent(intent, world, constitution, prevReceipt) that,
       when predicate(world) is true, builds the action, runs governAction, and returns
       {fired, decision, receipt}. When false, returns {fired:false}.
    2. Re-export from src/governance/index.ts.
    3. Add test/standingIntent.test.ts: a predicate that flips false->true fires exactly once per
       true evaluation, the receipt chains, and a money action escalates.

- id: benchmark-products
  title: Privacy-safe cross-product benchmark builder (sellable data product)
  material: no
  model: sonnet
  depends: []
  proof: `cd packages/darwin-kernel && node --test --experimental-strip-types test/benchmark.test.ts` exits 0
  prompt: |
    Productize the federated aggregates as peer benchmarks (banks vs banks, firms vs firms).
    Steps:
    1. Add src/federated/benchmark.ts: buildBenchmark(metric, cohortValues[], subjectValue,
       privacy) -> { suppressed, percentile, peerMedian, peerCount } using federated/privacy
       (k-anon suppress below k; ε-DP noise on the published median). Never returns a raw cohort.
    2. Re-export from src/federated/index.ts.
    3. Add test/benchmark.test.ts: a subject above the cohort gets a high percentile; a cohort below
       k is suppressed (percentile null); the peer median is noised but bounded.

- id: assurance-dossier
  title: Proof-carrying assurance dossier (underwriter / capital-provider facing)
  material: no
  model: sonnet
  depends: []
  proof: `cd packages/darwin-kernel && node --test --experimental-strip-types test/assuranceDossier.test.ts` exits 0
  prompt: |
    Aggregate the portfolio's verifiable proofs into one offline-verifiable assurance report an
    insurer / capital provider can check to price lower E&O / regulatory capital.
    Steps:
    1. Add src/governance/assuranceDossier.ts: buildAssuranceDossier({ product, receipts[],
       attestations[], evidenceBundles[] }) -> content-addressed digest + counts/coverage stats;
       verifyAssuranceDossier(d) re-verifies every component statelessly (verifyChain /
       verifyAttestation / the evidence-bundle verifier) and reports a coverage score 0..1.
       (If the evidence-bundle module isn't present yet, accept just receipts + attestations.)
    2. Re-export from src/governance/index.ts.
    3. Add test/assuranceDossier.test.ts: a dossier over a valid chain + attestations verifies with
       coverage>0; tampering any component drops it to invalid.

- id: passport-external-acceptance
  title: "Passport accepted here" — external verification SDK + published key set
  material: yes
  model: sonnet
  depends: []
  proof: `cd packages/darwin-kernel && node --test --experimental-strip-types test/passportAcceptance.test.ts` exits 0
  prompt: |
    Make the passport a two-sided network: external partners verify a Darwin passport with only a
    published key set, no call-home.
    Steps:
    1. Add src/passport/acceptance.ts: publishKeySet() -> a JWKS-like list of trusted Ed25519 SPKI
       keys (from env-configured anchors); acceptPassport(passport, keySet, {requiredClaims?}) that
       verifies the passport AND pins its embedded key to the published set AND checks required
       claims/expiry. Reject keys not in the set (foreign-issuer attack).
    2. Re-export from src/passport/index.ts.
    3. Add test/passportAcceptance.test.ts: a passport signed by a published key + required claim is
       accepted; an otherwise-valid passport whose key is NOT in the set is rejected; expired rejected.

- id: multi-tenant-governance
  title: Tenant-scoped constitutions + isolated metered capability access
  material: yes
  model: opus
  depends: []
  proof: `cd packages/darwin-kernel && node --test --experimental-strip-types test/multiTenant.test.ts` exits 0
  prompt: |
    Foundation for offering the governed/metered substrate to EXTERNAL tenants (white-label).
    Steps:
    1. Add src/orchestratorClient/tenancy.ts: a TenantContext { tenantId, constitution,
       allowedCapabilityIds[] }; governForTenant(ctx, action) (uses the tenant's constitution) and
       invokeForTenant(ctx, registry, capabilityId, input) that REFUSES capability ids outside the
       tenant allowlist and tags the usage record with tenantId. No cross-tenant read of receipts/
       usage.
    2. Re-export from the orchestratorClient barrel.
    3. Add test/multiTenant.test.ts: tenant A cannot invoke a capability not in its allowlist; usage
       records carry the right tenantId; tenant A's governance verdict is independent of tenant B's.

- id: orchestrator-as-product-api
  title: Public authenticated API over queue + registry + approvals (eng-org-as-a-service)
  material: yes
  model: opus
  depends: [multi-tenant-governance]
  proof: `cd web && npx vitest run server/api/__tests__/platform.test.ts` exits 0
  prompt: |
    Expose the orchestrator's control surface as a tenant-scoped product API: submit tasks, read
    status, list/decide approval cards, discover capabilities — all gated by TenantContext.
    Steps:
    1. Add web/ Nuxt server routes under /api/platform/* (enqueue task, get task, list approvals,
       decide approval, search capabilities) that authenticate a tenant and enforce
       tenancy.ts allowlists + governForTenant. Reuse the existing Supabase tasks/approvals tables
       with a tenant_id scope (additive column, default the owner tenant).
    2. Add web/server/api/__tests__/platform.test.ts (vitest) covering: a tenant enqueues + reads its
       own task; cannot read another tenant's; a material task creates an approval card.
    NOTE: public API surface — keep in the human-approval lane; do not expose service-role keys.

- id: self-funding-budget-loop
  title: Route realized capability margin into the runner's build-budget allocation
  material: yes
  model: sonnet
  depends: []
  proof: `cd runner && python3 budget_alloc_selftest.py` exits 0
  prompt: |
    Close the loop: high-margin, high-demand capabilities earn more autonomous build budget.
    Steps:
    1. Add runner/budget_alloc.py with a PURE function allocate_budget(base_caps_by_project,
       margins_by_project, total_budget) that tilts each project's monthly cap toward higher
       realized margin (bounded: no project below a floor, none above a ceiling multiple). Read
       margins from the economics ledger export (a JSON the kernel/web can emit).
    2. Wire it into the existing budget-guardrail read in the runner (additive; default to flat
       allocation when no margin data is present).
    3. Add runner/budget_alloc_selftest.py asserting: equal margins -> equal caps; a 3x-margin
       project gets a larger (bounded) cap; total is conserved.

- id: redteam-harness
  title: Permanent cross-product red-team harness (attacks gates, logs receipts)
  material: yes
  model: opus
  depends: []
  proof: `cd packages/darwin-kernel && node --test --experimental-strip-types test/redTeam.test.ts` exits 0
  prompt: |
    A standing adversary that continuously tries to break governance/privacy/capability isolation;
    every attempt is a governed receipt. Findings harden all products.
    Steps:
    1. Add src/security/redTeam.ts: runRedTeam({ constitution, keySet, privacy }) returning a report
       of attack results across a fixed battery: (a) try to make a money_move bypass §1a; (b) submit
       a foreign-issuer passport; (c) request a sub-k federated aggregate; (d) invoke a capability
       outside a tenant allowlist; (e) submit a tampered receipt to a verifier. Each MUST be blocked;
       the report flags any that weren't.
    2. Add test/redTeam.test.ts asserting the battery reports all-blocked against the real kernel
       primitives (a regression guard: if a gate weakens, this test fails).
    NOTE: defensive only — exercises the kernel's own guards; takes no external action.

OPERATOR:
  - Register a `claude-orchestrator` project in the orchestrator projects table (name + repo_path) if intake only knows the app-repo slugs; else route this file manually.
  - orchestrator-as-product-api: add a tenant_id column (default owner) to tasks/approvals before exposing; deploy behind auth; never ship service-role keys to the client.
  - passport-external-acceptance: publish the trusted key set (JWKS) at a stable URL and document the pinning policy for external acceptors.
  - self-funding-budget-loop: have the web/kernel emit the economics-margin JSON the runner reads.
