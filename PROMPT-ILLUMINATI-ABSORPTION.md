# PROMPT-ILLUMINATI-ABSORPTION

## Directive

Full absorption of Illuminati (CADE / AI orchestrator) into Apparently.
Method: contract extraction, not naive copy. The brand retires at 100 %
regulated-surface parity — the same gate used for Vigil.

## Context

Illuminati is a Nuxt 3 application running at `https://illuminati-two.vercel.app`
on Supabase project `tsefmbiprirwcgqefemb`. It provides:

- **CADE scoring pipeline** — LLM-backed risk assessment with tiered gradient
  analysis (T0 pre-debated verdicts, T1 rapid parallel tribunal), explanation
  dossiers, and recalibration feedback loops. 7 API routes + `cadeEvaluator.ts`
  (7.5 KB), `verdictCards.ts` (9.6 KB), `rapidGradient.ts` (27.6 KB).
- **Gateway evaluation** — action-level approve/branch/block gate that consumes
  CADE scores and policy controls. 1 API route, fallback threshold logic.
- **Hivemind** — multi-domain governance, regulatory, and economic orchestration.
  14 API files dispatching to 300 KB+ of server utils across governance, economy,
  8 regulatory sub-systems (capability, temporal, frontier, opportunity,
  execution, sovereignty, immune system, proof market, atomic assurance), and
  control plane. The single largest subsystem.
- **Fleet management** — cross-product fleet administration control plane. 64 API
  route files covering policies, proof, sync (to a second orchestrator Supabase
  project `eatfwdzfurujcuwlhdgj`), governance, red-team, autonomy dials,
  marketplace, and trust-web.
- **Integration registry** — registers external integrations (IDE, AI vendor,
  corporate, CI/CD, etc.) and issues `ilmnt_` prefixed API keys.
- **Terminal / command** — operational console with cascade monitoring, deployment
  tracking, CLI-like dispatch, WebSocket + polling fallback. 6 API routes.
- **Evidence ledger** — append-only audit trail via `append_evidence` RPC,
  separate from (but complementary to) `darwin_receipts` in the kernel.
- **darwin-kernel** (`packages/darwin-kernel/`, `@darwin/kernel`) — the shared
  zero-dependency package used by ALL products. ~130 source files, ~250 KB TS.
  Sub-modules: governance (constitution, receipts, kill switch), CADE (recursive
  panels, factions, red-team, proof packs, finality, doctrine), fleetAdmin
  (65 files, 8 amplifier generations), hivemindV15 (fractal holographic memory),
  products (per-product constitutions), passport (Ed25519 portable identity),
  identity (consent-scoped graph), orchestratorClient, federated (k-anonymity),
  dataCoop, attestation, crypto, commonBrain (18 primitives), configApproval,
  resolution (cross-product mesh with jurisdiction guards), adapters.
- **30+ pages**, **95+ server utils** (~600 KB), **14 composables**, **160+
  Supabase migrations**.

### What already exists in Apparently

- Vigil absorption infrastructure: `absorption-plan.ts`, `vigil-parity.ts`
  (SurfaceKind, AbsorptionStatus, freeze enforcement, fail-closed retirement
  gate), `vigil-retirement.ts` (9-step sequence with cooling period).
- Coordination event bus: `event-publisher.ts` (outbox pattern, subscription
  routing, dead-letter queue, bot heartbeat). CoordinationEventType union with
  dotted namespace convention.
- 11 shared contracts under `shared/contracts/` (workstream, newsletter,
  disclosure, KPI, filings, gaming-portal, federation transport, etc.).
- `@darwin/kernel` is NOT yet a dependency of Apparently.

### Two Supabase projects

Illuminati uses two Supabase instances:
1. Main: `tsefmbiprirwcgqefemb` — the primary application database.
2. Orchestrator: `eatfwdzfurujcuwlhdgj` — fleet sync target for cross-product
   policy propagation.

Both must be accounted for in the absorption plan. The fleet sync endpoint
currently hardcodes the orchestrator URL + anon key as fallbacks — these must
move behind environment variables in the absorbed version.

### darwin-kernel strategy

darwin-kernel is shared infrastructure consumed by every product. It does NOT get
"absorbed" in the sense of copying its code into Apparently. Instead:
1. Apparently adds `@darwin/kernel` as a dependency (file: reference or npm).
2. Absorbed engines import from `@darwin/kernel` rather than duplicating logic.
3. The package continues to live in its own repository/package for all consumers.

The darwin-kernel Supabase tables (`darwin_*`, 12 tables) need a migration in
Apparently's Supabase project if they don't already exist there.

## Absorption architecture

Follow the contract-extraction method from `absorption-plan.ts`:
`unreviewed → contract_extracted → absorbed → retired`.

### Phase 1: Contracts (boundary-pinning)
Extract stable TypeScript interfaces for every subsystem being absorbed. These
go into `shared/contracts/illuminati-*.ts` and define the boundary that parallel
implementation branches cannot disagree on.

### Phase 2: Engine ports
Port each subsystem behind its extracted contract. Each becomes an Apparently
engine under `server/engines/illuminati/`. API routes go under
`server/api/illuminati/`.

### Phase 3: Schema migration
Add Illuminati's tables to Apparently's Supabase project via versioned
migration. Namespace with `illuminati_` prefix (same pattern as `vigil_`).

### Phase 4: Surface registration + parity measurement
Register every absorbed surface in the absorption inventory. Run
`measureParity()` and `canRetireBrand()`. 100 % regulated-surface parity
required before brand retirement.

### Phase 5: Retirement
Follow the 9-step `vigil-retirement.ts` sequence adapted for Illuminati:
freeze_writes → notify_users → migrate_auth → redirect_traffic → export_data →
disable_crons → archive_repo → delete_data → release_domain. 30-day cooling
period between last reversible and first irreversible step.

## Surface inventory (declared universe)

### Regulated surfaces (block brand retirement)

| Surface ID | Kind | Description |
|---|---|---|
| `cade-scoring-api` | api | CADE risk scoring endpoint |
| `cade-gradient-api` | api | Tiered gradient analysis |
| `cade-recalibrate-api` | api | Feedback/calibration loop |
| `cade-explain-api` | api | Explanation dossier generation |
| `gateway-evaluate-api` | api | Action approve/branch/block gate |
| `evidence-ledger` | contract | Append-only audit trail |
| `fleet-sync-api` | api | Cross-product policy sync |
| `fleet-ingest-api` | api | Governed event ingestion |
| `fleet-governance` | engine | Fleet governance control plane |
| `hivemind-regulatory` | engine | Regulatory orchestration (8 subsystems) |
| `hivemind-governance` | engine | Governance orchestration |
| `darwin-governance` | contract | Constitution evaluation, receipts, kill switch |
| `darwin-cade-core` | contract | CADE determination engine |
| `darwin-fleet-admin` | contract | Fleet admin control plane types |
| `darwin-passport` | contract | Portable identity/risk credential |
| `darwin-attestation` | contract | Signed attestation bus |
| `integration-registry` | api | External integration registration |

### Non-regulated surfaces

| Surface ID | Kind | Description |
|---|---|---|
| `cade-verdict-cards` | engine | Pre-debated verdict card system |
| `cade-gradient-deep-api` | api | Full-citation deep analysis |
| `cade-card-api` | api | Individual verdict card lookup |
| `hivemind-economy` | engine | Hivemind economy/incentives |
| `hivemind-advanced` | engine | Advanced hivemind features |
| `hivemind-autopilot` | engine | Scheduled autopilot execution |
| `fleet-propagate-api` | api | Governance propagation |
| `fleet-guidance-api` | api | Pre-action guidance |
| `fleet-analytics` | api | Fleet analytics/metrics |
| `fleet-proof` | api | Proof pack generation |
| `terminal-command` | api | CLI command dispatcher |
| `terminal-fleet` | api | Fleet agent/deployment reads |
| `terminal-metrics` | api | Cascade operation metrics |
| `terminal-cascades` | api | Active cascade listing |
| `terminal-deploy-history` | api | Deployment history |
| `terminal-poll` | api | WebSocket polling fallback |
| `darwin-hivemind-v15` | contract | Fractal holographic memory |
| `darwin-identity` | contract | Consent-scoped identity graph |
| `darwin-federated` | contract | k-anonymity privacy |
| `darwin-data-coop` | contract | Data cooperative |
| `darwin-common-brain` | contract | Deployable brain recipes |
| `darwin-resolution` | contract | Cross-product resolution mesh |
| `darwin-flywheel` | contract | Cross-product underwriting |
| `darwin-config-approval` | contract | Config change approval |
| `illuminati-pages` | page | All 30+ UI pages |
| `illuminati-composables` | engine | 14 Vue composables |
| `illuminati-server-utils` | engine | 95+ server utility files |
| `illuminati-schema` | migration | 160+ Supabase migrations |

## Constraints

- No hardcoded secrets — move fallback Supabase URLs/keys to env vars.
- No hardcoded AI models — use `selectModel()` from model-policy.ts.
- No raw `.from('table')` — use typed Supabase helpers.
- No `@ts-nocheck` — use targeted `@ts-expect-error` with reason.
- All agent work in isolated worktrees under `{repo}-wt/{slug}`.
- DO NOT prefix config keys with `ILMNT_` — use `ORCH_` for fleet-wide.
- darwin-kernel stays as a package dependency, not inlined code.
- Two Supabase projects must be reconciled; fleet sync targets the orchestrator
  project via env-configured URL.
- Feature freeze date for Illuminati must be declared and enforced (same pattern
  as Vigil's `FREEZE_DATE = '2026-08-04'`).
