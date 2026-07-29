# MASTER IMPLEMENTATION RUNBOOK — Portfolio Overhaul (2026-07-27)

**This is a governance + activation runbook, NOT a drop-box task file** (it is intentionally not named `PROMPT-*.md`, so the intake watcher will not decompose it). It records counsel sign-off, states the invariants that bind every implementation prompt, lists prerequisites, and defines the activation sequence.

Source of truth for WHAT to build: `/Users/kpasch/Documents/beethoven/PORTFOLIO_STRATEGY_V2_2026-07-27.md` (Parts 1–9). The eight per-app prompts below are the executable specs; each cross-references its strategy section.

---

## 0. Counsel sign-off (record)
Kale Aaron Pasch — operator AND counsel of record — has reviewed and **signed off on the legal STRUCTURE** of the entire overhaul on 2026-07-27, specifically including:
- The exposure-gate replacement of the category deny-list (Part 4.1), retaining only the physical-harm-incentive exclusion; key-person mortality as an insurance-equivalent; always-on self-attestation.
- The outcome-perpetual bidirectional trigger design (4.2) and living memos as settlement oracles (5.3).
- Apparently Law as first-party firm + Apparently OS as the boutique product; token-burn pricing with the Apparently-Law premium multiplier (4.3, 5.1).
- Vigil full absorption into Apparently (4.4); the omniscience corpus; coalition letters + winning-argument corpus (6.2).
- The four-layer insurance-elimination stack (4.10) and parametric-indemnity framing (5.6).
- The standby-line as the compliant retail pathway (Part 8) and its day-1 operability (Part 9), specifically:
  - **9.1a — the standby fee as a genuine loan-COMMITMENT fee on a real contingent credit facility** (repayable draw; trigger = condition-to-draw, not a payout event; licensed principal = real creditor), NOT a disguised insurance premium. **Blessed.**
  - **9.4 broker-avoidance** — the user's own agent/bots run the IOI process as the recipient's agent; Tomorrow provides technology + referral only and charges NO fee/commission for the financing match (revenue = ECP subscription + token usage); once live it is bilateral bot-to-bot with Tomorrow not a party. **Blessed.**
  - **9.5 / 8.3 — capacity is ECP-only and bilateral; NO securities, NO Reg D, NO note/ILS/pool-participation of any kind.** "Tranche" = seniority-structuring of named bilateral ECP swap legs (PTRRS fabric), never a sold instrument. **Blessed.**
  - Broadened principals incl. broker-dealer/investment-firm SBLOC variants (9.2).

**Counsel sign-off ≠ go-live.** It authorizes BUILDING the code to this structure. It does NOT authorize moving real money, onboarding real lender/ECP partners, or firing live standby lines — those require the operator/ops prerequisites in §2 and stay behind default-OFF runtime flags until each is provisioned and each principal-type doc variant is executed. Build now; flip live per §2.

---

## 1. Global invariants — these bind EVERY prompt below (the fleet must honor them everywhere)
1. **Disinterested operator (N8):** no app ever becomes a principal counterparty, lender, insurer, or swap dealer. Tomorrow runs NO proprietary book. Grep-enforced.
2. **No securities surface, anywhere:** no note, no Reg D, no pool-participation interest, no tokenized investment sold to anyone. Capacity is ECP-only bilateral swaps. If a task would create a security, it is wrong — stop and flag.
3. **Bilateral ECP posture:** swap execution is ECP-only (statutory prongs: $10M discretionary / $5M+hedging / guarantor). Non-ECPs are buyers via the licensed-principal credit rail only, never counterparties.
4. **Participant-agent + no-fee-for-match:** matching/IOI is run by the participants' own agent bots, not the platform; no per-match financing fee anywhere; platform revenue = subscription + token burn.
5. **Standby fee = loan-commitment fee** on a real contingent facility (9.1a), never a premium; the maintenance swarm continuously re-tests this characterization as law evolves.
6. **Physical-harm-incentive exclusion retained:** no payout that rewards a beneficiary for causing/being adjacent to physical harm; key-person mortality (attested insurable-interest-equivalent) is permitted.
7. **Information barrier (exam data ↔ any pricing/curve/trading surface):** enforced in code (14-field allowlist pattern). Load-bearing.
8. **Token-burn pricing:** metered burn like AI usage; Apparently-Law human work = same burn with a premium multiplier; NO fixed quotes, NO refunds, NO hourly bills.
9. **Attribution:** every prompt, steering decision, approval, and Illuminati decision is attributed to the authenticated actor (never client-supplied), carried into `steering_events` and the receipt chain.
10. **Review gate before prod:** NO app work auto-promotes to production. Everything merges to the staging/dev branch and holds for operator review (see §3 — the review-gate wave must be live first).
11. **Every new live-money / real-partner path ships behind a default-OFF flag** until its §2 prerequisite is met.
12. **Repo conventions per each repo's CLAUDE.md** (migrations name-checked, RLS default-deny, ai-call-logger, selectModel, lint:migrations, no root scratch files, single git author identity).

---

## 2. Operator/ops prerequisites (assistant cannot do these — you must)
Build proceeds without these; LIVE activation of the flagged features waits on them.
- **apparently-law repo + Vercel project + Supabase project** created and registered in `deployment_bindings.json` before the apparently-law prompt activates.
- **New S2S secrets** provisioned in each side's env + GitHub secrets (never entered by the assistant): `APPARENTLY_LAW_SHARED_SECRET`, `WARROOM_S2S_SECRET`, `PARETO_SMARTER_SHARED_SECRET`, `ILLUMINATI_API_KEY` / `ILLUMINATI_URL`, `APPARENTLY_URL` (for Illuminati advisory), plus any standby-rail partner keys.
- **Notification transport** (`scripts/notify.sh` or Resend/Slack env) so "ready for review" actually reaches you (the review-gate wave builds this; you supply the keys).
- **Licensed principal + ECP capacity partners** signed and each principal-type CADE doc variant executed before any standby line goes live (default-OFF until then).
- **Counsel-flag flips** are yours: `RISK_STUDIO_*`, standby/capacity `*_ENABLED`, `CODE_IMPROVEMENT_ENABLED`, `GIT_AUTOMATION_ENABLED`, etc. — flip per feature when its prerequisite is met.

---

## 3. Activation sequence (dependency-ordered waves)
Activate a per-app prompt by renaming `HOLD-PROMPT-<x>.md` → `PROMPT-<x>.md` at the orchestrator repo root (the intake watcher ingests `PROMPT-*.md` and decomposes each via planner). Do it in this order; let each wave reach staging + your review before starting the next where a dependency exists.

**WAVE 0 — Control plane (ALREADY LIVE; must complete first).**
`PROMPT-beethoven-review-gate-and-steering.md` — already ingested. It adds the staging→prod approval gate, the waves/merge dashboard, working notifications, attribution (`submitted_by` + `steering_events`), Madeus clarifying questions, and Illuminati CADE co-think. **Verify these work before Wave 1** — until the gate exists, other work could auto-promote to prod.

**WAVE 1 — Foundational, parallelizable (no cross-dependencies):**
- `HOLD-PROMPT-apparently-vigil-merge.md` (biggest — full Vigil absorption, omniscience corpus, lifecycle matrix, regulatory studio, coalition/winning-argument, jurisdiction swarms, living memos, protection storefront, CADE agreement suite, Apparently OS, multi-entity).
- `HOLD-PROMPT-tomorrow-selfservice-insights-ecp.md` (exposure gate, outcome perpetuals, standby primitive + retail pathway, warehouse, capacity + principal consoles, tranche-as-bilateral, tax swarm, insurance-elimination stack, ISDA prove-then-complete).
- `HOLD-PROMPT-smarter-embed-and-coordination.md` (embed surface, member identity + free-to-pickup, inbound findings pipeline, credits ledger, Pareto egress).
- `HOLD-PROMPT-illuminati-overlay-and-trust.md` (trust floor, 5 install surfaces incl. gateway proxy, live sidecar + option ladder + fork-nodes, funnel, receipt packs, living policies).

**WAVE 2 — Dependent on Wave 1 + prerequisites:**
- `HOLD-PROMPT-apparently-law-site.md` (needs the repo/Vercel/Supabase from §2; consumes Apparently + CADE via S2S).
- `HOLD-PROMPT-beethoven-madeus-platform.md` (needs Wave 0 landed — shares web/ surfaces; embeds into Apparently/Tomorrow/Pareto).
- `HOLD-PROMPT-pareto-luxury-ecp-exchange.md` (consumes Tomorrow standby S2S from Wave 1; bug burn-down can start anytime).

**Concurrency guidance:** do not fire all of Wave 1 in the same minute if fleet capacity is limited — stagger by a few hours or cap `MAX_PARALLEL` so the merge train and your review queue don't saturate. The apparently-vigil prompt alone is a large multi-week body of work.

---

## 4. Materiality — everything here is MATERIAL
Every prompt touches material paths (compliance, swaps, pricing, legal, securities-adjacent, control plane). The materiality classifier should hold all of it for approval before prod — confirm it does. Because you are counsel + operator, YOU are the reviewer at the staging→prod gate. Expect to review each wave's batch; the waves dashboard (Wave 0) shows what's pending and when.

---

## 5. What NOT to do (guardrails for the fleet)
- Do not create any securities instrument, note, Reg D offering, or investor-facing pool participation.
- Do not make any app a principal/lender/insurer/dealer; do not give Tomorrow a proprietary book.
- Do not charge a per-match financing fee.
- Do not flip any live-money/partner flag to ON (that is the operator's §2 step).
- Do not push directly to main/master; do not bypass the staging→prod review gate.
- Do not enter or hardcode any secret/key.
