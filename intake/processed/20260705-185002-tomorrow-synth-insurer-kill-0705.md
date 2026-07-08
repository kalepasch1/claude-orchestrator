PROJECT: tomorrow

# Synthetic insurer-displacement, strictly within the OTC institutional-swap model: every
# structure is a bilateral ECP swap (§2(h)(7)), parametric-only (assertParametricOnly), no new
# entity, no partnership, no custody. Builds on existing Risk Studio (displacement engine,
# parametric families, basisOptimizer), the risk fabric, marginOptimizer (Z3), capital
# recognition (D3), and the kernel's proof-reduction (captive-risk-quantification). Where a
# joining insurer is involved, it participates ONLY as an ordinary ECP counterparty via an
# embed — never a partnership/commitment. Do NOT duplicate the tomorrow-mutual-synth or
# tomorrow-secondwave waves; these are distinct deltas.

- id: sik-contracts
  title: Shared types + API stubs for synthetic insurer-displacement
  material: no
  model: sonnet
  depends: []
  proof: `npx vitest run server/utils/otc/replication/__tests__/contracts.test.ts` exits 0
  prompt: |
    Add server/utils/otc/replication/types.ts (ReplicatedPolicy, PerilLeg, BasisReport,
    RetentionPlan, InsurerAppetite, CapitalReliefAttestation) and thin API stubs under
    server/api/otc/replication/* returning 501 until wired. Pure types + route scaffolding only.
    Proof: contracts.test.ts imports the types and asserts the stubs return 501.

- id: sik-policy-replication-compiler
  title: Policy → replicating parametric swap basket (the direct insurer-kill)
  material: yes
  model: opus
  depends: [sik-contracts]
  proof: `npx vitest run server/utils/otc/replication/__tests__/policyReplication.test.ts` exits 0
  prompt: |
    Compile an EXISTING insurance policy into the equivalent bilateral ECP parametric swap so the
    institutional client drops the carrier. No indemnity, no partnership.
    Steps:
    1. server/utils/otc/replication/policyReplicationCompiler.ts: compileReplication(policy) where
       policy = parsed declarations/coverage (perils, limits, retentions, exclusions) — reuse the
       Document-Intake extraction if a doc is supplied. Map each covered peril to a parametric
       trigger from the existing families (Risk Studio families + basisOptimizer). Emit a
       ReplicatedPolicy: swap basket legs + residual BasisReport + cost-of-capital premium vs the
       policy's loaded premium. Enforce assertParametricOnly + ECP gate.
    2. Proof policyReplication.test.ts: a sample multi-peril policy yields a basket whose modeled
       payoff tracks the policy within a stated basis tolerance; replication premium < loaded carrier
       premium; a request to indemnify actual loss is refused by assertParametricOnly.

- id: sik-basis-warranty
  title: Basis-backstop swap (removes the #1 objection to parametric)
  material: yes
  model: opus
  depends: [sik-contracts]
  proof: `npx vitest run server/utils/otc/replication/__tests__/basisWarranty.test.ts` exits 0
  prompt: |
    Make synthetic parametric economically indistinguishable from indemnity for the client while
    staying swap-only: a second bilateral parametric leg that pays the residual basis of the primary
    parametric hedge (a hedge on the hedge), priced off the BasisReport.
    Steps:
    1. server/utils/otc/replication/basisWarranty.ts: structureBasisWarranty(replicated, tolerance)
       -> a parametric swap leg keyed to a SECONDARY observable (loss-proxy index), never actual
       loss, that pays when realized basis exceeds tolerance. assertParametricOnly + dual-trigger so
       it can never settle on indemnified actual loss.
    2. Proof basisWarranty.test.ts: the warranty leg reduces client residual basis below tolerance in
       the modeled paths; it fires on the secondary index, not actual loss; assertParametricOnly holds.

- id: sik-assurance-discounted-margin
  title: Compliance-as-collateral — verified dossier lowers bilateral IM (no partnership)
  material: yes
  model: sonnet
  depends: [sik-contracts]
  proof: `npx vitest run server/utils/otc/margin/__tests__/assuranceDiscount.test.ts` exits 0
  prompt: |
    A pure bilateral CSA term: reduce a counterparty's initial margin / haircut when they post a
    verified assurance dossier (lower operational risk => lower margin). Meshes the kernel proof-
    reduction with Tomorrow's marginOptimizer — no third party.
    Steps:
    1. server/utils/otc/margin/assuranceDiscount.ts: assuranceDiscountedIM(baseIM, dossier) that
       verifies the dossier (or accepts a riskReductionFactor 0..1) and applies a BOUNDED reduction
       (floor so IM never collapses). Unverified/tampered dossier => zero discount.
    2. Proof assuranceDiscount.test.ts: a verified high-coverage dossier lowers IM within [floor, base];
       tampered => zero discount; monotonic in coverage.

- id: sik-optimal-retention-ledger
  title: Synthetic self-insurance — optimal retention vs transfer over the fabric (no entity)
  material: yes
  model: sonnet
  depends: [sik-contracts]
  proof: `npx vitest run server/utils/otc/replication/__tests__/retention.test.ts` exits 0
  prompt: |
    The "captive" as an ACCOUNTING VIEW, not an entity: the book proves down its own risk and lays
    off only the residual as bilateral parametric swaps via the existing fabric.
    Steps:
    1. server/utils/otc/replication/retention.ts: computeOptimalRetention({exposure, baselineLossRate,
       riskReductionFactor, riskAppetite}) -> RetentionPlan { retainedUsd, transferUsd, residualTail }
       where higher proof-reduction increases optimal retention and shrinks transfer; route residual
       to fabric parametric legs (reuse riskFabric + marginalRisk). No funds, no entity.
    2. Proof retention.test.ts: higher riskReductionFactor => more retained + smaller transfer notional
       (monotonic); the residual tail is covered by the structured parametric legs; factor 0 => full
       transfer.

- id: sik-insurer-capacity-embed
  title: One-file embed so a joining insurer writes synthetic reinsurance as an ECP counterparty
  material: yes
  model: opus
  depends: [sik-contracts]
  proof: `npx vitest run server/utils/otc/capacity/__tests__/insurerEmbed.test.ts` exits 0
  prompt: |
    The "if we can't kill them, give joiners a 1000X-easy advantage": an insurer/reinsurer (already an
    ECP) posts appetite and instantly receives pre-structured bilateral parametric swaps replicating
    the reinsurance they'd write, plus a capital-relief attestation — zero partnership, just ISDA/ECP.
    Reuse capacityRegistry + syntheticSellerMinter + D3 capital recognition; do NOT create an entity.
    Steps:
    1. server/utils/otc/capacity/insurerCapacityEmbed.ts: onboardInsurerCapacity(appetite:
       InsurerAppetite {peril, region, capacityUsd, minSpreadBp}) -> matched pre-structured parametric
       swaps within appetite + a signed CapitalReliefAttestation (via D3). ECP gate: refuse non-ECP.
    2. Proof insurerEmbed.test.ts: an ECP insurer posting appetite receives >=1 matched parametric swap
       within capacity + a verifiable capital-relief attestation; a non-ECP is refused.

- id: sik-verification
  title: Synthetic insurer-displacement full-suite verification + report
  material: no
  model: sonnet
  depends: [sik-policy-replication-compiler, sik-basis-warranty, sik-assurance-discounted-margin, sik-optimal-retention-ledger, sik-insurer-capacity-embed]
  proof: `npx vitest run server/utils/otc/replication server/utils/otc/margin server/utils/otc/capacity` exits 0
  prompt: |
    Run the full slice, assert posture invariants hold across it (assertParametricOnly on every
    replicating/warranty/embed structure; ECP gate on every counterparty; no indemnity path; no new
    entity/custody), and emit a short REPLICATION_VERIFICATION.md summarizing coverage + any residual
    basis. Proof: the three suites are green together.

OPERATOR:
  - Counsel review of the policy-replication characterization + basis-warranty dual-trigger before any client use (advisory/structuring only until then).
  - No partnerships required: a joining insurer signs the standard ECP/ISDA onboarding and uses the embed as a counterparty; nothing here creates a JV, MGA, or carrier relationship.
