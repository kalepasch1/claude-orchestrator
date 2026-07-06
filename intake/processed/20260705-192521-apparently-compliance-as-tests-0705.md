PROJECT: apparently

- id: legal-posture-compliance-suite
  title: Encode the legal-opinion posture as an executable compliance-as-tests suite (merge gate)
  material: yes
  model: opus
  depends: []
  proof: `npx vitest run server/engines/compliance/__tests__/posture.compliance.test.ts` exits 0
  prompt: |
    Turn the doc-intake/legal posture into an executable suite the orchestrator's compliance-gate runs and
    that BLOCKS any merge that would weaken it. Create server/engines/compliance/postureInvariants.ts +
    server/engines/compliance/__tests__/posture.compliance.test.ts, each invariant its own test:
      - UPL boundary: the Novelty/High-Risk Sentinel's answer for genuine legal judgment is "engage licensed
        counsel," never advice; a novel-risk opinion path must set requires_human_confirmation / route to
        counsel, not auto-finalize.
      - Human-in-the-loop finalize: an opinion/finding is never marked final until every finding is reviewed
        (Document-Intake Standard principle 5); assert the finalize path refuses with unreviewed findings.
      - Grounded findings: every asserted finding carries a verbatim source quote + confidence >= threshold
        (emission guard); a finding without a quote is suppressed, not emitted.
      - Citation-verification standard: properly-formatted primary-law statutory cites are treated as verified
        (the calibrated citation-verifier standard) — lock it so a regression can't re-introduce false flags.
      - Position/self-service gate: a materially-weak position on the self_service path is BLOCKED without a
        licensed HumanCounselOverride (position-engine tenability gate).
      - No posture-changing claims: generated output must not assert the firm holds a license/registration it
        doesn't; a fixture asserting unlicensed regulated activity is flagged.
    Add server/engines/compliance/compliance.manifest.json = { "suite": "<test path>", "command":
    "npx vitest run <test path>" } for orchestrator auto-discovery. Wire predicates to the REAL engines
    (position-engine.ts, intakeGuards.ts, findingReview.ts, recipient-alignment.ts) so weakening them fails
    the tests. Lock behavior under test; do not change posture.

OPERATOR:
  - Confirm the UPL + finalize + self-service-gate invariants match current firm policy before it hard-gates merges (counsel).
