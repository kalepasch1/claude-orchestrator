PROJECT: tomorrow

# Round 2 of shared primitives, homed in Tomorrow's shared/contracts alongside comms-kernel-contracts /
# decision-receipt-engine from the first portfolio-primitives intake (depend on those by id; same project).
# Stack: Nuxt4 + TS + Supabase; vitest present; build in isolated worktree. Pure, contract-first, vitest-gated.

- id: portfolio-cockpit-contract
  title: Pin the cross-app autonomy-cockpit aggregation contract + pure merge reducer
  material: no
  model: sonnet
  depends: [comms-kernel-contracts]
  proof: `npx vitest run shared/contracts/__tests__/portfolio-cockpit.test.ts` exits 0
  prompt: |
    Add shared/contracts/portfolioCockpit.ts: CockpitItem { appSource, action, receiptRef (DecisionReceipt id),
    status('auto_applied'|'awaiting_approval'|'proposed'), counterfactualUsd?, ts } and a PURE mergeCockpit(streams[])
    reducer that unifies per-app receipt streams (Smarter getCockpit, Pareto autonomy cockpit, etc.) into one ordered
    feed. PII barrier: refs/enums only. Test the merge ordering + PII exclusion. No app wiring here.

- id: precedent-retrieval-engine
  title: Pure precedent index/retrieval with a deterministic embedder fallback (no secret)
  material: no
  model: sonnet
  depends: [comms-kernel-contracts]
  proof: `npx vitest run shared/contracts/__tests__/precedent.test.ts` exits 0
  prompt: |
    Add a pure precedent engine: indexPrecedent(resolvedCase) and retrievePrecedent(query, k) over resolved
    obligations/negotiations/scam-handlings. Use a deterministic embedder fallback (hashEmbedder(64) per the CADE
    kernel) so it is fully testable with NO external key; expose a pluggable embedder port for production pgvector.
    Superseded/expired precedents are excluded from retrieval. Tests: index then retrieve a semantically similar case;
    superseded excluded; deterministic under the fallback embedder.

- id: contingent-private-line
  title: Adapt contingentIdentity.ts to a private-line reveal/bond state machine (default-OFF)
  material: no
  model: sonnet
  depends: []
  proof: `npx vitest run shared/contracts/__tests__/contingent-private-line.test.ts` exits 0
  prompt: |
    Reuse the existing shared/contracts/contingentIdentity.ts default-OFF contingent-reveal state machine to model a
    private line: an unknown caller cannot reach the user (or see identity) until a condition is met (pre-authorization,
    posted refundable bond, or trust-tier threshold); reveal/admit on satisfaction; default OFF. Add the state-machine
    transitions + tests (blocked by default, admits on condition, reverts on revoke). Pure; no telephony here.

OPERATOR:
  - Production embeddings provider (pgvector) for precedent-retrieval — the deterministic fallback ships now; the real embedder + vector store is operator-set.
  - The refundable-bond mechanic in contingent-private-line moves money at runtime — keep it OFF until a payments/escrow provider + counsel sign-off (non-custodial posture) are in place.
