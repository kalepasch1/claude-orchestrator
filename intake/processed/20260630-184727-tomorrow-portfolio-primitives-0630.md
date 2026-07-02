PROJECT: tomorrow

# Portfolio primitives that make the comms/obligation work compound across ALL apps. These are CONTRACTS +
# pure engines, landed contracts-first (your established ordering: contracts-* land before consumers), homed in
# Tomorrow's shared/contracts (the canonical contract location: decisionBudget.ts, xappSignal.ts, warRoomSync.ts,
# perpLifecycle.ts, contingentIdentity.ts already live here). Stack: Nuxt4 + TS + Supabase + Anthropic; vitest present;
# Supabase/Prisma migrations require name-check before landing; working tree is dirty so the orchestrator MUST build in
# an isolated worktree (it does). Do NOT rewire consumer apps here — consumer wiring is sequenced as follow-on per-app
# intakes once these are pinned (see OPERATOR). Coordinate with existing backlog tasks contracts-tomorrow and
# p0-decision-budget-wrapper — extend, do not fork.

- id: comms-kernel-contracts
  title: Pin the comms kernel contracts in shared/contracts (CommEvent, Obligation/Commitment, DecisionReceipt)
  material: no
  model: sonnet
  depends: []
  proof: `npx vitest run shared/contracts/__tests__/comms-kernel.contract.test.ts` exits 0
  prompt: |
    Add three contract files to shared/contracts, matching the existing style of decisionBudget.ts / xappSignal.ts
    (exported, stable interfaces; no runtime deps):
    - commEvent.ts — CommEvent { id, channel(enum), direction('inbound'|'outbound'), senderRef, recipientRef, ts,
      transcript?, intent?, riskScore?(0-1), trustTier?, provenance }. Refs are ids, never raw PII.
    - obligation.ts — the UNIFIED commitment shape both Smarter (server/utils/obligations.ts Obligation) and Pareto
      (server/utils/commitmentLedger Commitment) converge on: { owner('me'|'counterparty'), kind, dueDate,
      status('open'|'fulfilled'|'overdue'|'waived'), sourceRef }. This is the single cross-app contract.
    - decisionReceipt.ts — DecisionReceipt { action, authorizingRef (grant/policy id), sourceRef, counterfactualUsd?,
      signer, ts, constitutionHash? }.
    Add a contract-shape vitest test asserting exported shapes + that PII fields are absent (refs only). Typecheck clean.

- id: autonomy-budget-package
  title: Unify the 5/95 primitive into one consumable autonomy-budget engine (extends decisionBudget.ts)
  material: no
  model: opus
  depends: [comms-kernel-contracts]
  proof: `npx vitest run shared/contracts/__tests__/autonomy-budget.test.ts` exits 0
  prompt: |
    Build the single 5/95 engine that Smarter's trust dial, Tomorrow's DecisionBudget, Apparently's materiality gate,
    and Pareto's staged-commit all become instances of. Build ON the existing shared/contracts/decisionBudget.ts and
    coordinate with the p0-decision-budget-wrapper backlog task (extend it, don't duplicate).
    - Expose applyBudget(items, policy) -> { outcome (95% resolved fact), oneKnob (single Recommended discretionary
      default), proof() } enforcing the 95/5 split and surface budgets.
    - Pure + deterministic; consumable by every app surface. Include a DecisionReceipt emitter hook (from
      comms-kernel-contracts) so each resolved item can carry a receipt.
    - Tests cover: budget enforcement, Recommended default selection, proof payload, and receipt emission. Do NOT edit
      consumer app code in this task.

- id: decision-receipt-engine
  title: Signed, offline-verifiable Decision Receipt producer + verifier
  material: yes
  model: opus
  depends: [comms-kernel-contracts]
  proof: `npx vitest run shared/contracts/__tests__/decision-receipt.test.ts` exits 0
  prompt: |
    Implement produceReceipt(action, authorizingRef, sourceRef, opts{counterfactualUsd?, constitutionHash?}) and
    verifyReceipt(receipt) over the decisionReceipt.ts contract. Follow the offline/public-key pattern used by
    Apparently's attestation-signing (sign -> verify round-trips; a tampered payload fails; verification needs NO
    platform secret — it is offline/publicly verifiable). This is the audit-trail + liability shield generalized into
    one signed artifact every autonomous action across apps can attach. Tests mirror the attestation-signing contract:
    round-trip, tamper-detection, secret-free verification.

- id: federated-commitment-contract
  title: Cross-app commitment-sync contract + pure local reducer (PII-barrier clean)
  material: yes
  model: sonnet
  depends: [comms-kernel-contracts]
  proof: `npx vitest run shared/contracts/__tests__/federated-commitment.test.ts` exits 0
  prompt: |
    Define CommitmentSyncEvent carried over the existing xappSignal envelope so a commitment captured in one app maps
    to a staged action in another (e.g., a promise in Smarter email -> a Pareto staged follow-up; a fulfilled Pareto
    transaction -> close the Smarter obligation). ENFORCE the PII barrier: payload is refs + enums only (no bodies,
    quotes, names, addresses). Add a PURE reducer mapping a remote commitment to a local staged-action intent.
    Tests: payload shape, PII exclusion, and correct map of fulfilled/overdue -> local intent. Live S2S delivery is
    OPERATOR (needs secrets) — do not open a network connection here.

- id: trust-frontier-contract
  title: Unified learned-autonomy contract + deterministic reducer (per task-type / counterparty)
  material: no
  model: sonnet
  depends: [comms-kernel-contracts]
  proof: `npx vitest run shared/contracts/__tests__/trust-frontier.test.ts` exits 0
  prompt: |
    Pin the contract that unifies Smarter's streak auto-promote (governance.ts AUTO_PROMOTE_THRESHOLD) and Pareto's
    trustAutotune per-category caps into one learned-autonomy model. TrustFrontier inputs: approvals, overrides,
    regret signal, counterparty, taskType; output: a recommended autonomy level bounded by each surface's floor/ceiling.
    Add a PURE, deterministic updateFrontier(state, event) reducer (the orchestrator's bandit can optimize it later;
    here we only pin the contract + reducer). Tests: an override narrows the frontier, a clean streak widens it, and
    output never escapes floor/ceiling. No app rewiring in this task.

OPERATOR:
  - Consumer wiring is the sequenced follow-on (contracts land first, then consumers — your established ordering). Once these pin, queue per-app intakes: smarter-5-95 + family-war-room (over warRoomSync) consuming autonomy-budget + decision-receipt; pareto cockpit + counterfactual-comms (extend counterfactualLedger) consuming them; apparently materiality gate consuming autonomy-budget.
  - Live S2S delivery of CommitmentSyncEvent needs the operational-risk-signal secret + sibling endpoints (HMAC per the _s2s helpers); wire after the contract is pinned.
  - Bandit optimization of TrustFrontier + the obligation/fraud classifiers runs through the orchestrator's OWN meta-loop (bandit.py + eval_harness + self_review, approval-gated) — orchestrator-internal, not an app intake task.
  - The unified Policy Constitution (generalizing Smarter's policy.ts) that decision-receipt's constitutionHash points at should be versioned + hash-pinned portfolio-wide; confirm with counsel before it governs any external/legal autonomous send.
