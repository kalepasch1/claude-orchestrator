PROJECT: tomorrow

# CADE frontier-2 — interoperability, federation, finality, capital, doctrine.
# PURE PRIMITIVES already built + tested in @darwin/kernel/cade (credential.ts, federation.ts,
# finality.ts, capital.ts, doctrine.ts — 181 kernel tests green). These are ENHANCE tasks: extend the
# named existing module and consume the named kernel export. Nothing rebuilds; all posture-safe.
# Posture (enforced): calc-only, disinterested operator, bilateral ECP, anti-CCP, no novation,
# no Tomorrow lending/custody, parametric/oracle-attested.
# Repo rules: Prisma migrations name-checked + `npm run lint:migrations`; evaluateConstitution outer
# gate; new sensitive paths in BOTH materiality classifiers; pure tests via vitest.pure.config.ts.

- id: cadefr2-cdm-credential
  title: CDM type for the portable determination credential (interop standard)
  material: no
  model: sonnet
  depends: []
  proof: `npx vitest run --config vitest.pure.config.ts server/utils/otc/legalInfra/__tests__/cdm-credential.test.ts` exits 0
  prompt: |
    ENHANCE server/utils/otc/legalInfra/cdm.ts: add a Common-Domain-Model type for a determination
    credential and (de)serializers that wrap `toDeterminationCredential` / `verifyDeterminationCredential`
    (@darwin/kernel/cade), so any external venue/counterparty can consume + verify a Tomorrow
    determination natively. Test: round-trip serialize→verify passes; tamper fails. Improvement #1/#9.

- id: cadefr2-passport-accept
  title: Accept a cross-app determination credential at settlement
  material: yes
  model: sonnet
  depends: [cadefr2-cdm-credential]
  proof: `npx vitest run --config vitest.pure.config.ts server/utils/otc/determination/__tests__/credential-accept.test.ts` exits 0
  prompt: |
    ENHANCE determination/cade.ts: accept a verified determination credential (e.g. issued by
    Apparently) as an attested input via `verifyDeterminationCredential`; a credential that fails
    verification is rejected. One determination, reused across apps (kernel passport). Test: a valid
    credential is accepted as a source; a tampered one is rejected. Improvement #9.

- id: cadefr2-marketplace-templates
  title: List reusable determination templates on the strategy marketplace
  material: no
  model: sonnet
  depends: [cadefr2-cdm-credential]
  proof: `npx vitest run --config vitest.pure.config.ts server/utils/otc/strategyMarketplace/__tests__/determination-templates.test.ts` exits 0
  prompt: |
    ENHANCE strategyMarketplace: list certified determination templates and, on a new issue, use
    `matchTemplate` + `determinationSignature` (@darwin/kernel/cade) to reuse a template instead of
    re-running. Test: a similar-signature issue reuses a template; a dissimilar one does not. Improvement #2.

- id: cadefr2-federated-determination
  title: Federated determination across participant nodes (privacy-preserved)
  material: yes
  model: opus
  depends: []
  proof: `npx vitest run --config vitest.pure.config.ts server/utils/otc/federation/__tests__/federated-determination.test.ts` exits 0
  prompt: |
    ENHANCE server/utils/otc/federation: aggregate participant nodes' LOCAL determinations via
    `federatedDetermination` (@darwin/kernel/cade) with k-anon suppression (no raw data crosses a node
    boundary) into one more-authoritative consensus. Test: sub-k cohorts are suppressed; the blend
    weights by confidence. Improvement #3.

- id: cadefr2-adversarial-oracle
  title: Adversarial oracle screening before consensus admission
  material: yes
  model: opus
  depends: []
  proof: `npx vitest run --config vitest.pure.config.ts server/utils/otc/determination/__tests__/adversarial-oracle.test.ts` exits 0
  prompt: |
    ENHANCE oracles/consensus + deterministicDispute: screen oracle sources via `screenOracleSources`
    (@darwin/kernel/cade) — reject stale, statistical-outlier, and colluding/over-represented sources
    before they enter settlement consensus. Test: stale/outlier/collusion sources are rejected with
    reasons; clean sources admitted. Improvement #6.

- id: cadefr2-finality-netting
  title: Determination-finality netting over the precedent DAG
  material: yes
  model: opus
  depends: []
  proof: `npx vitest run --config vitest.pure.config.ts server/utils/otc/determination/__tests__/finality-netting.test.ts` exits 0
  prompt: |
    ENHANCE determination/cade.ts: use `propagateFinality` (@darwin/kernel/cade) so a determination
    whose dependencies are all final inherits finality — settled sub-questions are never re-litigated;
    cycles are flagged, not auto-finalized. Test: finality cascades through the DAG; a cycle is flagged.
    Improvement #4.

- id: cadefr2-precedent-pricing
  title: Precedent-weighted spread input to the pricing oracle
  material: yes
  model: sonnet
  depends: []
  proof: `npx vitest run --config vitest.pure.config.ts server/utils/otc/pricingOracle/__tests__/precedent-spread.test.ts` exits 0
  prompt: |
    ENHANCE pricingOracle: widen the spread via `precedentPricingAdjustmentBps` (@darwin/kernel/cade)
    using the precedent-concentration HHI (from cadefr-precedent-ratings) and source reliability, so
    instruments referencing fragile/over-concentrated precedents price wider automatically. Test: a
    fragile precedent yields a wider spread than a safe one. Improvement #5.

- id: cadefr2-capital-optimization
  title: Determination-driven capital optimization in the margin/capital stack
  material: yes
  model: opus
  depends: []
  proof: `npx vitest run --config vitest.pure.config.ts server/utils/otc/capitalLiberation/__tests__/determination-capital.test.ts` exits 0
  prompt: |
    ENHANCE regulatoryCapital / capitalLiberation / marginOptimizer: use `optimizeCapitalTreatment`
    (@darwin/kernel/cade) with the certified haircut multipliers (from cadefr-margin-haircut) to compute
    freed initial margin under the regime. Advisory calc only; Tomorrow never holds/lends. Test: lower
    certified haircut frees more margin, deterministically. Improvement #7.

- id: cadefr2-doctrine-loop
  title: Self-closing dispute → doctrine loop into the self-improvement runner
  material: no
  model: sonnet
  depends: []
  proof: `npx vitest run --config vitest.pure.config.ts server/utils/cade/__tests__/doctrine-loop.test.ts` exits 0
  prompt: |
    ENHANCE the Tomorrow self-improvement runner: feed realized determination overturn outcomes through
    `mineDoctrineUpdates` (@darwin/kernel/cade) and auto-queue the ranked roster/prompt/doctrine
    proposals (non-divergent → auto, material → human-gated). Test: a high-overturn pattern produces a
    ranked proposal; a healthy pattern does not. Improvement #8.

OPERATOR:
  - Add server/utils/otc/federation + determination + cade paths to BOTH materiality classifiers.
  - Counsel confirm federated determination stays privacy-preserved (k-anon/ε-DP, no raw cross-firm data) and that credential acceptance does not create reliance/authorized-practice issues.
  - Cross-app adoption: Apparently/smarter/Pareto issue determination credentials via @darwin/kernel/cade (toDeterminationCredential) — fan out via the existing darwin-kernel adoption pattern.
  - The doctrine-loop mirror on the orchestrator improvement_miner (Python) is a separate claude-orchestrator task (no project enum slot).
