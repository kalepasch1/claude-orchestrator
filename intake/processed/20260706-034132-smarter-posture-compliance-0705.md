PROJECT: smarter

# REVISED delta — smarter has CADE brain + Gmail + obligationExtract already, but NO posture-compliance suite
# (tomorrow + apparently do). Lock Smarter's legal posture under an executable merge-gate suite. Conventions per the
# CADE-brain intake: proofs `npx vitest run server/utils/.../__tests__/*.test.ts`; ADDITIVE ONLY; fail closed; never
# loosen a locked gate; model strings from repo constants. Ground truth: server/utils/policy.ts (evaluateAction,
# KILL_SWITCH_GATED=['auto_send','external_share','sign_document'], UPL boundary), server/utils/governance.ts
# (trust dial counsel_only|co_pilot|auto_pilot, streak auto-promote), WorkspaceConfig.storagePolicy.

- id: smarter-posture-compliance-suite
  title: Encode Smarter's UPL + kill-switch + trust-dial posture as a compliance-as-tests merge gate
  material: yes
  model: opus
  depends: []
  proof: `npx vitest run server/utils/compliance/__tests__/posture.compliance.test.ts` exits 0 AND `test -f server/utils/compliance/compliance.manifest.json`
  prompt: |
    Mirror tomorrow's posture-compliance-suite for Smarter. Create server/utils/compliance/postureInvariants.ts (pure
    predicates) + server/utils/compliance/__tests__/posture.compliance.test.ts, each invariant its own test, wired to
    the REAL functions in policy.ts / governance.ts (not string checks where possible):
      - UPL boundary: evaluateAction blocks legal-advice action types from any autonomous path (advice never auto).
      - kill-switch: KILL_SWITCH_GATED ('auto_send','external_share','sign_document') are blocked when the global
        kill-switch is ON, and are never executed at counsel_only.
      - trust-dial monotonicity: counsel_only can only propose; streak auto-promote cannot cross a KILL_SWITCH_GATED
        action without explicit human approval; auto_pilot cannot exceed policy.
      - storage policy: strict workspaces never persist email bodies.
      - citation verification: an outbound draft that cites authority requires verified citations first.
    Add server/utils/compliance/compliance.manifest.json = { "suite":
    "server/utils/compliance/__tests__/posture.compliance.test.ts", "command":
    "npx vitest run server/utils/compliance/__tests__/posture.compliance.test.ts" } so the orchestrator compliance-gate
    auto-discovers and BLOCKS any merge that regresses posture. Do NOT change behavior — only lock it under test. Additive.

OPERATOR:
  - Counsel confirms the UPL / kill-switch invariant list is complete BEFORE this becomes a hard merge gate.
