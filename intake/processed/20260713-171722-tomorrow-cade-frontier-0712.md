PROJECT: tomorrow

# CADE frontier — wire the 10 determination→settlement/capital/assurance levers into the merged
# code. The PURE PRIMITIVES are already built + tested in @darwin/kernel/cade (settlement.ts,
# assurance.ts, loop.ts — 173 kernel tests green). These are ENHANCE tasks: extend the named existing
# module and consume the named kernel export. Nothing rebuilds; all posture-safe.
# Posture (enforced): calc-only, disinterested operator (assertDisinterestedOperator), bilateral ECP,
# anti-CCP/no pool, no novation, no Tomorrow lending/custody, parametric/oracle-attested.
# Repo rules: Prisma migrations name-checked + `npm run lint:migrations`; evaluateConstitution outer gate;
# new sensitive paths added to BOTH materiality classifiers; pure tests via vitest.pure.config.ts.

- id: cadefr-oracle-bridge
  title: Register adversarial CADE determinations as an attested oracle source
  material: yes
  model: opus
  depends: []
  proof: `npx vitest run --config vitest.pure.config.ts server/utils/otc/determination/__tests__/cade-oracle.test.ts` exits 0
  prompt: |
    ENHANCE server/utils/otc/determination/cade.ts + oracles/consensus: import `toOracleReading` from
    @darwin/kernel/cade and register a kernel adversarial-consensus Determination (+ optimality
    certificate + proof digest) as an attested oracle source feeding L1/L2 and deterministicDispute.
    A legal event resolves: adversarial determination → attested reading → deterministic settlement.
    Calc-only, precedent-citing. Test: a CADE reading enters the consensus policy and carries its
    proof digest + confidence. Improvement #1.

- id: cadefr-l0-tier
  title: L0 machine-proved tier above oracle consensus
  material: yes
  model: opus
  depends: [cadefr-oracle-bridge]
  proof: `npx vitest run --config vitest.pure.config.ts server/utils/otc/determination/__tests__/cade-l0.test.ts` exits 0
  prompt: |
    ENHANCE determination/cade.ts level ladder: add an L0 tier that calls `machineCheck` from
    @darwin/kernel/cade; when a question reduces to propositional/deontic obligations and machineCheck
    proves (in)consistency, L0 resolves with the machine proof and ranks ABOVE L1 oracle consensus.
    Test: a contradictory clause set resolves at L0 with a counterexample; a consistent one passes to L1.
    Improvement #2.

- id: cadefr-living-loop
  title: Legal Radar → re-run determinations → re-strike legs → settle
  material: yes
  model: opus
  depends: [cadefr-oracle-bridge]
  proof: `npx vitest run --config vitest.pure.config.ts server/utils/cade/__tests__/living-loop.test.ts` exits 0
  prompt: |
    ENHANCE the Legal-Radar / govParametric path: on a detected authority change, call
    `propagateAuthorityChange` (@darwin/kernel/cade) over stored determinations to compute the affected
    determinations + perpetual legs, then re-run the determinations, re-strike the legs
    (perpetualLegs.reStrikePerpetualLeg), and fire settlement on referencing legal-event contracts.
    Oracle-attested, no discretionary operator action. Test: a simulated authority change re-runs
    exactly the citing determinations + returns the legs to re-strike. Improvement #3.

- id: cadefr-precedent-ratings
  title: Precedent-concentration systemic-risk dimension in riskRatings
  material: no
  model: sonnet
  depends: []
  proof: `npx vitest run --config vitest.pure.config.ts server/utils/otc/riskRatings/__tests__/precedent-concentration.test.ts` exits 0
  prompt: |
    ENHANCE server/utils/otc/riskRatings: add a precedent-concentration dimension using
    `precedentConcentration` (@darwin/kernel/cade) over the book's precedent→contract notional edges
    (HHI + most-exposed precedent). Surface it as a rating input participants can see. Analytics only.
    Test: a book concentrated on one precedent scores high HHI + names it. Improvement #4.

- id: cadefr-challenge-legs
  title: Bilateral challenge legs + market-implied overturn probability
  material: yes
  model: opus
  depends: [cadefr-oracle-bridge]
  proof: `npx vitest run --config vitest.pure.config.ts server/utils/cade/__tests__/challenge-legs.test.ts` exits 0
  prompt: |
    Add a bilateral ECP event-swap ("challenge leg", allowlisted binary_event_swap) that pays if a
    determination is overturned; feed the book of challenge legs through `impliedOverturnProbability`
    (@darwin/kernel/cade) to produce a money-weighted confidence prior into the oracle/dispute engine.
    ECP-gated, bilateral, operator never a side (assertDisinterestedOperator). Test: challenge legs
    shift the implied overturn probability; non-ECP is blocked. Improvement #5.

- id: cadefr-reliability-loop
  title: Outcome → oracle-source / calc-agent reliability calibration
  material: yes
  model: sonnet
  depends: [cadefr-oracle-bridge]
  proof: `npx vitest run --config vitest.pure.config.ts server/utils/cade/__tests__/reliability.test.ts` exits 0
  prompt: |
    On a realized settlement/overturn outcome, update oracle-source + calc-agent-bot reliability via
    `updateReliabilityFromOutcome` (@darwin/kernel/cade), persisted through the credit/reputation store;
    reliability feeds future source weighting + panel selection. Test: an overturn lowers the implicated
    source's reliability; a correct outcome raises it. Improvement #6.

- id: cadefr-event-compression
  title: Legal-event exposure compression (named bilateral, anti-CCP)
  material: yes
  model: sonnet
  depends: []
  proof: `npx vitest run --config vitest.pure.config.ts server/utils/otc/__tests__/event-compression.test.ts` exits 0
  prompt: |
    ENHANCE compressionEngine / networkNetting: use `proposeEventCompression` (@darwin/kernel/cade) to
    match opposing legal-event positions into NAMED BILATERAL offset legs (A↔B) — never a pool/CCP —
    reducing gross legal-event notional. Test: offsetting positions compress into bilateral legs with a
    correct residual. Improvement #7.

- id: cadefr-margin-haircut
  title: Certified determination → lower IM haircut in the margin optimizer
  material: yes
  model: sonnet
  depends: [cadefr-oracle-bridge]
  proof: `npx vitest run --config vitest.pure.config.ts server/utils/otc/marginOptimizer/__tests__/certainty-haircut.test.ts` exits 0
  prompt: |
    ENHANCE marginOptimizer: read a CADE optimality certificate via `marginHaircutMultiplier`
    (@darwin/kernel/cade) so a warranted determination lowers the IM haircut on a participant's other
    bilateral positions (certified enforceability ⇒ less collateral). Tomorrow computes only; never
    holds/lends. Test: higher certified confidence yields a lower (floor-bounded) haircut multiplier.
    Improvement #8.

- id: cadefr-instrument-gaps
  title: Dispute → instrument-gap mining into the foundry
  material: no
  model: sonnet
  depends: []
  proof: `npx vitest run --config vitest.pure.config.ts server/utils/otc/__tests__/instrument-gaps.test.ts` exits 0
  prompt: |
    ENHANCE rfqGapMiner / instrumentFoundry intake: use `mineInstrumentGaps` (@darwin/kernel/cade) over
    realized legal-event losses vs existing instrument coverage to propose ranked candidate parametric
    legal-event instruments. Proposals only (live mint stays human/allowlist-gated). Test: an unhedged
    recurring loss surfaces the top-ranked candidate spec. Improvement #9.

- id: cadefr-certified-raas
  title: Certified-determination RaaS tier on the metered bridge
  material: no
  model: sonnet
  depends: [cadefr-oracle-bridge]
  proof: `npx vitest run --config vitest.pure.config.ts server/utils/otc/raas/__tests__/certified-tier.test.ts` exits 0
  prompt: |
    ENHANCE otc/raas/bridge.ts: add a "certified determination" service tier priced via
    `priceDeterminationService` (@darwin/kernel/cade) by difficulty/tier, returning the signed optimality
    certificate. Calc-only, never custody, never an order (unchanged posture). Test: the certified tier
    prices above oracle tier and flags certificate inclusion. Improvement #10.

OPERATOR:
  - Add server/utils/cade/ + otc/determination/ new CADE paths to BOTH materiality classifiers.
  - Counsel confirm: challenge legs + legal-event compression stay bilateral ECP parametric swaps within SWAP_ONLY_MODE (not insurance, not novation); operator remains disinterested.
  - Live-money settlement on the oracle-bridged legal events remains operator/counsel-gated (ref-only until then).
