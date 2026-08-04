# Apparently Capability OS — full Smrter merge as per-user activatable tabs + capability bots (build now)

Operator directive 2026-07-30. AUDIT FINDING: the Apparently×Smrter "integration" today is only a
LINKAGE bridge (workspace↔org link, cross_platform_events ledger, smarter-crosssell engine). The
actual Smrter capability surface — CRM, marketing, content production, approvals, agents,
arbitration, apprenticeship, account vault, and the other ~40 API domains — is NOT operable from
Apparently. The operator should never need both apps open. This build completes the merge.

## A. The Capability OS (tabs, per-user, activatable)
1. CAPABILITY REGISTRY: every Smrter capability registered as an activatable module (name, what it
   does, required connections, owning bot, permission dimension). Browsable list + agentic
   activation ("add CRM to my workspace" in the terminal → tab appears configured).
2. PER-USER TABS, not generic: each user's OS shows THEIR activated tabs, configured to them.
   Concrete acceptance case (build it as the test): **Brian's workspace** = biz-dev/CRM, customer
   outreach, marketing content, video production, article review+production tabs; **Kale's** adds
   Medium/social management for his own accounts (kalepasch Medium + socials) with the
   consilium/expert-thought-leadership content pipeline feeding drafts.
3. EXECUTION: capabilities run against Smrter's engines (shared service layer / S2S per existing
   HMAC patterns) — ONE implementation, surfaced in Apparently's chrome; no forked logic. Smrter
   remains standalone for its own users; Apparently users never leave Apparently.
4. CONTENT/SOCIAL PIPELINE (the operator's named use case): article production (Medium-class
   thought leadership incl. consilium-backed pieces), video production intake (feeds the queued
   video-hub pipeline), social distribution — drafts flow through the commission gate + the
   permissions framework (marketing copy = its own risk dimension) before publish.

## B. Capability bots (the hivemind wiring — required, not optional)
1. ONE NAMED BOT PER CAPABILITY/TAB (crm-bot, outreach-bot, content-bot, video-bot,
   article-bot, approvals-bot...): each learns/speaks/listens/adapts on its capability AND
   subscribes to every other capability's event stream for its user + org.
2. CROSS-CAPABILITY REASONING in real time: a CRM note about a prospect's licensing question
   should surface in the content bot ("write the article that answers this"), the outreach bot
   ("this prospect is exam-season busy — delay the sequence"), and the compliance gradient
   (company_context). Events flow through the existing cross_platform_events ledger — extend it,
   don't fork.
3. THREE LEARNING SCOPES, privacy-tiered: user (personal patterns), org (workspace patterns),
   hivemind (cross-org aggregates under k>=3, no leakage — existing rules). Bots create
   tasks/edits/workflows/approvals autonomously WITHIN the user's permission ceiling and
   propose above it — the same constitution/ceiling machinery, no new gates invented.
4. Every bot's activity lands in the progress console + daily digest; every autonomous action
   auditable (who/which-bot/why/what-rule-allowed-it).

## C. 50-500X (bake in, not bolt on)
- CAPABILITY GENETICS: bots share learned step-patterns through the teach-skills engine (queued
  build) — the outreach cadence learned in one org becomes a proposable template in another.
- "COMPOSE A TAB": users combine capability primitives into custom tabs ("outreach + article
  review in one view for Brian") — composition is configuration, not code.
- The activation moment is the demo: activating CRM should immediately show value from data we
  ALREADY hold (contacts inferred from connected email, pipeline inferred from threads) — a tab
  that arrives pre-populated converts; an empty tab churns.

## Constraints
Reuse Smrter engines via service layer; RLS/workspace scoping everywhere with tests; capability
activation respects the permissions framework; no duplicate schemas — Smrter's tables remain the
system of record for its capabilities, Apparently reads/writes through the shared layer.
