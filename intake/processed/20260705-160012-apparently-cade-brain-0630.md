PROJECT: apparently

# Extends CADE_IMPLEMENTATION_HANDOFF.md. Apparently is the process-flow memory of the
# consortium: it stores the programs CADE learns and runs the self-service autonomous
# document-program engine. Obey apparently/CLAUDE.md + DARWIN_KERNEL_ADOPTION.md.
# Guardrails: additive; fail closed; one repo per task; CADE determines, approval flows
# act (no autonomous filing/sending); RLS on every table; no raw .from(); no hardcoded
# model strings; log every AI call.

- id: cade-process-flow-registry
  title: Store CADE-learned document programs as reusable, versioned bundles
  material: yes
  model: opus
  depends: []
  proof: `npx vitest run server/engines/process-flows/__tests__/registry.test.ts` exits 0
  prompt: |
    Build a process-flow registry: when CADE completes a document program, capture
    the reusable flow (the decomposition graph, the per-unit roster/competence map,
    the deliverable set, the judgment-question template, the compliance-rule
    handoff) as a versioned, queryable bundle other apps (smarter) can invoke.
    Add an idempotent, numbered migration for a `process_flows` table (RLS on;
    typed client only; no raw .from()) storing the flow spec + provenance +
    version. Expose loadFlow(domain, objective) / saveFlow(flow). Seed one flow:
    "FCM registration + ongoing compliance" as the reference bundle. Add
    registry.test.ts covering save/load, versioning, and RLS. Name-check the
    migration before landing. Additive.

- id: mass-drafting-program-engine
  title: Self-service autonomous document-program engine (Apparently side)
  material: yes
  model: opus
  depends: [cade-process-flow-registry]
  proof: `npx vitest run server/engines/mass-drafting/__tests__/program.test.ts` exits 0
  prompt: |
    Build the engine smarter's mass-drafting orchestration calls: given an
    objective + jurisdiction, load or synthesize the process flow, decompose into
    every required deliverable, run CADE (runDetermination) per unit grounded in
    corpus_documents/legal_bot_memories/regulator_information_answers, and assemble
    the package: required filings, ongoing-compliance + exam-readiness docs,
    best-in-class internal policies, and a machine-checkable COMPLIANCE-RULE
    handoff (see compliance-backvalidation-spec). Return the minimal, ranked set of
    human-judgment questions and a signed proof per unit. No auto-file/auto-send.
    Add program.test.ts using an FCM fixture asserting the full deliverable set,
    per-unit proofs, minimal ranked judgment set, and that saving the run updates
    the process-flow registry (the learning loop). Additive; log all AI calls.

- id: compliance-backvalidation-spec
  title: Real-time compliance back-validation + audit + live "policy active" display
  material: yes
  model: opus
  depends: [mass-drafting-program-engine]
  proof: `npx -y markdownlint-cli2 docs/compliance-backvalidation.md` exits 0
  prompt: |
    Write docs/compliance-backvalidation.md: the design by which a drafted policy
    compiles into machine-checkable compliance rules that the product code
    continuously self-validates against in real time, emitting hash-chained audit
    logs and a live "policy active / passing / failing" status surface for the
    company/user (and an exportable, provenance-checked view suitable for a
    regulator/exam). Cover: the rule representation (policy -> executable
    assertions), the continuous-validation runner, the audit/receipt format (reuse
    the darwin governance hash-chained receipts), the real-time status API +
    dashboard tiles, and how failures alert + open a remediation task. Tie triggers
    to the continuous-learning monitors so a regulatory change re-opens affected
    rules (living compliance). Design only; note the actual regulator-facing
    display + any regulator data feed are operator items.

OPERATOR:
  - Regulator-facing real-time display / any direct regulator data feed — operator/compliance engagement, not queued.
  - Counsel sign-off per regulated regime before a process flow is offered for self-service.
  - Prod migration apply for `process_flows` (name-check + approval); DARWIN_SIGNING_PRIVATE_KEY_PEM in prod.
