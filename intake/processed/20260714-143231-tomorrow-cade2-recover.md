PROJECT: tomorrow
# Learning + IOI + edge + theory layer. Chains onto core-recover + cade-publication-extract.

- id: cade-publish-gate
  title: Private-by-default tiered publish gate wired into the track-record route
  material: no
  model: sonnet
  depends: [cade-publication-extract]
  proof: `npm run build` exits 0 AND `npx vitest run packages/cade-publication` exits 0
  prompt: |
    Make packages/cade-publication evaluatePublishTier the single source of truth. Add
    server/utils/cade/publishGate.ts delegating; front /api/cade/track-record to return
    {private:true,progress} until a domain earns a tier. Keep tests green.

- id: cade-ioi-calibration-feed
  title: Matched IOIs (the agentic exchange) as ground-truth resolutions
  material: yes
  model: opus
  depends: [cade-outcome-resolvers]
  proof: `npm run build` exits 0 AND `npx vitest run server/utils/cade/__tests__/ioiCalibration.test.ts` exits 0
  prompt: |
    Add server/utils/cade/ioiCalibration.ts: map a MATCHED IOI/execution (ioiMesh, order
    book, execution-probability) to a CadeOutcome - bids/offers are stakes, matches are the
    resolutions financial predictions calibrate against. Mock matched IOI in tests.

- id: cade-ioi-price-blend
  title: Blend CADE calibrated consensus with live IOI order-flow for guidance
  material: yes
  model: sonnet
  depends: [cade-ioi-calibration-feed]
  proof: `npm run build` exits 0 AND `npx vitest run server/utils/cade/__tests__/ioiPriceBlend.test.ts` exits 0
  prompt: |
    Add server/utils/cade/ioiPriceBlend.ts blending consensus (prior) with IOI book depth
    (evidence); spread widens with ECE+disagreement+thin book. Reuse packages/cade-prediction
    pricing + IOIPriceAdvisor.vue + useBestExecution.ts. Advisory/calc-only. Test tighten/widen.

- id: cade-mispricing-radar
  title: Mispricing radar - CADE fair value vs live IOI book (edge + training)
  material: yes
  model: opus
  depends: [cade-ioi-price-blend]
  proof: `npm run build` exits 0 AND `npx vitest run server/utils/cade/__tests__/mispricingRadar.test.ts` exits 0
  prompt: |
    Add server/utils/cade/mispricingRadar.ts: signed divergence CADE-vs-IOI ranked by
    |div|xconfidencexliquidity - market-making signal + edge-proof + training label (vindicated
    up-weight experts, refuted -> counter-examples). GET /api/cade/mispricing (advisory).

- id: cade-expert-training-loop
  title: Closed-loop expert training from realized outcomes (always improving)
  material: yes
  model: opus
  depends: [cade-mispricing-radar]
  proof: `npm run build` exits 0 AND `npx vitest run server/utils/cade/__tests__/trainingLoop.test.ts` exits 0
  prompt: |
    Add server/utils/cade/trainingLoop.ts (pure): from resolved outcomes+scores recompute
    per-expert skill (expertSkill), update ensemble weights, recalibrate via fitPlatt, emit
    top counter-examples to the panel. Nightly cron. Deterministic + tested.

- id: cade-theory-forge
  title: Experts forge + test novel theories / white papers as falsifiable predictions
  material: yes
  model: opus
  depends: [cade-expert-panel-feed]
  proof: `npm run build` exits 0 AND `npx vitest run server/utils/cade/__tests__/theoryForge.test.ts` exits 0
  prompt: |
    Add server/utils/cade/theoryForge.ts: named falsifiable THEORY emits scored Predictions;
    track skill vs baseline; promote validated (->white-paper+weight signal), retire refuted
    (->counter-examples). Pure lifecycle, tested. Default-OFF flag (sign-off given).

- id: cade-predictive-product-mint
  title: Propose a new parametric contract where prediction + IOI demand + edge align
  material: yes
  model: opus
  depends: [cade-mispricing-radar]
  proof: `npm run build` exits 0 AND `npx vitest run server/utils/cade/__tests__/productMint.test.ts` exits 0
  prompt: |
    Add server/utils/cade/productMint.ts: where prediction (calibrated) + IOI demand + radar
    edge align, emit a PROPOSAL for a new parametric trigger (objective trigger + evidence +
    band) - proposal only, human-listed, ECP/anti-CCP. Test all-three + trigger. Default-OFF.

- id: cade-edge-embargo
  title: Embargo edge reports until the calibrated event resolves + position closes
  material: yes
  model: sonnet
  depends: [cade-mispricing-radar, cade-publication-extract]
  proof: `npm run build` exits 0 AND `npx vitest run server/utils/cade/publication/__tests__/embargoPass.test.ts` exits 0
  prompt: |
    Enforce embargo via packages/cade-publication edgeEmbargo (canPublishEdge/publishableEdges):
    an edge must NOT publish until its event settled + no open position + vindication scored.
    Filter every edge before drafting. Keep embargoPass tests green. Protects proprietary info.

OPERATOR:
  - theory-forge + product-mint default-OFF (sign-off recorded). Confirm IOI/execution data source.
