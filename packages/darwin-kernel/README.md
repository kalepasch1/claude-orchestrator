# @darwin/kernel

The shared, zero-dependency kernel beneath **tomorrow, smarter, apparently, pareto, galop, hisanta** and the **orchestrator**. It exists so the five primitives each product kept re-building — agent governance, identity/risk credentials, cross-product learning, and process reuse — are implemented **once** and compound across all seven.

Lives in the orchestrator repo (the designated cross-project control plane). Apps vendor it via path/workspace dependency or git subtree. Pure TypeScript, Node/Web crypto only — drops into Nuxt server routes, Supabase Deno edge functions, and (via a thin port) the Python runner.

## Modules

| Module | Opportunity | What it gives every product |
|---|---|---|
| `governance/` | #1 | `evaluateConstitution` (fail-closed) + `governAction` → signed, **hash-chained, offline-verifiable** receipts + `classifyMateriality` + **`compileConstitution`** (plain-English policy → enforceable rules, locked-dimension-safe) |
| `passport/` | #3 | Portable Ed25519 risk/identity credential — **KYC/verify once, verify offline everywhere**, time-boxed claims |
| `attestation/` | #3+ | The generalization of the passport: **any product attests anything portable**, verified offline (trigger ratings, clause-at-market, shelter-verified, …) |
| `identity/` | #3, #12 | Consent-scoped cross-product graph + `suggestRoutes` (cross-sell flywheel) + **household/entity `rollup`s** ("one relationship, every product") |
| `federated/` | #9 | k-anonymity + ε-DP so products learn from each other **without moving raw data** |
| `dataCoop/` | #9 | Consented data-sharing **paid in an existing rewards currency** (points/sparks/coins), k-anon-gated |
| `orchestrator/` | #2 | Capability registry (publish once, run anywhere) + task-queue/approval client + **metering** (signed usage record = audit AND invoice line) + **economics** (per-capability/-product gross margin + transfer P&L) |
| `governance/policyService` | new#2 | Policy-as-a-product: compile NL → govern a stream → `exportPack()` → **`verifyCompliancePack` (stateless, sellable)** |
| `attestation/feed` | new#3 | Licensable, signed, metered attestation feeds (each product's judgment as a data product) |
| `dataCoop/exchange` | new#4 | Makes points/sparks/coins **fungible** via a USD-cent rate table (the "data dividend" currency) |
| `identity/relationshipPnl` | new#5 | Household/entity **P&L + LTV proxy** by composing rollups × metering × rewards |
| `adapters/supabase.ts` | all | Drop-in Supabase transports + `persistReceipt/UsageRecord/Attestation/Rewards/IdentityEdge` |
| `sql/0001_darwin_kernel.sql` | all | The shared `darwin_*` tables (additive, RLS-enabled) |

## The one call every bot makes

```ts
import { governAction } from '@darwin/kernel/governance';
import { persistReceipt } from '@darwin/kernel/adapters/supabase';

const { verdict, receipt } = governAction({
  action: { product: 'tomorrow', type: 'place_trade', actor: 'bot137', subjectId: dealId, amountUsd },
  constitution,                 // your product's ratified constitution
  prevReceipt,                  // last receipt on this chain (for the hash link)
});
await persistReceipt(sb, receipt);     // append-only audit trail
if (verdict.decision !== 'allow') escalateToInbox(verdict);   // fail-closed
```

Anyone — a regulator, a counterparty, an auditor — can later verify the whole chain with no DB and no secret:

```ts
import { verifyChain } from '@darwin/kernel/governance';
verifyChain(receipts); // { ok: true|false, brokenAt }
```

## Per-repo adoption (each is ~3 lines + a config knob)

**Tomorrow** — already has a Constitution + C1 proof. Re-export the kernel from `server/utils/policy/` and have `evaluateConstitution()` delegate to the kernel so War Room, fabric, bank, gaming, settlement all emit the *same* receipt format other products can read. Set `DARWIN_SIGNING_PRIVATE_KEY_PEM` = the existing `PROOF_SIGNING_PRIVATE_KEY_PEM` so the trust anchor is shared.

**Pareto** — wrap the Tier-A/B/C agent spine: call `governAction` before any ledgered action; publish the ~60 pure engines as capabilities (`defineCapability` over `montecarlo`, `allocator`, `deductionOptimizer`, …) so Tomorrow's bank vertical and Smarter can instantiate them.

**Smarter** — replace the local policy evaluator with `evaluateConstitution`; publish `obligation_extraction`, `negotiation_position`, `time_estimate` as capabilities; emit a `reliability` passport claim per counterparty that Tomorrow's credit index consumes.

**Galop** — on KYC/geo pass, mint a passport with `kyc_verified` + `geo_allowed` claims (TTL = re-verify cadence). That passport is what makes a Galop user one click into Pareto/Tomorrow.

**Apparently** — wrap the disclosure/opinion bots in `governAction`; publish `regulator_intel` + `legal_opinion` as capabilities consumed by Tomorrow/Galop/Smarter.

**Hisanta** — wrap the parent-approval gate as a constitution with `deliver_ai_message` in `alwaysEscalate` (already its posture); emit `guardian_verified` passport claims that route the parent to Pareto household/college planning.

**Orchestrator** — back the capability registry + task queue with `adapters/supabase.ts` against `darwin_*` tables; all products' bot fleets enqueue here.

## Config

| Env | Purpose |
|---|---|
| `DARWIN_SIGNING_PRIVATE_KEY_PEM` | Ed25519 PKCS8 PEM — the stable shared trust anchor. Unset ⇒ ephemeral per-process key (self-verifying but not stable). |
| `DARWIN_SIGNING_DISABLED=true` | Content-addressed only (`algorithm:'none'`); integrity still checked by hash. |

## Test

```bash
cd packages/darwin-kernel && node --test --experimental-strip-types test/*.test.ts
```

59 tests cover canonical hashing, fail-closed constitution eval, §1a override, receipt tamper + chain reordering, materiality, NL policy compilation (+ locked-dimension refusal), the PolicyService compliance-pack (compile→govern→export→stateless verify + tamper), passport expiry/tamper, generic attestation verify/expiry/tamper, owner-gated + metered attestation feeds, consent gating, cross-sell routing, household/entity rollups + relationship P&L, k-anon/ε-DP, the data-coop reward round, rewards-currency exchange/fungibility, capability metering + per-capability/-product economics, and cross-product capability instantiation (incl. the Galop-KYC→Tomorrow-instant-underwrite flywheel).

A live end-to-end proof of the metered ledger against a REAL Pareto engine is in the Pareto repo: `node --experimental-strip-types scripts/darwin-metering-proof.ts`.

## Design invariants (do not weaken)

- **Fail closed** everywhere: no constitution / unknown high-risk action / thrown predicate ⇒ `escalate`, never `allow`.
- **Stateless verify**: receipts and passports verify from public inputs + embedded key alone.
- **No raw PII crosses products** — the identity graph links opaque ids; federated shares carry only privatized aggregates.
- **Locked dimensions** (per-product non-negotiables) can never be loosened by a compiled rule.
