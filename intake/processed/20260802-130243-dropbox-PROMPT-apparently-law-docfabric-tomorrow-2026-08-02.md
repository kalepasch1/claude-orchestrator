# apparently (+tomorrow bridge): Apparently Law doc fabric — prebuild Tomorrow's full legal doc suite + living-embed capability (Tomorrow = first technical user) (operator directive 2026-08-02)

SUBMITTED-BY: kale@smrter.us (operator) via Cowork strategy session 2026-08-02.

CONTEXT: All legal document drafting for the portfolio routes through Apparently/Apparently Law from now on (displacing the $200–500K outside-counsel line to draft-stage; outside counsel reviews, never drafts first). Operator account kale@heretomorrow.us was created directly in the Apparently Supabase (auth.users id 29b97c7b-dd01-415f-b6ca-3d5ba696043e, email confirmed). VERIFY provisioning end-to-end: profile/org rows, entitlements (operator/owner tier), onboarding state — repair via service-role script if the direct insert missed app-side triggers. Bind this account as the owner of the Tomorrow legal workspace/matter.

## 1. Prebuild the Tomorrow legal document suite (CADE/Consilium first drafts, counsel-review gated — legal gate stays owner-only)
Build as living documents (perpetual memos internally — auto-updated on regulatory/case-law changes via the watch/corpus rails), each with characterization receipts and a versioned changelog:
- Perpetual master-confirmation FAMILY (the spine): base master confirmation + wrapper annexes {ECP swap | loan facility | theme overlay | bundle leg}; formula-driven reset schedules; ECP covenant + automatic run-off clause; band-consent conditional-commitment annex (auction fill inside user's pre-consented band); offset-close (no-novation) mechanics; determination/oracle agent provisions with fallbacks and dispute ladder.
- ISDA pack: Schedule template (ECP reps, CEA §2(e) reps, DF-protocol reps), CSA variants (fully-collateralized; custodian ACA tri-party), bespoke confirm library per trigger family.
- Structure memos (living): SEF/IB characterization of matching+guidance+bots under bilateral-IOI invariants; dealing-notional counting for binaries vs $8B (and SBS $150M/$3B) with the telemetry methodology; swap/SBS trigger-taxonomy methodology (environment vs entity-outcome; 10/30/60/linear index rules); §9b lender-partner + true-lender + anti-evasion (§1a(47)(A)(vi)) substance file; payment-rails/no-custody/money-transmission memo; RUM no-transaction-comp memo; CTA compliance memo (Part 4/§4.7, 4.33, NFA 2-29 incl. AI-generated content).
- 50-state surveys (living, table-driven): commercial lending licensure + usury (NY <$2.5M/25% flag, CA CFL); commercial financing disclosure statutes (CA/NY/UT/VA/GA/FL/CT/KS) with APR-computation notes incl. keep-open fees; debt-waiver/GAP-analogue insurance-recharacterization survey.
- Operational docs: participation/onboarding agreements (hedger + capacity roles), capacity auction rules, standby-capacity LOI / right-of-first-look template, custodian account-control agreement template, transparency-room consent + NDA tiers, data-tier license (symmetric-availability terms, k-anonymity commitments), privacy/CCPA pack, loan-substance receipt template, exposure data pack disclosure template, NFA 2-29 promotional review checklist.

## 2. Living-embed capability (critical, dead-simple to use)
- Every Apparently Law document gets a stable signed embed: iframe/web-component + JSON API, issued via signed tokens (reuse/extend the embed_tokens pattern), scoped read-only, auto-updating when Apparently revises the doc, with version pin option + "updated" badge + changelog diff view + characterization-receipt footer.
- Doc registry: map document → destination surface. For Tomorrow (first technical user), auto-embed at the right locations: master confirmation + annexes in the contract/consent flows; structure memos in Compliance bucket; state-survey results inline in loan-application gating; auction rules on the Auctions page; consent/NDA docs in Transparency Rooms; ACA template in Collateral; 2-29 checklist in admin. Embeds must render inside Tomorrow's consent flows so the doc a user consents to IS the living doc version (with version hash recorded per consent — immutability of the consented version, updates prospective only).
- Self-service for external users: "Embed your legal docs" flow in Apparently — pick doc → get script tag / web component / signed URL + SDK snippet; per-domain token allowlist; usage metered via RUM. One-click, no engineering help required. Tomorrow's integration is the reference implementation + template gallery.
- Autonomous loop: embedded docs participate in the existing autonomous update/risk-review/hedge-review cycles — when a watched authority changes, the doc revises, embeds update, affected users get a notification + (where applicable) a hedge-review prompt into Tomorrow.

## PROOFS
- Provisioning e2e: kale@heretomorrow.us logs in, owns the Tomorrow workspace, entitlements correct.
- Doc suite: every listed document exists as a living doc with receipts + changelog; counsel-gate flags set (no doc marked counsel-approved without owner action).
- Embed: vitest on token scoping/expiry/domain allowlist; Tomorrow pages render embeds at mapped locations; consent flow records version hash; revision propagates to embed within one cycle; self-service flow issues a working embed for a third-party test domain.

OPERATOR:
- Outside-counsel review pass on the master-confirmation family + structure memos before first live execution (drafts are Apparently work product; UPL posture: internal/first-draft tooling, counsel signs).
- Change temp password on kale@heretomorrow.us at first login.
