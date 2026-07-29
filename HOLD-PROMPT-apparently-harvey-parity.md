# apparently: Harvey feature parity (clean-room) + the network bundle + Smarter exclusivity switch

SUBMITTED-BY: kale@smrter.us (operator) via Cowork strategy session 2026-07-28. Strategy reference: PORTFOLIO_STRATEGY_V2 Part 10.5. (Rename to PROMPT-… to activate after the apparently-vigil wave is landing steadily in dev.)

WORKFLOW: parallel_fleet

Objective: eliminate the reason anyone uses Harvey by (a) shipping clean-room native equivalents of every mechanic currently driving users to Harvey, then (b) layering the capabilities Harvey structurally cannot have. Copy CONCEPTS, never code/assets/branding — all implementations are original on our stack.

## 1. Live feature catalog first (do not build from stale memory)
- First task: research Harvey's CURRENT public feature set (site, docs, release notes, reviews, comparison pages — web research at build time) and produce a versioned parity catalog: feature → what job it does → our native equivalent → status (exists / build / skip-with-reason). Commit the catalog as the workstream's contract; all sibling tasks build against it.
- Proof: catalog artifact exists with ≥15 cataloged mechanics, each mapped.

## 2. Expected parity surfaces (build the catalog's gaps; these are the known drivers)
- Assistant workflows over matters/documents (draft/summarize/extract/compare across uploaded sets) — compose from existing engines; the gap is the unified workspace UX, not capability.
- Vault-style matter workspaces: multi-document projects with persistent context, citations to source passages, bulk upload.
- Tabular multi-doc review/extraction (N docs × M questions grids, exportable).
- Firm-wide knowledge search across matters/templates/prior work (reuse pgvector + knowledge-graph infra).
- Word/Office add-in flows (Smarter's office pane exists — wire it to Apparently matters via the embed/SSO work).
- Workflow builder (reusable multi-step legal workflows — map to our skills/playbooks machinery).
- Client-matter permissioning + audit exports (RLS + audit-chain infra exists; surface it).
- Proof per surface: end-to-end fixture flow + SFC/typecheck clean.

## 3. The differentiation layer (wire ours on top — Harvey cannot follow)
- On every parity surface, surface our natives contextually: negotiation rooms, CADE adversarial review, swarm second-opinions, living-memo subscriptions (auto-updating documents), omniscience-corpus authority chains with precedential weight, CEPL risk grades + hedge quotes (recommendation-gated via Tomorrow S2S), and expert-network escalation (when the network prompt lands).
- Proof: each parity surface exposes ≥2 differentiators with fixture data.

## 4. The bundle (10.5)
- Apparently Law engagement auto-provisions: partner-tier Smarter + up to 10 junior-associate seats + full Apparently resources — via the smarter embed/SSO handoff already queued. Entitlement service + provisioning flow + seat management UI.
- Proof: fixture Law client provisions the bundle; seats enforce; de-provisioning on engagement end.

## 5. Smarter network-exclusivity switch (supersedes general-SaaS posture)
- Smarter becomes hyper-premium + network-exclusive: public marketing repositions to aspirational/by-network-access; self-serve general signup path gated off (config flag, operator flips); existing non-network workspaces grandfathered (config list). Pricing page reflects ultra-premium standalone price with "included with Apparently Law / network membership" as the real path.
- Coordinate with the smarter repo prompt's surfaces — this item is the APPARENTLY-side entitlement + positioning; the smarter-side gate is a small follow-up task in the smarter project (emit it as a cross-project note in the results).
- Proof: gating flag works; grandfather list honored; positioning page renders.

## 6. Familiar shapes + the "primitive moment" (round 8; strategy 11.5)
- Replicate the WORKFLOW SHAPES and mechanics so a Harvey user is instantly at home (zero learning curve, muscle-memory-compatible layouts and flows) — but in Apparently's own visual brand, never Harvey's trade dress. Engineer the "primitive moment" on every parity surface: the Harvey-equivalent PLUS the reframing capability (self-updating memo, CEPL grade + hedge price, CADE adversarial pass, authority chain with precedential weight, expert-network escalation) presented inline so the user concludes Harvey was first-wave.
- Proof: each parity surface passes a "Harvey-user walkthrough" fixture (same steps a Harvey user would take succeed unmodified) AND surfaces its primitive-moment differentiator.

## 7. Smarter decoy pricing ladder (round 8; strategy 11.5)
- Publish a real but deliberately aspirational Smarter rate card (partner tier in the $1,500-2,500/seat/mo band; application/waitlist-gated; a SMALL number of non-network seats genuinely sold at it — scarcity real, not fake; waitlist position visible). The attainable path is Apparently membership where partner-tier Smarter is INCLUDED — joining must feel like beating the system. Every waitlist signup routes as a warm Apparently lead (the pricing page is a lead-capture engine wearing a rate card).
- Proof: rate card + waitlist flow live; network entitlement bypasses it; waitlist signup lands in the Apparently funnel with attribution.

## 8. THE ANTICIPATION LAYER (round 10; strategy 13.5 — the layer above parity; build fully)
- A standing anticipatory swarm on every work document, acting WITHOUT prompts: CADE risk-flagging inline (graded options per the option-ladder pattern); proactive enhancement suggestions; AUTONOMOUS ACTIVATION where confidence is high — CADE deep-dives on flagged sections, formatting fixes (via the Smarter swarm S2S), DEEP citation verification to source documents (pull the source, verify the cited proposition — not just cite format), bolstering (supporting authorities attached with relevance notes). All actions logged to a visible "work done for you" ledger per document.
- NOVELTY ROUTING DOCTRINE: the user only steers genuine novelty — the CADE novelty detector routes exactly and only novel-judgment moments to the human, as decisions-with-options; everything anticipatable is anticipated.
- NEW CAPABILITIES (none exist anywhere — build all three):
  (a) COUNTERPARTY ANTICIPATOR: before send, simulate the counterparty's likely redline/objections/asks/walk-aways from the negotiation-pattern corpus; deliver the pre-hardened draft + the predicted-response memo.
  (b) DOWNSTREAM-CONSEQUENCE ENGINE: every edit instantly checked for what it breaks/changes across the whole matter — cross-references, defined terms, related agreements, filed positions, living-memo dependencies — findings inline.
  (c) THE OVERNIGHT ASSOCIATE: nightly batch swarm running the full anticipatory suite across the workspace; morning brief: "everything we strengthened/verified/flagged/prepared while you slept — N items need your judgment." This is the product promise; make the brief beautiful.
- Proof: a fixture document accumulates unprompted ledger entries across all suites; deep-cite check catches a fixture mis-cited proposition; counterparty anticipator produces a predicted redline on a fixture draft; a fixture edit triggers a downstream-consequence finding in a sibling doc; overnight brief renders from a fixture workspace.

## 9. Smarter↔Apparently feature-parity invariant + mutual-improvement confirmation (operator directive)
- ARCHITECTURE FACT to preserve: the Apparently-embedded Smarter is the SAME codebase served through Smarter's /embed/* surfaces — so every new Smarter core capability (One-OS persona modes, anticipation ledger, formatting swarms, network-readiness score) reaches the Apparently OS automatically ON MERGE, with zero porting. The only parity failure mode is surface REGISTRATION (a new capability not exposed through an embed route / not entitled to Apparently tenants).
- BUILD THE INVARIANT: a `feature-parity` CI check in the smarter repo (coordinate cross-project) — every core capability registered in the One-OS capability manifest MUST have (a) an embed-route exposure and (b) an Apparently-entitlement mapping, or the check fails with the missing pairs listed. New features cannot merge un-embedded. Apparently side: the entitlement service auto-grants new manifest capabilities to network/OS tenants by default (deny-list, not allow-list, so parity is the default state).
- MUTUAL-IMPROVEMENT LOOP (confirm + wire, don't duplicate): both directions already queued — Smarter→Apparently via the shared codebase + manifest; Apparently→Smarter via shared finding/option-ladder/storefront contracts (S2S). The HIVEMIND layer that makes them improve each other continuously: the intelligence bus + convention corpus (madeus prompt item 5) must list BOTH apps as publishers AND consumers — add both to the bus's expected-publisher registry (coherence-bot pattern) so a silent drop of either direction is flagged automatically. Steering events, calibration data, and anticipation-ledger outcomes flow into the shared corpus (k≥3 gates) and both apps' models read from it.
- Proof: parity check fails on a fixture unregistered capability and passes when embedded+entitled; both apps present in the bus publisher registry with coherence-bot coverage; a fixture Smarter capability lands in an Apparently tenant with no manual step.

## Constraints
- CLEAN ROOM: no Harvey code, copy, screenshots, or trade dress. Concepts only, original implementation. Cite the catalog, not their materials, in code/comments.
- Apparently CLAUDE.md conventions throughout; parity surfaces are mostly non-material (UI/workspace) — the hedge/CEPL wiring and entitlements are material and stamped so.
