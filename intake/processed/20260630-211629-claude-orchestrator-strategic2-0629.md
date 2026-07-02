PROJECT: claude-orchestrator

# Strategic wave 2. New modules in packages/darwin-kernel (pure, additive, node:test) + a
# read-only web verifier route. Keep the kernel suite green after each:
#   cd packages/darwin-kernel && node --test --experimental-strip-types test/*.test.ts
# Prerequisite modules referenced (already queued/built): governance (compiler, policyService,
# receipts, projection), passport (+acceptance), attestation, federated, orchestratorClient
# (registry, metering, economics), identity. Cross-file deps are NOT hard-wired here — where a
# task references another wave's module, code defensively (feature-detect / accept a subset).

- id: a2a-market-ecp-safe
  title: Governed agent-to-agent risk-transfer market with a hard ECP bright line
  material: yes
  model: opus
  depends: []
  proof: `cd packages/darwin-kernel && node --test --experimental-strip-types test/a2aMarket.test.ts` exits 0
  prompt: |
    Let product agents transact risk transfer under governance + metering, but ENFORCE the CEA
    §2(h)(7) bright line: a non-ECP subject (e.g. a Pareto retail client) can NEVER be a counterparty
    to a bilateral OTC swap. Retail requests must be rerouted to a retail-safe fulfillment; the swap,
    if any, stays ECP↔ECP (carrier/issuer level), with the consumer receiving a FEATURE not a swap.
    Steps:
    1. Add src/orchestratorClient/a2aMarket.ts: requestRiskTransfer({ requesterSubject, passports,
       consent, exposure, registry, constitution }) ->
         - check ecp_eligible on the requester's verified passport (passport/acceptance + hasClaim).
         - if ECP: route to a bilateral swap capability (e.g. tomorrow:price_swap / fabric_run),
           governed + metered, returning a swap leg.
         - if NOT ECP: REFUSE the swap path and route to a retail-safe capability
           (tomorrow:parametric_displacement or a carrier-fronting fulfillment) returning a
           {consumerFeature, swapStaysAtCarrier:true} result. Never emit a swap leg with a
           non-ECP counterparty.
       Every route runs through governAction; denied routes are blocked.
    2. Re-export from the orchestratorClient barrel.
    3. Add test/a2aMarket.test.ts: an ECP requester gets a swap leg; a non-ECP requester (no
       ecp_eligible claim) gets a consumerFeature and NO swap leg with them as counterparty;
       a denied action is blocked. This test is the regulatory regression guard.

- id: multi-domain-risk-harness
  title: Cross-domain risk-score harness over the canonical ledger (model pluggable)
  material: yes
  model: opus
  depends: []
  proof: `cd packages/darwin-kernel && node --test --experimental-strip-types test/multiDomainRisk.test.ts` exits 0
  prompt: |
    Build the feature + scoring harness for a single risk score that sees banking + gaming +
    insurance + legal + consumer-finance signals on one subject. Training is offline/OPERATOR; the
    kernel ships the deterministic feature assembly + a pluggable scorer + a golden-set eval.
    Steps:
    1. Add src/risk/multiDomainScore.ts: buildFeatureVector({ subject, unifiedPositions, receipts,
       passportClaims }) -> a normalized numeric vector with named features (leverage, settlement
       reliability, KYC depth, counterparty concentration, behavioral volatility). scoreSubject(vec,
       model) where model is an injected fn (default: a documented linear baseline). evalGolden(cases,
       model) -> AUC-like accuracy.
    2. Re-export via a new src/risk/index.ts (add to package exports map).
    3. Add test/multiDomainRisk.test.ts: feature vector is deterministic + bounded [0,1]; the linear
       baseline ranks a high-risk synthetic subject above a low-risk one; evalGolden returns a number.

- id: cross-product-fraud-graph
  title: Shared fraud/AML signal graph keyed on the identity graph
  material: yes
  model: opus
  depends: []
  proof: `cd packages/darwin-kernel && node --test --experimental-strip-types test/fraudGraph.test.ts` exits 0
  prompt: |
    Fuse cross-product signals (Galop KYC, Smarter reliability, Tomorrow counterparty credit, Pareto
    account) into one fraud graph that flags patterns no single product can see.
    Steps:
    1. Add src/risk/fraudGraph.ts: buildFraudGraph({ identities, edges, signals[] }) and
       detectRings(graph) -> suspicious clusters (shared-device / synthetic-identity / circular-flow
       heuristics over the identity edges + signal anomalies). flagSubject(graph, subject) -> a 0..1
       risk with cited contributing edges.
    2. Re-export from src/risk/index.ts.
    3. Add test/fraudGraph.test.ts: a synthetic ring (3 subjects sharing a device + circular flow) is
       detected; an isolated clean subject scores low.

- id: zk-threshold-claims
  title: Zero-knowledge-style threshold claims on the passport (value hidden)
  material: yes
  model: opus
  depends: []
  proof: `cd packages/darwin-kernel && node --test --experimental-strip-types test/zkClaims.test.ts` exits 0
  prompt: |
    Let a passport prove "ecp_eligible", "net worth > X", or "age >= 18" WITHOUT revealing the raw
    value. Ship the claim shape + verification interface with a commitment-based default; a real ZK
    backend (bulletproofs/groth16) is a documented pluggable swap.
    Steps:
    1. Add src/passport/zkClaims.ts: buildThresholdClaim({ kind, threshold, value, issuer }) that
       stores a salted commitment + a signed assertion value>=threshold but NEVER serializes the raw
       value; verifyThresholdClaim(claim) checks the signature + that the asserted predicate holds and
       that no raw value is present. Define a ZkBackend interface for a real range-proof implementation.
    2. Re-export from src/passport/index.ts.
    3. Add test/zkClaims.test.ts: a claim for value=5M, threshold=1M verifies true; the serialized
       claim does NOT contain the raw value 5_000_000; a forged threshold (value<threshold) fails.

- id: constitution-formal-invariants
  title: Formal invariant / reachability proofs over a constitution
  material: no
  model: sonnet
  depends: []
  proof: `cd packages/darwin-kernel && node --test --experimental-strip-types test/invariants.test.ts` exits 0
  prompt: |
    Prove a rule-set can never reach a forbidden state (e.g. money_move reachable without escalation;
    a locked dimension allowable). Property-based over the action space; a documented SMT hook for a
    full solver later.
    Steps:
    1. Add src/governance/invariants.ts: checkInvariants(constitution, { forbidden: AgentAction
       predicates[], sampleSpace }) that fuzzes many sampled actions through evaluateConstitution and
       asserts no forbidden state is ever 'allow'; returns { holds, counterexample? }.
    2. Re-export from src/governance/index.ts.
    3. Add test/invariants.test.ts: a sound constitution passes (holds=true); a constitution that
       allows a locked dimension yields holds=false with a counterexample.

- id: constitution-marketplace
  title: Signed, installable constitution templates (governance marketplace)
  material: yes
  model: sonnet
  depends: []
  proof: `cd packages/darwin-kernel && node --test --experimental-strip-types test/constitutionMarket.test.ts` exits 0
  prompt: |
    Make ratified constitutions forkable assets: publish a signed template (PTRRS, COPPA, Reg-W,
    sweepstakes) that any firm installs and inherits provable enforcement.
    Steps:
    1. Add src/governance/constitutionMarket.ts: publishTemplate({ name, jurisdiction, text,
       lockedDimensions, issuer }) -> a signed, content-addressed template (compiles via the NL
       compiler, attaches an attestation); installTemplate(template, { overrides? }) -> a Constitution,
       verifyTemplate(template) stateless. Installs must re-assert locked dimensions (cannot be
       loosened by overrides).
    2. Re-export from src/governance/index.ts.
    3. Add test/constitutionMarket.test.ts: publish+verify a template; install yields an enforcing
       constitution; an override attempting to allow a locked dimension is rejected.

- id: capability-futures-sla
  title: Prepaid capability credits + SLA/circuit-breaker layer over metering
  material: yes
  model: sonnet
  depends: []
  proof: `cd packages/darwin-kernel && node --test --experimental-strip-types test/capabilityFutures.test.ts` exits 0
  prompt: |
    Turn the metered internal API economy into a contractual external platform: prepaid credit pools
    + per-capability SLA with a circuit breaker.
    Steps:
    1. Add src/orchestratorClient/capabilityFutures.ts: a CreditPool (deposit, debitOnUsage from a
       UsageRecord, balance, refuse when exhausted) and an SLA tracker (rolling success/latency; a
       3-state circuit breaker that opens on breach and half-opens after a window).
    2. Re-export from the orchestratorClient barrel.
    3. Add test/capabilityFutures.test.ts: a pool debits per usage and refuses when empty; the breaker
       opens after N failures and half-opens after the window.

- id: counterfactual-constitution-replay
  title: Replay the recorded action stream under a candidate constitution
  material: no
  model: sonnet
  depends: []
  proof: `cd packages/darwin-kernel && node --test --experimental-strip-types test/counterfactualReplay.test.ts` exits 0
  prompt: |
    "What if the constitution had been X over the last 90 days?" Re-evaluate recorded receipts'
    actions under a candidate policy and report decision deltas before ratifying.
    Steps:
    1. Add src/governance/counterfactual.ts: replayUnderConstitution(receipts, candidateConstitution)
       -> { total, deltas: { allowToEscalate, allowToDeny, escalateToAllow, ... }, examples[] } by
       re-running evaluateConstitution on each receipt.action.
    2. Re-export from src/governance/index.ts.
    3. Add test/counterfactualReplay.test.ts: a stricter candidate flips some recorded allows to
       escalate and the counts are correct.

- id: captive-risk-quantification
  title: Quantify proof-backed risk reduction from assurance dossiers (captive input)
  material: no
  model: sonnet
  depends: []
  proof: `cd packages/darwin-kernel && node --test --experimental-strip-types test/riskReduction.test.ts` exits 0
  prompt: |
    Turn proof coverage into a number a captive/insurer can price against.
    Steps:
    1. Add src/governance/riskReduction.ts: quantifyRiskReduction({ receiptsCoverage, attestations
       coverage, invariantsHold, dossierVerified }) -> a factor 0..1 (and a short rationale) where
       fully-verified + invariants-holding approaches the max and any unverified component caps it low.
    2. Re-export from src/governance/index.ts.
    3. Add test/riskReduction.test.ts: full coverage + invariants hold -> high factor; a tampered/
       unverified dossier -> near-zero; monotonic in coverage.

- id: living-compliance-pipeline
  title: Auto-recompile + re-attest a constitution on a regulatory-change signal
  material: yes
  model: opus
  depends: []
  proof: `cd packages/darwin-kernel && node --test --experimental-strip-types test/livingCompliance.test.ts` exits 0
  prompt: |
    When the law changes, recompile the affected constitution, diff it, and emit a re-ratification
    PROPOSAL + a signed change attestation — never auto-ratify (respect the cooling-off gate).
    Steps:
    1. Add src/governance/livingCompliance.ts: applyRegulatoryChange({ currentText, change, product })
       -> recompiles via the NL compiler, computes a rule diff (added/removed/changed), and returns
       { proposedConstitution, diff, changeAttestation } where changeAttestation is a signed
       attestation of the diff. Mark proposals that touch locked dimensions as requiresHumanRatify.
    2. Re-export from src/governance/index.ts.
    3. Add test/livingCompliance.test.ts: a change that tightens a cap produces a proposed constitution
       with the new cap, a non-empty diff, and a verifiable change attestation; nothing is ratified
       automatically.

- id: regulator-verifiable-portal
  title: Read-only public verifier portal (receipts / dossiers / proofs)
  material: yes
  model: sonnet
  depends: []
  proof: `cd web && npx vitest run server/api/__tests__/regulator.test.ts` exits 0
  prompt: |
    Give a regulator/auditor a live, self-serve, independently-verifiable view — keyless verification
    (only the embedded public key is needed).
    Steps:
    1. Add web/ Nuxt read-only server routes /api/regulator/verify (paste an envelope -> {valid,reason})
       and /api/regulator/dossier/[id] (fetch + verify a stored assurance dossier). No secrets, no
       writes, rate-limited.
    2. Add web/server/api/__tests__/regulator.test.ts (vitest): a valid envelope verifies; a tampered
       one is rejected; the route never returns service-role data.

OPERATOR:
  - Register a `claude-orchestrator` project (name + repo_path) in the orchestrator projects table if intake only knows the app slugs; else route this file manually.
  - multi-domain-risk-harness: the production scorer is trained offline on the canonical ledger (GPU/eval pipeline) and injected; the kernel ships only the harness + baseline.
  - zk-threshold-claims: swap the commitment default for a real range-proof backend (bulletproofs/groth16) before relying on it for privacy guarantees.
  - regulator-verifiable-portal: deploy behind read-only auth + rate limiting; publish the trusted key set (JWKS) so verification is keyless for third parties.
