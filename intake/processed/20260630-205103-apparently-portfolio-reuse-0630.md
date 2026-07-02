PROJECT: apparently

# Generalize Apparently's EXISTING frontier engines into portfolio-wide primitives (do NOT rewrite; EXTEND, and keep
# the existing filing/licensing paths green). These reuse engines already shipped in the apparently-frontier intake:
# proof-carrying (tests/engines/trust/proof-carrying.test.ts), filing-warranty (tests/engines/trust/filing-warranty.test.ts),
# outcome-learning (tests/engines/learning/outcome-learning.test.ts), examiner-twin (tests/engines/examiner/examiner-twin.test.ts),
# hive prepositioning (tests/engines/hive/prepositioning.test.ts). Conventions: vitest (`npx vitest run tests/...`);
# migrations name-check before landing (e.g. `SELECT to_regclass('public.X')` NULL pre-apply). Coordinate with the
# frontier tasks — additive only. Bind to the shared contracts pinned in tomorrow (decisionReceipt.ts, obligation.ts);
# mirror locally if not yet importable cross-repo.

- id: proof-carrying-actions
  title: Generalize proof-carrying so ANY action emits an offline-verifiable, constitution-bound proof
  material: yes
  model: opus
  depends: []
  proof: `npx vitest run tests/engines/trust/proof-carrying.test.ts` exits 0
  prompt: |
    Extend the existing proof-carrying engine to accept a generic action + DecisionReceipt (tomorrow
    shared/contracts/decisionReceipt.ts; mirror the type locally if not yet importable) and emit a proof that verifies
    OFFLINE it was produced under the Policy Constitution against verified facts. Altering any cited fact OR the
    constitution hash must invalidate the proof. Keep the existing filing/opinion proof path passing. Extend the test
    to cover a non-filing action class.

- id: reliability-priced-warranty
  title: Generalize computeWarranty to price a guarantee for any action class
  material: yes
  model: sonnet
  depends: []
  proof: `npx vitest run tests/engines/trust/filing-warranty.test.ts` exits 0
  prompt: |
    Extend computeWarranty into computeWarranty(actionClass, confidence, segmentErrorRate, opts) so it prices
    guarantees for comms / financial / obligation actions, not just filings. Below the quality floor => offered=false;
    high-confidence + low-error => a bounded price. Keep the existing filing-warranty behavior intact and extend the
    test with a non-filing action class. (Pricing a guarantee is a financial product — see OPERATOR for counsel gate.)

- id: outcome-calibration-generalize
  title: Generalize outcome-learning to calibrate confidence for any domain/segment
  material: yes
  model: opus
  depends: []
  proof: `npx vitest run tests/engines/learning/outcome-learning.test.ts` exits 0
  prompt: |
    Extend outcome-learning to accept a domain/segment key (obligation, fraud, negotiation — not only
    jurisdiction×vertical). Feeding labeled outcomes shifts that segment's calibration weights, the next prediction
    moves in the expected direction, and weights persist. If persistence needs a schema change, name-check the
    migration first. These calibrated confidences feed reliability-priced-warranty and the trust frontier.

- id: adversary-twin
  title: Generalize examiner-twin into a counterparty/adversary twin (negotiation + fraud)
  material: no
  model: sonnet
  depends: []
  proof: `npx vitest run tests/engines/examiner/adversary-twin.test.ts` exits 0
  prompt: |
    Factor the examiner-twin into a generic twin and add predictCounterpartyMoves(profile, history) -> ranked likely
    moves / red-flags (with the same citation/ranking rigor). Use it to predict a vendor's next negotiation move or a
    caller's likely scam pattern BEFORE engaging. Empty/no-history => predicts none. Keep examiner-twin working
    (it should become a thin caller of the generic twin). Add tests/engines/examiner/adversary-twin.test.ts.

- id: comms-prepositioning
  title: Generalize hive prepositioning to forecast future comms/obligation needs
  material: no
  model: sonnet
  depends: []
  proof: `npx vitest run tests/engines/hive/prepositioning.test.ts` exits 0
  prompt: |
    Extend planPrepositioning to accept a comms/obligation footprint (upcoming renewals, vendors needing
    re-verification, lines needing authorization) and return pre-stage actions with file-by/act-by dates ahead of need.
    Keep the existing licensing-prepositioning path green; extend the test with a comms footprint case.

OPERATOR:
  - Counsel gate before reliability-priced-warranty ships as a real offer: pricing a guarantee on outcomes can carry insurance/financial-product regulatory implications — confirm posture before exposing prices to users.
  - Production embeddings + S2S to feed these into the portfolio cockpit and federated network need secrets (HMAC per _s2s helpers) — deterministic/offline paths ship now; live wiring is operator-set.
