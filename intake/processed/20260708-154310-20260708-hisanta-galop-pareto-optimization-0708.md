PROJECT: hisanta

# From 2026-07-08 fleet review. Verify findings in-repo first. Follow CLAUDE.md: business logic in
# lib/ with tests in lib/__tests__ (node --test), T.* theme constants, checkContent() guardrails,
# age<18 purchase blocks, no console.log, no mocking Supabase in tests.

- id: ai-safety-hardening
  title: Fix checkContent truncation risk + validate URLs in AI-adjacent content
  material: yes
  model: sonnet
  depends: []
  proof: `npm test` exits 0
  prompt: |
    Two child-safety gaps in lib/ai_safety.ts: 1) checkContent() can truncate long inputs before
    scanning, so disallowed content past the truncation point escapes the filter — scan the FULL
    content (chunk if needed; a flagged chunk fails the whole check; fail-closed on scanner error).
    2) URLs embedded in AI-generated or user-supplied content are not validated — add an allowlist
    based URL check (strip/deny by default, allow only known-safe domains if any are genuinely
    needed in a kids' app). Add tests in lib/__tests__/ai_safety.test.ts: oversized payload with
    late disallowed content is blocked; javascript:/data:/unknown-domain URLs stripped; scanner
    failure blocks content. Do not weaken any existing guardrail.

- id: purchase-gate-and-rls-verification
  title: Verify age/purchase gates end-to-end + document RLS on purchase tables
  material: yes
  model: sonnet
  depends: []
  proof: `npm test` exits 0
  prompt: |
    childCanPurchasePass() enforces age<18 → cannotPurchase app-side, but RLS coverage on
    purchase/commerce tables is unclear — client-side gates alone are bypassable. 1) Audit
    supabase/migrations/ for RLS on every commerce/economy table (purchases, passes, currency
    ledgers); add policies (or a migration) so a child account cannot INSERT purchase rows even with
    a tampered client — enforce the age gate at the RLS/edge-function boundary, not only in lib/.
    2) Add tests in lib/__tests__/ covering every purchase path (advent pass, loot, commerce)
    asserting under-18 denial. 3) Sweep for session-token spillover into SecureStore/AsyncStorage
    keys that persist beyond logout — clear on signout. 4) Remove production console.log statements
    (repo rule). Keep the Duolingo-style design system untouched.

PROJECT: galop

# From 2026-07-08 fleet review. No CLAUDE.md exists — read package.json/README first and match
# existing conventions. Wagering-adjacent app: fail-closed is mandatory.

- id: auth-gate-audit
  title: Audit + enforce auth on all wager-related endpoints
  material: yes
  model: opus
  depends: []
  proof: `npm test` exits 0
  prompt: |
    Review found unclear auth gates on wager endpoints. Inventory every server endpoint; classify
    public vs authed; ensure every wager/balance/payout-touching route validates the session user
    and ownership BEFORE any read/write, fail-closed. Add a regression test that walks the endpoint
    manifest asserting unauthenticated requests are rejected on protected routes. Match whatever
    auth util the repo already uses; if none exists, add a minimal requireUser helper used
    everywhere rather than per-route copies. Also write a CLAUDE.md capturing the discovered stack,
    commands, and conventions (this repo lacks one) so future agents stop rediscovering it.

- id: vendor-seam-and-prod-guards
  title: Fail-closed geo/KYC adapter seams + keep mock providers out of production
  material: yes
  model: sonnet
  depends: [auth-gate-audit]
  proof: `npm test` exits 0
  prompt: |
    1) The vendor seam is partially wired: geo-location and KYC adapters are missing while
       dependent flows proceed anyway. Implement the adapter interfaces with explicit NotConfigured
       stubs that FAIL CLOSED (a wager flow requiring geo/KYC verification refuses when the adapter
       is unconfigured) — never silently pass. 2) Mock providers are importable in production paths:
       gate every mock behind an env check that throws in production builds. 3) PostHog analytics
       fires without consent — add a consent flag check before any analytics call; default off until
       consent recorded. Tests: unconfigured adapter blocks flow; prod flag rejects mock provider;
       no analytics call pre-consent.

PROJECT: pareto-2080

# From 2026-07-08 fleet review. Governing invariants (never break): free/no fee revenue;
# non-discretionary by default (prepare, human commits); non-custodial; agent-of-user; every
# completed transaction writes back to the market graph (recordMarketOutcome.requireWriteback).
# Conventions: parseInt+isNaN guard before Prisma; every handler awaits requireAuth(event) +
# requireOwnership(event, uid); crons dual-register in nuxt.config.ts scheduledTasks AND vercel.json.
# Test gate: npm test must not regress beyond the 2 known pre-existing failures
# (tests/agentLedger.test.js, tests/bookingSaga.test.js — local Prisma-binary mismatch only).

- id: require-ownership-coverage
  title: Bring requireAuth+requireOwnership coverage to 100% of user-scoped handlers
  material: yes
  model: opus
  depends: []
  proof: `npm test` exits 0 (no regressions beyond the 2 known failures)
  prompt: |
    Review found requireOwnership guards on fewer than ~60% of handlers. Inventory every handler
    under server/api/**; for each user-scoped route ensure the first statements are
    `await requireAuth(event)` then `await requireOwnership(event, uid)` (repo convention), with
    parseInt+isNaN guards before any Prisma id lookup. Produce the inventory (route → guard status
    before/after) in the PR description. Add a CI-style check script (scripts/check-guards.mjs or
    matching repo convention) that greps handlers for the guard pair and fails on unguarded
    user-scoped routes, wired into npm test or an existing check chain, so coverage can't silently
    regress.

- id: writeback-invariant-enforcement
  title: Enforce the market-graph writeback invariant at the API layer
  material: yes
  model: sonnet
  depends: [require-ownership-coverage]
  proof: `npm run check:writeback` exits 0 AND `npm test` exits 0 (no regressions beyond the 2 known failures)
  prompt: |
    The invariant "every completed transaction writes back to the market graph" is implemented in
    server/utils/recordMarketOutcome (requireWriteback) but is not enforced where transactions
    complete. 1) Find every code path that marks a transaction/booking/staged-action as completed
    and ensure it calls recordOutcome via requireWriteback (annotated for the existing CI scanner —
    see npm run check:writeback). 2) Where completion happens without an outcome available, record
    an explicit deferred-writeback row rather than skipping. 3) Extend the CI scanner if it misses
    completion paths (e.g. saga handlers). Tests cover: completion writes observation; deferred path
    creates the deferred row; scanner fails on an unannotated completion path.

- id: reshop-backoff-and-hygiene
  title: Backoff for continuous reshop, audit cascading deletes, remove console.log
  material: no
  model: sonnet
  depends: []
  proof: `npm test` exits 0 (no regressions beyond the 2 known failures)
  prompt: |
    1) The continuous reshop/standing-auction loop lacks backoff — repeated failures or unchanged
       markets re-run at full cadence. Add per-(user, productKey) exponential backoff with a cap and
       reset-on-success; keep the schedule math pure and unit-tested (inject clock). 2) Cascading
       deletes remove dependent rows without an audit trail: before cascade, write a compact audit
       row (what, why, counts) — non-discretionary invariant means users must be able to see what
       the agent removed. 3) Remove console.log from production server paths, replacing with the
       repo's logging convention. No fee/affiliate logic anywhere (invariant).

OPERATOR:
  - Galop: choose and contract real geo-location + KYC vendors; the new adapter seams fail closed until configured.
  - Galop: confirm PostHog consent copy/UX with counsel before enabling analytics.
  - Hisanta: review RLS migration for commerce tables before prod push (child-safety surface).
  - Pareto: the 2 known test failures (agentLedger, bookingSaga) are local Prisma-binary mismatch — do not let agents "fix" them by weakening tests.
