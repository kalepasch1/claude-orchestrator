PROJECT: tomorrow

- id: posture-compliance-suite
  title: Encode the regulatory posture as an executable compliance-as-tests suite (merge gate)
  material: yes
  model: opus
  depends: []
  proof: `npx vitest run server/utils/compliance/__tests__/posture.compliance.test.ts` exits 0
  prompt: |
    Consolidate the scattered posture guarantees (currently posture-grep + ad-hoc asserts) into ONE named,
    executable suite the orchestrator's compliance-gate can run and that BLOCKS any merge that regresses the
    legal posture. Create server/utils/compliance/postureInvariants.ts (pure predicates) +
    server/utils/compliance/__tests__/posture.compliance.test.ts asserting, each as its own test:
      - §2(h)(7) bilateral-only: no order book / no click-to-execute path exists (IOI flow only); grep-guard
        that no route auto-executes a match. Use the existing engine functions, not string checks where possible.
      - ECP gate: every bilateral/OTC entry point calls assertEcpCounterparty (bank/gaming/overlay/fabric/synth);
        a fixture counterparty that is null or >2y-stale throws [ECP-GATE].
      - SWAP_ONLY_MODE allowlist: instrumentAllowlist refuses every DISABLED_PRODUCTS id; permitted swaps pass.
      - Fabric N1–N8: assert the guardrails (assertNoMutualization, assertDisinterested/operatorAffiliate=false,
        assertNeutral within tau, assertRiskReducing, assertNoPriceFormation, no cleared->uncleared, HHI-not-worse);
        a run violating any invariant is rejected.
      - No mutualization / no DCO: named bilateral legs only; a pooled/novated-to-CCP structure is refused.
      - GENIUS eligibility gate runs on every stablecoin-overlay structure + draw.
      - Reg Q SRT: credit-risk-transfer requires SRT certification before capital relief is recognized.
    Add a manifest file server/utils/compliance/compliance.manifest.json = { "suite":
    "server/utils/compliance/__tests__/posture.compliance.test.ts", "command": "npx vitest run <that path>" }
    so the orchestrator compliance-gate auto-discovers and runs it. Wire the pure predicates to the REAL
    guardrail functions (guardrails.ts, riskFabric/guardrails.ts, instrumentAllowlist.ts, eligibilityGate.ts)
    so the tests fail if those are weakened. Do NOT change posture behavior — only lock it under test.

OPERATOR:
  - Confirm the invariant list is complete for current exemptions before it becomes a hard merge gate (counsel).
