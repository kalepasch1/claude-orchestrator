PROJECT: tomorrow

# Synthetic Mutuals, Group-ECP Hedging, and Synthetic Packaging.
# Strategy/context: tomorrow repo SYNTHETIC_MUTUAL_ECP_AND_PACKAGING.md (READ IT — esp. sections 2, 3, 6).
# COMPOSE existing production primitives; do NOT rebuild: otc/ecp/ecpDetermination.ts, mutualEligibility.ts,
# guarantorMarketplace.ts, pool/poolMatchingRound.ts, synthInsurance/{types,characterization,indexOracle,
# indexSpecStore, moat/riskOntology}.ts, HedgeBundle, perpetualGenerator.ts, perpetualOptions/mint.ts,
# perpetualPricing.ts, compressionEngine.ts, proof/verifiableProof.ts, ScoOverlayFacility/ScoReserveMandate.
# INVARIANT: UNMARGINED. Swap layer is ECP<->ECP with no platform margin. A co-op's member-contribution pool is
# the co-op's OWN reserve, not platform margin. Exposure is scaled via notional + funding-rate, never collateral.
# LEGAL: build the plumbing; GO-LIVE is counsel-gated (see OPERATOR). Nothing member-facing ships without it.

- id: ms-contracts
  title: Shared types + schema + API stubs for mutual/co-op + synthetic packaging
  material: yes
  model: opus
  depends: []
  proof: `npx tsc --noEmit` exits 0 AND `npx prisma validate` exits 0
  prompt: |
    Contracts ONLY (types, Prisma schema, API stubs) per SYNTHETIC_MUTUAL_ECP_AND_PACKAGING.md.
    - server/utils/otc/mutual/mutualTypes.ts (NEW): MutualEntity, MutualMember, MemberContribution,
      MemberDistribution, EcpQualificationPath, SyntheticUnderlying, SyntheticBasket, BasketPerpetualSpec,
      VerifiedHedgedNote, NoteTranche.
    - prisma/schema.prisma: ADD MutualEntity, MutualMember, MemberContribution, MemberDistribution,
      SyntheticUnderlying, SyntheticBasket, VerifiedHedgedNote, NoteTranche. Generate migration; DO NOT apply.
    - 501 API stubs: server/api/otc/mutual/create.post.ts, .../qualify.post.ts, server/api/otc/basket/create.post.ts,
      server/api/otc/note/issue.post.ts.
    No business logic.

- id: ms-mutual-entity
  title: Mutual/co-op entity that aggregates members and is the ECP counterparty
  material: yes
  model: opus
  depends: [ms-contracts]
  proof: `npx vitest run mutualEntity` exits 0
  prompt: |
    server/utils/otc/mutual/mutualEntity.ts (NEW): a MutualEntity aggregates MutualMembers, holds a member-
    contribution reserve (the co-op's OWN pool — not platform margin), and acts as the single swap counterparty.
    Distributions to members are pro-rata, PARAMETRIC (index-triggered), never indemnity for actual loss. Reuse
    ecp/* for the entity's ECP status. Test mutualEntity.test.ts: contributions accrue to the reserve; a parametric
    trigger produces pro-rata member distributions; no member is ever a swap counterparty.

- id: ms-ecp-qualification-wizard
  title: Group ECP-qualification flow (>$1M hedging-entity / >$10M assets / pool+CPO / guarantor)
  material: yes
  model: opus
  depends: [ms-contracts]
  proof: `npx vitest run ecpQualification` exits 0
  prompt: |
    server/utils/otc/mutual/ecpQualification.ts (NEW): given a forming group, evaluate the CEA doors via
    server/utils/otc/ecp/ecpDetermination.ts — hedging-entity prong (>$1M net worth managing members' risk),
    total-assets prong (>$10M), commodity-pool prong (>$5M + CPO), and ECP guarantor via guarantorMarketplace.ts —
    and return the simplest qualifying path + a verifiableProof ECP credential for the entity. Test
    ecpQualification.test.ts: a >$1M hedging co-op qualifies via the hedging-entity door; a sub-threshold group
    qualifies only with a guarantor; a group with no path returns not_ecp with structuring guidance.

- id: ms-synthetic-underlyings
  title: Composable synthetic underlyings + weighted baskets registry
  material: yes
  model: opus
  depends: [ms-contracts]
  proof: `npx vitest run syntheticUnderlyings` exits 0
  prompt: |
    server/utils/otc/mutual/syntheticUnderlyings.ts (NEW): extend synthInsurance/moat/riskOntology.ts +
    indexSpecStore.ts so single parametric indices compose into weighted SyntheticBaskets that are themselves
    tradeable references. Compute basket variance with a correlation matrix (NOT naive independence). Test: a basket
    of uncorrelated components has lower variance than any component; correlated components reduce diversification.

- id: ms-basket-perpetuals
  title: Basket perpetual protection with diversification-aware variance pricing
  material: yes
  model: opus
  depends: [ms-contracts, ms-synthetic-underlyings]
  proof: `npx vitest run basketPerpetuals` exits 0
  prompt: |
    server/utils/otc/mutual/basketPerpetuals.ts (NEW): compose HedgeBundle + perpetualGenerator.ts +
    perpetualOptions/mint.ts + perpetualPricing.ts into perpetual protection on a SyntheticBasket, priced with
    correlation-aware variance and funding-rate. Exposure scales via notional + funding-rate (UNMARGINED — no
    collateral). Test basketPerpetuals.test.ts: writing a diversified basket yields a lower premium-per-unit-residual
    than writing the riskiest single component; scaling notional scales exposure linearly.

- id: ms-micro-hedge-access
  title: Co-op-mediated member access to micro parametric hedges (without the retail block)
  material: yes
  model: opus
  depends: [ms-contracts, ms-mutual-entity]
  proof: `npx vitest run microHedgeAccess` exits 0
  prompt: |
    server/utils/otc/mutual/microHedgeAccess.ts (NEW): let members obtain micro parametric hedges (flood via
    property-cat/industry_loss index, individual life via group_mortality, terrorism) THROUGH the co-op. The SWAP
    is co-op<->ECP-counterparty (both ECP); the member<->co-op relationship is a mutual-benefit parametric
    distribution, NOT a swap and NOT indemnity. Every product must pass synthInsurance/characterization.ts
    (parametric, ECP-only at swap layer, disclosed basis, retail block satisfied because the member is not a
    swap party). Test microHedgeAccess.test.ts: an individual member obtains micro flood coverage; the swap party
    is the co-op (ECP), never the member; characterization verdict is 'safe'.

- id: ms-completeness-liquidity
  title: Tie diversified basket-writing to HCS (reward liquidity provision to micro-risks)
  material: yes
  model: sonnet
  depends: [ms-contracts, ms-basket-perpetuals, cc-completeness-score]
  proof: `npx vitest run completenessLiquidity` exits 0
  prompt: |
    server/utils/otc/mutual/completenessLiquidity.ts (NEW): a counterparty writing a diversified basket has low net
    residual ES -> feed that into cc-completeness-score so it earns high HCS (best price/terms/limits), explicitly
    incentivizing liquidity provision to small/unplaceable risks. Test: a diversified basket writer gets a higher
    HCS contribution than a concentrated single-risk writer of equal notional.

- id: ms-verified-hedged-note
  title: Verified-hedged note — tranche premium streams from high-HCS books for institutional capital
  material: yes
  model: opus
  depends: [ms-contracts, ms-basket-perpetuals, cc-solvency-passport]
  proof: `npx vitest run verifiedHedgedNote` exits 0
  prompt: |
    server/utils/otc/mutual/verifiedHedgedNote.ts (NEW): package premium streams from diversified basket-writing +
    co-op reserves into a tranched VerifiedHedgedNote, using ScoOverlayFacility/ScoReserveMandate patterns +
    proof/verifiableProof.ts (the Solvency Passport is the note's credit story). Tranching MUST use stressed,
    correlation-aware residual (reuse completeness stress machinery), never base-case. Test verifiedHedgedNote.test.ts:
    a high-HCS pool yields a senior tranche with lower residual than a low-HCS pool; stressed residual drives
    subordination; no base-case-only AAA claim is possible.

- id: ms-disclosures-characterization
  title: Member disclosures + characterization gate for every mutual/synthetic product
  material: yes
  model: sonnet
  depends: [ms-contracts, ms-mutual-entity, ms-micro-hedge-access]
  proof: `npx vitest run mutualDisclosures` exits 0
  prompt: |
    server/utils/otc/mutual/disclosures.ts (NEW): every mutual/basket/micro product must pass
    synthInsurance/characterization.ts (parametric, ECP-only swap layer, disclosed basis) AND generate a plain-language
    member disclosure stating it is parametric (pays on an index, not on your actual loss), the basis risk, and that
    it is not insurance. Block anything that fails characterization. Test: a compliant product generates a disclosure
    and passes; an actual-loss-referencing product is blocked.

- id: ms-verification
  title: Mutual/synthetic full-suite verification + report
  material: no
  model: opus
  depends: [ms-mutual-entity, ms-ecp-qualification-wizard, ms-synthetic-underlyings, ms-basket-perpetuals, ms-micro-hedge-access, ms-completeness-liquidity, ms-verified-hedged-note, ms-disclosures-characterization]
  proof: `npx tsc --noEmit && npx prisma validate && npx vitest run` exits 0 AND `test -f docs/SYNTHETIC_MUTUAL_REPORT.md`
  prompt: |
    Run tsc, prisma validate, full vitest; write docs/SYNTHETIC_MUTUAL_REPORT.md summarizing the mutual/co-op +
    synthetic-packaging build, confirming: swaps stay ECP<->ECP + UNMARGINED, members are never swap parties, every
    product passes characterization, and note tranching is stress-based. Flag every place go-live depends on the
    OPERATOR legal items.

OPERATOR:
  - State insurance-law analysis of the co-op<->member layer (unauthorized-insurance recharacterization risk); parametric / no-indemnity / no-insurable-interest defense; jurisdiction go-live map or no-action letters. NOTHING member-facing launches without this.
  - CFTC/NFA: CPO/CTA registration vs 4.13 exemption for member-fund pools; anti-evasion analysis.
  - Securities counsel: whether membership interests and verified-hedged notes are securities (Reg D / investment-club / note exemptions).
  - ECP guarantor arrangements + capitalization to meet >$1M / >$10M thresholds.
  - Independent verification/rating for the verified-hedged note; institutional-investor documentation.
  - Apply Prisma migrations to prod (ms-contracts schema additions).
