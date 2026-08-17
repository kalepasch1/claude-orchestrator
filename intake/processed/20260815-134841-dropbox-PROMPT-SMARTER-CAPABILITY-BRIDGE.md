# PROMPT-SMARTER-CAPABILITY-BRIDGE

## Directive

Dual-mode absorption of Smarter capabilities into Apparently. Smarter continues
as a standalone product — the brand does NOT retire. Instead, Apparently gains
the ability to consume Smarter's core capabilities through versioned contracts
and event bridges, so users of either app get cross-platform awareness without
switching context.

This is NOT the Vigil/Illuminati pattern (full absorption with brand retirement).
This is capability mirroring: Smarter publishes, Apparently imports. The
authoritative implementation stays in Smarter; Apparently holds a synchronized
view.

## Context

### Smarter surface area

Smarter (`smrter`) is an AI-powered legal/compliance workflow platform. Nuxt 3,
Supabase, Vercel, port 3004. Key dimensions:

- **137 pages** spanning: matter management (board, items, activity, my-work),
  war room / negotiation (negotiation-room, deal-room, deal-intel, opposing-intel,
  conflicts), corporate transactions (M&A, due diligence, filing, finality,
  arbitration), AI/intelligence (ask, CDO, darwin, vigil, agents, decision-lab,
  swarms, work-intelligence), client management (portal, token-based access),
  people/career (credentials, wellbeing, recruiting, talent), governance (trust
  dial, approvals, sentinel), billing, growth/marketing, and 7 vertical landing
  pages.

- **~998 API routes** across: AI/LLM (19), war room (11), approvals (8),
  agents (7), auth (14), bar admission (12), CDO (32+), client portal (7),
  conflicts (6), constellation (100+ autonomous intelligence), credits (3),
  darwin (9), deal health/flow/intel (15+), decision fabric (7), filing (6),
  finality (11), governance (10), growth (14), ingestion (7), integrations (8),
  legal events / MCP (4), shield (23), vigil (3), plus push notifications,
  billing, and others.

- **3 engines**: CADE inbound (document triage), SHIELD (associate protection),
  mass drafting (autonomous filing/compliance document production).

- **~400 server utils** including: LLM provider seam, model-policy, governance
  trust dial, finality (crypto-grade hash-chained versioning), matterRunner
  (deal-type templates), war room attorney cockpit, swarm orchestration,
  evidence graph, clause genome, decision fabric, federated learning, court
  e-filing, bar admission orchestrator, credentials vault, overnight desk.

- **163 KB single types file** (`types/index.ts`) defining every shared
  interface: workspace, matter, war room, negotiation, orchestration, policy
  constitution, coordination, citations, research, billing, intake, agents.

- **31 Supabase migrations** + 178 KB baseline schema.

- **Portable Legal Event Protocol**: Ed25519-signed, append-only, with generated
  SDKs in 5 languages.

### What already exists

**Smarter → Apparently bridges (already built):**
- `server/utils/apparentlyWorkstreamBridge.ts` — HMAC-signed workstream
  publishing to Apparently.
- `composables/useApparentlyBridge.ts` — client-side bridge composable.
- `api/integrations/apparently-*.ts` — 4 API routes for Apparently integration.
- `api/bar/webhooks/apparently.post.ts` — bar admission webhook to Apparently.
- `api/auth/apparently-callback.post.ts` / `apparently-handoff.post.ts` — OAuth
  handoff.
- Migration `20260726010000_apparently_integration.sql` — integration schema.

**Apparently → Smarter bridges (already built):**
- `shared/contracts/smarter-workstream.ts` — workstream definition contract with
  Zod validation, merge logic, completion evaluation.
- `server/engines/smarter-workstream-import.ts` — digest-based idempotent
  workstream import into `smarter_workstream_definitions` table.

**Cross-platform (already built):**
- `server/utils/crossPlatformFlywheel.ts` (21 KB) — intelligence graph
  compounding Smarter (behavioral) + Tomorrow (negotiation) + Apparently
  (regulatory) signals.
- `types/integration.ts` — war room update events, bridge events, XApp signals.
- `types/xappSignal.ts` — PII-free operational-risk signals.

**In the orchestrator backlog (already queued):**
- `contracts-smarter` — vitest harness + contract-shape tests.
- `smarter-warroom-bridge-activate` — live war room bridge.
- `smarter-opsignal-feed` — operational risk signals to Tomorrow.
- `smarter-model-policy` — centralize model selection.
- `smarter-5-95` — 5/95 doctrine + decision budget lint.

### What's missing

The existing bridges cover workstreams and war-room connectivity. The following
Smarter capabilities have no bridge yet:

1. **Matter management** — Apparently has no visibility into Smarter's matters,
   their status, or their regulatory implications.
2. **Governance / trust dial** — Smarter's graduated autonomy model
   (counsel_only / co_pilot / auto_pilot with streak-based promotion) is not
   harmonized with Apparently's governance.
3. **SHIELD** — associate protection data, behavior scoring, brilliance profiling
   are invisible to Apparently.
4. **Filing / finality** — Smarter's court/regulatory filing and closing ceremony
   systems don't feed into Apparently's regulatory filing obligations.
5. **CADE triage** — Smarter's document triage engine overlaps with Illuminati's
   CADE but isn't connected to Apparently's regulatory intake.
6. **Legal Event Protocol** — the portable event protocol exists in Smarter but
   Apparently doesn't consume it.
7. **Conflicts** — Smarter's conflict-of-interest detection has no cross-platform
   reach.
8. **Bar admission** — the credential verification and regulatory exam systems
   have limited Apparently integration (webhook only).

## Capability bridge architecture

### Pattern: publish-import with digest-based idempotency

The existing `smarter-workstream-import.ts` is the canonical pattern:

1. **Smarter publishes** a capability payload via HMAC-signed HTTP POST.
2. **Apparently receives** the payload, validates the HMAC, normalizes via a
   shared contract (Zod-validated), computes a content digest (SHA-256 of
   canonical JSON), and upserts.
3. **Idempotency** is guaranteed by the digest: if the content hasn't changed,
   the import is a no-op.
4. **The contract lives in both repos**: Smarter's `types/integration.ts` and
   Apparently's `shared/contracts/smarter-*.ts` must agree on shape.

### New capability contracts needed

Each capability gets a contract file in `shared/contracts/smarter-*.ts` on
the Apparently side and a corresponding publisher in Smarter.

| Capability | Contract file | Publisher (Smarter) | Importer (Apparently) |
|---|---|---|---|
| Matter awareness | `smarter-matter-feed.ts` | `api/integrations/apparently-matters.post.ts` | `server/engines/smarter-matter-import.ts` |
| Filing status | `smarter-filing-feed.ts` | `api/integrations/apparently-filings.post.ts` | `server/engines/smarter-filing-import.ts` |
| Governance state | `smarter-governance-feed.ts` | `api/integrations/apparently-governance.post.ts` | `server/engines/smarter-governance-sync.ts` |
| CADE triage results | `smarter-cade-feed.ts` | `api/integrations/apparently-cade.post.ts` | `server/engines/smarter-cade-import.ts` |
| Legal events | `smarter-legal-events.ts` | `api/legal-events/publish-to-apparently.post.ts` | `server/engines/smarter-legal-event-import.ts` |
| Conflict signals | `smarter-conflict-feed.ts` | `api/integrations/apparently-conflicts.post.ts` | `server/engines/smarter-conflict-import.ts` |

### PII barrier (load-bearing)

All cross-app payloads carry opaque IDs only. No names, emails, document content,
or client-identifying information crosses the bridge. The contract types enforce
this with allowlisted fields — the publisher strips non-allowlisted data before
egress (same pattern as `XAppSignal`).

### Governance harmonization

Smarter's trust dial (counsel_only / co_pilot / auto_pilot) and Apparently's
governance model must be harmonized so that a trust decision in one app is
respected in the other. This does NOT mean merging the implementations — it means
defining a shared governance posture contract that both apps consume.

The governance feed publishes:
- Current trust tier per workspace
- Streak state (approvals count toward graduation)
- Override events (manual tier changes)

Apparently consumes this to adjust its own governance gates for Smarter-originated
capability data.

## Constraints

- Smarter's brand does NOT retire. There is no parity gate.
- The authoritative implementation of every capability stays in Smarter.
- Apparently holds a synchronized read-only view (except for bidirectional
  governance harmonization).
- All bridges use HMAC-signed HTTP — no shared database connections.
- PII barrier is non-negotiable — opaque IDs only in cross-app payloads.
- Contract types must be pinned with shape tests in both repos.
- Each bridge must be independently deployable (no big-bang cutover).
- Existing bridges (workstream, war room, bar webhook) must not break.
