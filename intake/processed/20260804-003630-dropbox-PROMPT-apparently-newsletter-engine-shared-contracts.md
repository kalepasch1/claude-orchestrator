# Apparently — Bespoke Newsletter + Gated Report Engine: SHARED CONTRACTS

RECOVERY NOTE (2026-08-03). This is a reconstruction of the `…-contracts` shard of the
2026-07-30 operator directive "Apparently — Bespoke Newsletter + Gated Report Engine
(build now)". That shard's prompt was destroyed by the auto-remediate prompt-overwrite
bug (since fixed) and quarantined as `spec-lost`; the source drop-box file is gone from
disk and from git. Its five sibling shards SURVIVED and are QUEUED, and every one of them
says "honor the shared contracts" — so the contracts they depend on are the one piece
missing. This spec is derived from what those siblings explicitly require.

DO NOT re-implement the sibling sections. They are already queued and owned:
  * The differentiator: BESPOKE, not broadcast
  * Mechanics (Monday 06:00 ET send, per-subscriber render pipeline)
  * FREE public reports — marketing / power-demo gauntlet
  * GATED pre-drafted reports — the paid library
  * NEWSLETTER incentive — subscribe unlocks one typically-paid report

Build ONLY the shared contracts: the types, schemas, and interfaces those five implement
against. Ship them as real code (TypeScript types + Zod schemas + a migration where a
table is genuinely required), not documentation. No dead code — each contract must be
imported by at least one call site or covered by a test that proves its shape.

---

## Scope: the contracts every sibling shard must honor

### 1. Corpus + freshness
- `VerdictCardRef` and the corpus-hash contract. Every generated artifact records the
  corpus hash it was valid as of ("valid as of corpus hash X").
- `AuthorityChain` — the citation lineage behind a card. A report or issue MUST re-render
  when any authority in its chain changes; define the change signal that triggers it.
- Freshness states: `current` / `stale` / `superseded`, with the rule that decides each.

### 2. Subscriber profile
- `SubscriberProfile`: vertical, jurisdictions, licenses held and pending, products, and
  open compliance gaps. This is the left operand of the render pipeline.
- Profiles are per-client data. The type must make the organization scope explicit so a
  render path cannot accidentally be written unscoped.

### 3. Render pipeline
- `renderIssue(profile, corpusDiff) -> Issue` — the single interface the Mechanics shard
  implements and the differentiator shard shapes.
- `Issue` structure is contractual: "What changed for you this week" → "What it means for
  [company]" → "What we'd do before Friday" → one featured deep-dive.
- The honest-short-issue rule is part of the contract, not a nicety: when nothing material
  changed for a subscriber, the issue is one paragraph saying so. Encode it as a
  representable state (`materialChanges: []` renders the short form), so padding is not
  reachable by construction.

### 4. Citation + compliance floors
- Citation floors: ≥10 citations overall per report, ≥5 per issue. Expose them as
  constants and a `meetsCitationFloor()` predicate — every producer checks the same one.
- Every claim carries a citation. Every issue carries the disclaimer, unsubscribe, and the
  "book independent counsel" line. Make these fields required by the type, so an issue that
  lacks them cannot be constructed.
- Legal-posture rule: this engine produces marketing and informational content. It does not
  give legal advice; the independent-counsel line is load-bearing, not decorative.

### 5. Entitlement / gating
- One `EntitlementDecision` contract used by all three tiers, covering: free public report,
  gated paid library, free-to-active-subscription, and the newsletter-subscribe grant of one
  typically-paid report.
- Deny-by-default. An unknown or unresolvable entitlement resolves to DENIED, never to open.

### 6. Engagement telemetry
- `SectionEngagement` (opens / clicks per section per subscriber) and the read interface the
  renderer uses to learn per-client emphasis (exec-summary vs technical depth).
- Telemetry is per-subscriber and must be organization-scoped like everything else.

### 7. Isolation (the invariant that matters most)
- RLS default-deny on every new table.
- No cross-client leakage in ANY render path. Write an explicit test that renders for
  client A with client B's data present and asserts B never appears — the operator called
  this out specifically ("test for it explicitly"). A passing test that never had B's data
  in the fixture does not count.

### 8. Reuse
- Reuse Apparently's existing email infrastructure and the existing report/blog tables.
  Do not create a parallel send path or a second report store. If an existing table is
  close but wrong, extend it in a migration rather than forking it.

---

## Repo conventions (non-negotiable)
- Types from `~/types/database.types`; typed Supabase helpers only (`useTypedClient` /
  `useTypedServiceClient`) — no raw `.from('table')`.
- Zod schemas live in `shared/schemas/`.
- No hardcoded model strings; no `console.log` (use `server/utils/logger.ts`).
- Migrations idempotent (`IF NOT EXISTS`), names checked against `schema.prisma`
  mapping rules before landing, and `npm run lint:migrations` clean.
- Tests: pure functions tested in isolation; the cross-client leakage test is required.

## Acceptance
- Each contract is imported by at least one sibling call site OR covered by a test that
  pins its shape — nothing lands as an unreferenced type file.
- `meetsCitationFloor()` and the entitlement decision have unit tests including the
  deny-by-default and below-floor cases.
- The cross-client leakage test exists, and fails if the organization scope is removed.
- An `Issue` missing a disclaimer, unsubscribe line, or citation fails to typecheck or
  fails a test — proving the requirement is structural, not conventional.
