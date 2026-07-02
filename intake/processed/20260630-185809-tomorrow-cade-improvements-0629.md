PROJECT: tomorrow

# CADE improvement wave — finance/negotiation-specific + heavy infra, around @darwin/kernel/cade.
# Prereqs: first-wave Tomorrow CADE wiring (cade-invoker-tom, cade-finance-determine,
# cade-negotiation-vehicle, cade-proof-store-tom, cade-calibration-tom). Spec: CADE_IMPLEMENTATION_HANDOFF.md.
# Repo rules: Prisma migrations name-checked + `npm run lint:migrations`; evaluateConstitution outer gate;
# add new sensitive paths to BOTH materiality classifiers; pure tests via vitest.pure.config.ts.

- id: cade-mirror-negotiation
  title: Mirror determination in the merged negotiation vehicle
  material: yes
  model: sonnet
  depends: [cade-negotiation-vehicle]
  proof: `npx vitest run --config vitest.pure.config.ts server/utils/cade/__tests__/mirror-negotiation.test.ts` exits 0
  prompt: |
    Run CADE as the counterparty (adversary objective + counterparty roster + Tribunal model) before
    each move, so the user sees the other side's strongest position + likely counter. Surface in the
    war-room intelligence panel. Test (mocked invoker): mirror returns the opposed move + divergence.
    See chat #5 / HANDOFF §4.2.

- id: cade-model-diversity-finance
  title: Model-diversity seats for the finance/economist panel
  material: no
  model: sonnet
  depends: [cade-invoker-tom]
  proof: `npx vitest run --config vitest.pure.config.ts server/utils/cade/__tests__/model-diversity.test.ts` exits 0
  prompt: |
    Honor a persona `backend` tag in the Tomorrow invoker so a minority of economist seats run on a
    different base model (decorrelated error on contested numbers). Record backend per seat. Mocked-
    backend test. See chat #4.

- id: cade-difficulty-router-fin
  title: Difficulty router for finance determinations
  material: no
  model: sonnet
  depends: [cade-finance-determine]
  proof: `npx vitest run --config vitest.pure.config.ts server/utils/cade/__tests__/router.test.ts` exits 0
  prompt: |
    Gate the finance determine path: cheap classifier routes settled pricing/risk questions to a
    single cheap pass and contested ones to full CADE over the Monte Carlo distribution. Test: settled
    vs contested route differently. See chat #6.

- id: cade-self-precedent-fin
  title: Self-precedent store for finance determinations
  material: yes
  model: opus
  depends: [cade-proof-store-tom]
  proof: `npm run lint:migrations` exits 0
  prompt: |
    Add a CadePrecedent Prisma model (@@map("cade_precedents"), camelCase quoted cols, gen_random_uuid
    PK, an embedding column) — NAME-CHECK before landing. On a new financial issue retrieve near-
    duplicate priors and re-litigate only the delta (consistency + cost). Do not deploy to prod
    (operator-gated). lint:migrations clean. See chat #1.

- id: cade-conformal-finance
  title: Conformal coverage guarantee on finance determinations
  material: no
  model: opus
  depends: [cade-calibration-tom]
  proof: `npx vitest run --config vitest.pure.config.ts server/utils/cade/__tests__/conformal.test.ts` exits 0
  prompt: |
    Calibrate finance determination confidence against realized ROI/loan/hedge outcomes (split-
    conformal) so the certificate states a coverage rate. Add to the certificate output. Held-out
    synthetic coverage test. Guarantees meaningful only after enough outcomes (OPERATOR). See chat #9.

- id: cade-distillation-housemodel
  title: Determination distillation — cheap "house model" for common patterns
  material: yes
  model: opus
  depends: [cade-proof-store-tom]
  proof: `npx vitest run --config vitest.pure.config.ts server/utils/cade/__tests__/distill-route.test.ts` exits 0
  prompt: |
    Build the ROUTING + EVAL-GATE wrapper for a distilled house model: export training pairs from
    stored proof packs; at inference, route common/low-novelty/high-confidence determinations to the
    house model and fall back to full CADE on novelty or low confidence (gated by an eval check vs the
    golden set). Implement + test the routing + fallback + eval gate now; the actual fine-tune is an
    OPERATOR (GPU) step. Test: low-novelty high-confidence routes to house model; novel routes to full
    CADE. See chat #8.

OPERATOR:
  - Deploy the cade_precedents Prisma migration to prod after name-check + shadow dry-run, then `prisma generate`.
  - Distillation fine-tune needs an offline GPU training pipeline + a published, eval-gated house-model artifact; only the routing/fallback/eval-gate is queued here.
  - Conformal finance guarantees require accumulated realized outcomes before any public accuracy claim.
  - Confirm CADE finance outputs remain advisory + constitution-bounded (no autonomous money movement) before enabling distilled fast-path on live books.
