# smarter: embeddable core (Apparently + Pareto), real member identity + free-to-pickup board, inbound findings pipeline, credits ledger

SUBMITTED-BY: kale@smrter.us (operator) via Cowork strategy session 2026-07-27. (Rename this file to PROMPT-… to activate.)

Operator decision of record: Smarter becomes (a) a core component of Apparently's logged-in interface for internal team coordination/approvals, (b) remains its own standalone site for general use, and (c) embeds into Pareto for personal use. Email becomes a first-class reviewed data pipeline like code.

## 1. Embeddable core (the hard blocker first)
- `server/plugins/csp.ts:24` currently sets `frame-ancestors 'self'` — replace with an env-driven allowlist (Apparently + Pareto origins; per-tenant configurable). Cookies: SameSite=None + partitioned handling for iframe contexts.
- New `/embed/*` route group with a minimal-chrome layout (no AppShell): at minimum `/embed/board`, `/embed/approvals`, `/embed/inbox`, `/embed/item/[id]`. Add a postMessage host↔guest protocol (handshake, auth refresh, resize, deep-link navigation) + a tiny JS embed SDK published from the repo.
- Sustained auth: extend the existing 300s `apparently-handoff` JWT into a refreshable embedded session (token refresh endpoint; silent re-auth from the host via postMessage). Keep the existing HMAC/JWT trust model with `APPARENTLY_SMARTER_SHARED_SECRET`; add the Pareto equivalent (`PARETO_SMARTER_SHARED_SECRET`).
- Proof: Playwright test loading an /embed page inside a fixture host page on a different origin, auth handshake completing, CSP verified.

## 2. Real member identity + "free to pickup" self-directed assignment
- `assignedTo` is free text (`types/index.ts:341`) — migrate to a member reference (workspace_members exists in schema). Backfill by name-match where possible; keep a label fallback.
- Build the claim flow the operator described: smaller startups don't have assignment structures — they need a priority board with urgency rankings (already computed by `server/utils/workIntelligence.ts`) where unassigned items sit in a visible "free to pick up" pool and any member can one-click CLAIM (and release). Claim/release/complete events append to the item audit log. Board views must answer at a glance: who has done what, what's in flight, what's unclaimed, status of each — add an "by member" rollup view (items done / in progress / claimed this week per member).
- Approvals: remove the hardcoded 'ws-skadden' defaults in `server/api/approvals/*`; scope by real workspace.
- Proof: vitest on claim/release semantics + audit entries; board renders pool + per-member rollup from fixtures.

## 3. Inbound email findings pipeline (email reviewed like code)
- Today only OUTBOUND drafts are gated (`server/utils/presend.ts`). Add the inbound pass: every synced message (and its attachments — currently never scanned; extract via the existing ingest/document path) runs a findings scan (severity, cited quote, category: privilege/PII/UPL/regulatory/commitment/conflict) producing rows in a findings table with status (open/waived/resolved), per-workspace rule config, waivers with expiry, and a findings backlog page with trends by severity over time. Add a coverage metric (% of mail through review; overrides require recorded justification).
- Align the findings shape with Apparently's (the apparently-side prompt builds the same shape) so findings can sync over the existing HMAC integration for orgs linked to Apparently.
- Proof: fixture mailbox produces expected findings incl. one attachment-derived; waiver expiry honored; coverage metric computed.

## 4. Contribution credits ledger (the doc/email hive economy)
- The privacy spine exists (anonymize.ts + assertNoClientData, negotiationHive, deidentified_learning_signals, privacy_budget_ledger, member_benefits schema). Build the missing economy: a credits ledger (accrual events, balances, redemptions), driven by contribution value — score each shared anonymized doc/pattern by realized reuse (playbook_adoptions, template reuse, benchmark participation). Add the guided release advisor: before sharing, show computed network value (segment scarcity × expected reuse) and the credit payout; member chooses release-all vs specific docs. Wire member_benefits (group discount thresholds) to actual balances. Redemptions initially: AI review hours + flags for cross-app discounts (Apparently/Tomorrow redemption handled by those apps later).
- Privacy invariants are hard: nothing enters the hive that fails assertNoClientData; k-anonymity floors on benchmarks stay.
- Proof: vitest on accrual math + reuse attribution; release advisor returns a value estimate for fixture docs.

## 5. Pareto egress (personal mode)
- Pareto has a receiver stub (`pareto/2080/server/utils/smarterDocumentAdapter.js`) awaiting a sender. Build the Smarter side: a pareto connector (config + shared secret) that pushes classified personal document/email events (tax_doc, bill, medical, insurance, receipt) in the adapter's expected envelope, with outbound trust-tier labels so Pareto's quarantine model composes. Add the personal-mode classifiers for those doc types to the intake pipeline.
- Proof: contract test against the adapter's expected schema (copy fixture from pareto tests).

## 6. Hygiene
- Rename package (`ai-email-workspace` → smrter), refresh README, and do not touch the nested unrelated apps (pasch/, pmi/, 1000/ …) in this pass.
