# Orchestrator Intake Backlog — Darwin Kernel rollout + cross-product improvements

Paste this into the orchestrator intake engine. Each task below is self-contained
(scope + steps + the proof that closes it). Tasks are grouped by repo with explicit
dependencies. Everything here is **not yet implemented** — the shared `@darwin/kernel`
itself, its 10 improvement modules, the Pareto vendor + Wire 1/2 + proof script, the
six `DARWIN_KERNEL_ADOPTION.md` guides, and the enqueue tooling are **already built and
tested** and are intentionally excluded.

---

## GLOBAL CONTEXT (applies to every task)

- The shared kernel lives at `claude-orchestrator/packages/darwin-kernel` (`@darwin/kernel`),
  zero-dependency TypeScript, 59 tests green, 0 typecheck errors. Modules: `governance`
  (constitution eval + NL compiler + signed hash-chained receipts + materiality +
  PolicyService), `passport`, `attestation` (+ feeds), `identity` (graph + rollups +
  relationshipPnl), `federated`, `dataCoop` (+ exchange), `orchestrator` (capability
  registry + task queue + metering + economics), `flywheel`, `products/*`, `adapters/supabase`.
- Each app repo already contains a `DARWIN_KERNEL_ADOPTION.md` with the exact wiring
  recipe and a `vendor`/subtree step. **Follow that file** for the per-repo specifics.
- Apply `packages/darwin-kernel/sql/0001_darwin_kernel.sql` once to the shared Supabase
  project (additive `darwin_*` tables, RLS-enabled) before tasks that persist receipts/
  usage/attestations. Name-check first.
- Trust anchor: set `DARWIN_SIGNING_PRIVATE_KEY_PEM` via env (reuse Tomorrow's
  `PROOF_SIGNING_PRIVATE_KEY_PEM` so all products share one anchor). Never hardcode keys.

## GLOBAL GUARDRAILS (enforce in every task)

- **Additive only.** Do not change existing route behavior; new wiring is opt-in until
  imported. No deletions of working code.
- **Fail closed.** Preserve every existing gate (ECP, swap-only, parent-approval,
  server-authoritative settlement, RLS). Kernel rules may never *loosen* a locked dimension.
- **Materiality.** Any task touching money paths, auth/RLS, schema/migrations, or a
  product's policy core is MATERIAL → must wait for human approval before merge.
- **One repo per task.** Never edit a second repo from a task. Cross-product effects flow
  through the shared `darwin_*` tables, not direct imports.
- **Proof or it isn't done.** Each task names a command/test that must pass green.

---

## A. PARETO (repo: pareto/2080) — finish the activation

### A1 — Canonical subtree + activate Wire 1/2  [MATERIAL] [model: sonnet]
Goal: replace the copy-vendor with a real git subtree and turn the wiring on.
Scope: `vendor/darwin-kernel`, `package.json`, `server/utils/agentLedger.js`,
`server/utils/darwin/*`, a server plugin/seed, the Supabase project.
Steps: (1) `git subtree` the kernel from the orchestrator (`packages/darwin-kernel`) into
`vendor/darwin-kernel` (fallback: keep copy-vendor + add `scripts/vendor-darwin-kernel.sh`
to CI). (2) add `"@darwin/kernel": "file:vendor/darwin-kernel"` to deps. (3) Wire 1: in
`agentLedger.js`, before an action moves to awaiting_approval/approved, call `govern()`
from `server/utils/darwin/govern.ts` and persist the receipt to `darwin_receipts`
(append-only). Do NOT change tier logic. (4) Wire 2: add a startup seed that publishes the
Pareto capability specs. (5) apply `sql/0001_darwin_kernel.sql`.
Proof: `node --experimental-strip-types scripts/darwin-metering-proof.ts` prints real
engine output + signed+verified usage records + settlement; `npx vitest run` shows no
regression vs the 696 baseline.

### A2 — Geocoding city-pair table (replace great-circle stub)  [model: haiku]
Goal: remove the `price.post.js` distance stub.
Scope: `server/utils/` + `server/api/planning-room/[slug]/price.post.js`.
Steps: add a precomputed nomad city-pair distance table (the 22 cities in
`cityRentData.js`) + lookup with the great-circle fallback retained.
Proof: a unit test asserting known city-pair distances within ±5% and fallback for unknowns.

---

## B. TOMORROW (repo: tomorrow/tomorrow) — adopt the kernel  ⚠ AUTO-MERGES TO PROD

> Every Tomorrow task is MATERIAL and must be approval-gated. Keep diffs minimal; do not
> touch the self-improvement loop scripts or prod-auto-merge paths.

### B1 — Delegate the Constitution to the kernel  [MATERIAL] [model: sonnet]
Goal: Tomorrow emits the portfolio-standard signed receipt format without changing its
hard gates. Follow `DARWIN_KERNEL_ADOPTION.md` Wire 1.
Scope: `server/utils/policy/enforce.ts` (+ vendor the kernel). Set
`DARWIN_SIGNING_PRIVATE_KEY_PEM = PROOF_SIGNING_PRIVATE_KEY_PEM`.
Steps: make `evaluateConstitution` delegate to `@darwin/kernel/governance.governAction`,
persist receipts to `darwin_receipts`. ECP/swap-only/bilateral/disinterested stay as locked
dimensions enforced in code.
Proof: existing posture/policy test suite green; a new test asserts a governed action
produces a `verifyReceipt`-valid receipt; `npm run lint:migrations` clean.

### B2 — Publish Tomorrow capabilities  [MATERIAL] [model: sonnet] [depends: B1]
Goal: expose price_swap, parametric_displacement, war_room_pipeline, fabric_run on the
shared registry (Wire 2). Map each capability `endpoint` to the existing route.
Proof: a test publishes the specs and instantiates `price_swap` against a stub handler;
no change to existing routes.

### B3 — Passport claims + instant-underwrite flywheel  [MATERIAL] [model: sonnet] [depends: B1]
Goal: on ECP-gate/credit-index pass, issue `ecp_eligible` + `credit_quality` passport
claims; in Risk Studio, call `runFlywheel` so an inbound user with consented Galop/Pareto
claims is underwritten with zero new intake. Follow `DARWIN_KERNEL_ADOPTION.md` Wire 3+4.
Proof: a test where a Galop KYC passport + Pareto financial_profile claim (with consent)
yields `prefill.canInstantUnderwrite === true`.

---

## C. SMARTER (repo: smarter) — adopt + fix CI blocker

### C1 — Replace local policy evaluator with the kernel constitution  [MATERIAL] [model: sonnet]
Goal: the pre-send/UPL gate becomes a kernel constitution (deny `render_legal_advice`,
escalate final send). Follow `DARWIN_KERNEL_ADOPTION.md` Wire 1. Publish capabilities
(obligation_extraction, negotiation_position, time_estimate, contact_enrichment) and emit
a `reliability` passport claim per counterparty.
Proof: existing tests green; a test asserts `render_legal_advice` → deny and a final-send
action → escalate; a published capability instantiates.

### C2 — Fix hardcoded `@ht/ui` absolute path (CI blocker)  [model: haiku]
Goal: `@ht/ui` is aliased to `/Users/.../apparently/packages/ht-ui`, which breaks CI and
other machines. Convert to a workspace dependency or a published package reference.
Proof: `npm run build` (or typecheck) succeeds with no absolute-path alias; grep shows the
absolute path gone from config.

---

## D. APPARENTLY (repo: apparently) — become the legal backbone

### D1 — Govern bots + publish legal/regulatory capabilities  [MATERIAL] [model: sonnet]
Goal: wrap disclosure/opinion bots in `governAction` (escalate publish/file, deny
ungrounded assertions); publish `regulator_intel`, `legal_opinion`, `licensing_check` so
Tomorrow/Galop/Smarter consume them. Follow `DARWIN_KERNEL_ADOPTION.md`.
Proof: a test asserts `assert_without_citation` → deny; a consumer instantiates
`regulator_intel` against a stub and gets a typed result.

### D2 — Convert `@ts-nocheck` test files to targeted `@ts-expect-error`  [model: haiku]
Scope: the ~5 API test files using `@ts-nocheck`. Proof: typecheck passes; no `@ts-nocheck`
remains in `server/**/__tests__`.

---

## E. GALOP (repo: galop) — KYC passport + provably-fair capability

### E1 — Mint a passport on KYC/geo pass  [MATERIAL] [model: sonnet]
Goal: in the provider-seam success path (KYC + geo), mint a passport with
`kyc_verified`+`geo_allowed`+`sanctions_clear` claims and record a consent grant on
cross-product opt-in. Follow `DARWIN_KERNEL_ADOPTION.md` Wire 1. Integration point:
`racefeed/lib/providers` / `supabase` edge functions.
Proof: a test/edge-function check that a passing KYC result yields a `verifyPassport`-valid
passport with the three claims.

### E2 — Govern money-flow RPCs + publish capabilities  [MATERIAL] [model: sonnet]
Goal: route `cash_out`/`operator_payout`/`commingle_pool` through the kernel constitution
(escalate), deny `reveal_winner_pre_lock`; publish `kyc_geo_gate` and
`provably_fair_settlement`. Proof: a test asserts the deny/escalate verdicts and a
capability instantiation.

### E3 — Wire deeplink listener, video watch-fraction bonus, token-buy sync  [model: haiku]
Scope: `app/_layout.tsx` (call `setupDeepLinkListener`), `hooks/useStreak.ts` (+25 bonus on
watchedFraction), `app/(tabs)/shop.tsx` (sync token buys when `buy_tokens` RPC exists).
Proof: existing tests green + a unit test for the streak bonus.

---

## F. HISANTA (repo: hisanta) — generational account fabric

### F1 — Parent-approval gate as a kernel constitution  [MATERIAL] [model: sonnet]
Goal: model the existing parent-gate as a constitution (`deliver_ai_message`/`open_loot_box`/
`gift_purchase` escalate; `charge_child`/`open_ended_child_chat` deny) and emit signed
receipts to the parent-visibility surface. Follow `DARWIN_KERNEL_ADOPTION.md` Wire 1.
Proof: a test asserts `charge_child` → deny and `deliver_ai_message` → escalate, with a
verifiable receipt.

### F2 — guardian_verified claim + child node edges  [MATERIAL] [model: sonnet] [depends: F1]
Goal: on guardian verification, emit a `guardian_verified` passport claim and write a
`guardian_of` identity edge linking the child subject under the guardian (no child PII —
opaque subject ids only). This is the generational fabric that graduates a child's
character-ledger/elf-investments into a future Pareto junior account.
Proof: a test builds the household rollup and asserts the guardian+child appear with the
union of products; child PII never serialized.

### F3 — Publish kid-engagement capabilities  [model: haiku] [depends: F1]
Goal: publish `character_ledger` + `adaptive_difficulty`. Proof: a publish+instantiate test.

---

## G. ORCHESTRATOR (repo: claude-orchestrator) — govern itself + verifier

### G1 — Govern the runner's own task approvals through the kernel  [MATERIAL] [model: sonnet]
Goal: route every material change the runner ships through `governAction` + a signed
receipt, so all autonomous code changes across the portfolio get one offline-verifiable
audit trail. Wire into the approval-card path (`runner/` + web approvals).
Proof: a test/integration check that approving a material task writes a `verifyReceipt`-valid
receipt to `darwin_receipts`; the approval UI shows the receipt id.

### G2 — Public verifier service (productize the verifier)  [model: sonnet]
Goal: a small public endpoint/CLI that verifies any receipt / passport / attestation /
compliance-pack offline (recompute digest + check embedded key). Reads `darwin_*` by id or
accepts a pasted envelope. This is the sellable trust surface.
Proof: an endpoint test that validates a good artifact and rejects a tampered one; a curl
example in the README.

---

## H. KERNEL improvements not yet built (repo: claude-orchestrator/packages/darwin-kernel)

> These are new modules to ADD to the kernel (pure, tested, `node --test`), then surface.

### H1 — Margin-aware cross-sell ranking  [model: sonnet]
Goal: feed `productEconomics` + `relationshipPnl` back into `suggestRoutes` so cross-sell
routes are ranked by REALIZED net contribution, not static scores. Add an optional
`economicsSignal` input to the router; preserve current behavior when absent.
Proof: a test where a route with higher realized margin outranks a higher-static-score route.

### H2 — Capability service-catalog + dependency graph  [model: sonnet]
Goal: from published capabilities + usage records, emit the cross-product call graph
(who-calls-whose-engine), highest-value shared engines, and single points of failure.
Proof: a test that builds a graph from sample usage and identifies the top-consumed
capability + an SPOF.

### H3 — Receipt-chain event-sourcing projection  [model: sonnet]
Goal: generalize `verifyChain` into a replayable projection utility (fold a per-subject
receipt chain into current state + stats), so the receipt log doubles as an event-sourcing
spine + DR replay.
Proof: a test that replays a chain to a derived state and detects a broken/reordered chain.

### H4 — Compliance + judgment "exhaust" export bundle  [model: sonnet]
Goal: one call that assembles a `PolicyService` compliance pack + selected attestation-feed
entries into a single signed, offline-verifiable evidence bundle (per product). The
regulator/enterprise-facing data product.
Proof: a test that exports a bundle and a stateless verifier validates it; tamper fails.

---

## I. CROSS-CUTTING product surfaces (goal-level; decompose into tasks)

### I1 — Portfolio kill-switch / autonomy cockpit  [MATERIAL]
Objective: one control surface where flipping a constitution `killSwitch` halts ALL
products' bots at once, with receipts proving exactly what each bot did. Metric: time-to-
halt across all products < 5s; every halted action has a verifiable receipt.

### I2 — Rewards fungibility → cross-product pricing experiments
Objective: using the `dataCoop/exchange` rate table, run A/B reward experiments that move
users between products (e.g. earn Tomorrow hedging credits by completing a Pareto plan),
measured in one normalized currency. Metric: ≥1 live experiment with significance tracking.

### I3 — Consent data-cooperative as a paid product
Objective: surface the `runCoopRound` engine as an opt-in where users earn a normalized
"data dividend" for consented, k-anon/ε-DP-gated sharing. Metric: a working round paying a
reward ledger entry, with suppression below the k-floor.

---

## APPENDIX — OPERATOR / COUNSEL actions (NOT for the runner; do not queue)

These cannot be done by the runner (they need secrets, deploys, or legal sign-off). Listed
so this document is the single source of truth.

- **(B) Vendor + secrets:** mirror `DARWIN_SIGNING_PRIVATE_KEY_PEM`, S2S secrets, and any
  capability endpoints to each app's Vercel/host env; apply the kernel SQL to the shared
  Supabase project.
- **(B) Tomorrow:** deploy `20260628000000_lending_vertical`; set `CRON_SECRET`,
  `EMAIL_PROVIDER`/`RESEND_API_KEY`, S2S secrets in Vercel prod.
- **(C) Tomorrow:** counsel sign-off to flip `RISK_STUDIO_INTERMEDIATION_ENABLED`,
  `RISK_STUDIO_BASIS_GAP_ENABLED`, `SETTLEMENT_SWEEP_ENABLED`, `CUSTODY_ENABLED`.
- **(C) Apparently:** OCC carve-out + NFA/CFTC sign-off before enabling reward-token rails /
  gaming-wrapper-arb feature flags.
- **(B) Apparently:** USPS/FedEx tracking API credentials.
- **(B) Galop:** `DIGEST_SMTP_API_KEY` for weekly-digest email; Expo v2 / expo-video migration.
- **(B) Hisanta:** deploy Supabase edge functions when server-side AI/letters go live.
- **(B) Orchestrator:** deploy web to Vercel; wire Slack approval edge functions + DB
  webhook + `SLACK_*` secrets; set `ANTHROPIC_API_KEY`/`VERCEL_TOKEN`/Stripe keys; point the
  launchd scheduler at the runner.
