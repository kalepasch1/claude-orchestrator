# MISSION: Legal Radar (v2, supersedes the 2026-07-10 PROMPT-legal-radar drop) — every legal/compliance document across all apps managed from the orchestrator: docs-as-code, competitor-informed, drift-detected, counsel review in minutes

FIRST ACTION — DEDUPE: an earlier version of this prompt was ingested via the drop-box on 2026-07-10 (intake/processed/20260710-164402-dropbox-PROMPT-legal-radar.md). Find any queued/running tasks it created and close-or-supersede them in favor of this version's decomposition (same dedupe pattern as queue bankruptcy: close with reason `superseded-by-legal-radar-v2`). Do not double-build.

You are working in `~/Documents/beethoven/claude-orchestrator`. ADDITIVE to PROMPT-backlog-blitz, PROMPT-meta-optimizer, PROMPT-operator-lane, and PROMPT-studio-lane — check their commits/reports and REUSE their infrastructure directly: the studio ship console (changelog/push/revert), lane mechanics, project tabs + auto-save, prompt steerability (Principle 0), cockpit tabs, intent_id tracing, and the visual-verify pattern (here: legal-verify). Repo conventions: ORCH_ config keys, no secrets, fail-soft, 20+ tests per new module, fleet propagation via git + fleet_control. The existing legal plugin skills (triage-nda, review-contract, compliance-check, legal-risk-assessment) are reference patterns for review logic.

## DESIGN

All websites' legal/compliance documents (ToS, privacy policy, cookie policy, DPA, acceptable use, refund policy, disclaimers, licensing/attribution pages) become version-controlled content managed from a LEGAL tab in the orchestrator cockpit. Models draft; approval follows the TIERED AUTONOMY model (Part 9): material/new-risk/regulator-facing changes always get human review (hard floor), while below-threshold minor changes may run autonomously once the user enables it and the autonomy ledger has earned it — every autonomous action digest-visible and one-click revertible. Intelligence comes from three radars: competitor movements (well-funded comparables bear the legal fees; we take the signal), primary regulatory sources, and policy↔code drift detection. Review time collapses from weeks to minutes because review becomes risk-ranked diff review with plain-English rationale.

UI DESIGN LANGUAGE: the Legal tab, inbox, ship console, compliance calendar, autonomy-ledger views, and repo-connect flow all follow the cockpit design language defined in PROMPT-studio-lane §9-DESIGN (Legora × Vercel × Claude): dark-first warm near-black surfaces, one restrained accent, editorial type hierarchy with monospace for SHAs/dates/deadlines/scores, hairline low-alpha borders, 8–12px radii, skeleton loaders, ≤150ms micro-interactions, ⌘K command palette, StatusPill-style state chips. Consume the SAME design tokens from the shared package — legal surfaces must be indistinguishable in polish from the studio surfaces, and are screenshot-verified against the spec like any UI task. Legora is the aesthetic reference here especially: calm, précis-like legal reading surfaces — generous line length limits, real typographic hierarchy for clause structure, diff views that read like redlines, never walls of monospace.

## PART 1 — LEGAL DOCS AS CODE (single source, all apps, full ship-console reuse)

1. Per app, a `legal/` content directory (MD/MDX with frontmatter: doc_type, jurisdictions, effective_date, version, clause refs). Migrate each app's existing posted legal pages into it (one migration task per app, master lane); sites render legal pages from this content — after migration, the repo is the single source of truth for what's publicly posted.
2. Legal changes flow on the same protected-branch mechanics as studio (`legal` lane, integrates to the design branch or a `legal` branch per `ORCH_LEGAL_BASE`), with the SAME ship console: per-change changelog entries (plain-English summary of what changed and why), click-to-explain diffs, PUSH ALL / PUSH SELECTED to master through full gates, per-entry revert, revert-after-promote. Auto-versioning: promoting a material legal change bumps the doc version, sets the effective date, archives the prior version at a public URL, and generates the user-notification artifacts (site banner copy + notification email draft) required for material-terms changes.
3. LEGAL-VERIFY gate (analog of screenshot-verify): every legal diff is checked before merge for — internal consistency (no clause contradicting another), defined-terms integrity, jurisdiction coverage vs the app's markets, readability grade, and a similarity check against competitor source texts (see Part 3 guardrail). Failures bounce back to the drafting agent with reasons.

## PART 2 — CLAUSE LIBRARY (the 100X: design tokens for legal)

4. Parse every doc into a clause graph: shared clause library (`legal_clauses` table + `packages/legal-clauses/`) where each clause has an ID, plain-English purpose, jurisdictions, risk notes, and per-app parameterization (company name, data practices, governing law). Apps COMPOSE their docs from shared clauses + app-specific overrides.
5. One clause update → fan-out tasks regenerate every consuming doc across every app, each passing legal-verify → one batched operator approval → ship console. Updating (e.g.) the arbitration clause everywhere becomes one edit + one approval instead of N manual rewrites.
6. Clause provenance: every clause records why it exists (regulation, competitor signal, counsel advice, incident) with links — so future review of "why do we say this?" takes seconds.

## PART 3 — COMPETITOR RADAR (their legal spend, our signal)

7. `legal_watch` registry per app: top comparable, well-funded competitors (operator-editable; seeded by a research task that identifies them per app category). A periodic job fetches their public legal pages (respect robots/rate limits; cache snapshots in Supabase storage), diffs against prior snapshots, and files structured findings: {competitor, doc, change summary, likely trigger (new regulation / enforcement / product change / risk posture), applicability to each of our apps, estimated adoption effort}.
8. Applicable changes generate PROPOSED updates: mapped onto OUR clause library and REDRAFTED IN OUR OWN VOICE AND FACTS — never verbatim copying (their text is copyrighted, and their terms describe their practices, not ours; the legal-verify similarity check enforces a strict ceiling on textual overlap). The value captured is the SIGNAL — what changed, why now, what risk it addresses — at research cost instead of law-firm cost.
9. Findings + proposals land in a LEGAL INBOX (cockpit Legal tab, same swipe accept/reject UX as the UX-scout inbox): accept → drafting task with variants; reject feeds preference learning. Weekly digest of competitor movements even when no action is proposed (situational awareness).

## PART 4 — REGULATORY RADAR (upcoming issues flagged in minutes, not discovered in enforcement)

10. `runner/reg_radar.py` (periodic, generator-classed, cheap+research lanes): monitors PRIMARY sources per jurisdiction and app category — new/amended privacy statutes, FTC/DPA/state-AG enforcement actions, platform policy changes (app stores, payment processors), accessibility requirements, AI-specific regulation. Files findings with: what's changing, effective dates/deadlines, which apps are exposed, estimated impact and effort, and a proposed clause/practice update.
11. Deadline tracking: flagged items with dates enter a compliance calendar on the Legal tab (30/60/90-day lookaheads surface in the daily brief). Enforcement-action learning: each analyzed fine/order becomes quality-gated knowledge ("pattern X drew a €Y fine") injected into future legal drafting and product review.

## PART 5 — POLICY↔CODE DRIFT DETECTION (the flag most teams never see)

12. `runner/practice_inventory.py`: persona_curator-style deep code review per app inventorying ACTUAL data practices — analytics/tracking SDKs, cookies set, PII fields in schemas, third-party API calls and data shared, retention behavior, auth providers, payment processors, AI/model usage. Re-runs when merged diffs touch relevant surfaces (SDK adds, new schema fields, new integrations).
13. Drift check: diff the practice inventory against what the app's posted policies CLAIM. Flags both directions — undisclosed practices ("code ships GA4; privacy policy doesn't disclose analytics") and stale disclosures ("policy discloses a processor we removed"). Each flag auto-drafts the corrective clause update AND, where the right fix is changing the code instead, files a product task with the tradeoff explained. NEW-FEATURE GATE: merged product diffs that add data practices trigger an immediate drift check, so legal exposure is caught within minutes of the feature merging — before or immediately after it ships, not at audit time.

## PART 6 — COUNSEL-IN-MINUTES WORKFLOW

14. Review queue is risk-ranked (extend legal-risk-assessment severity×likelihood): each item shows plain-English what/why/risk-if-ignored/risk-of-change, the exact diff, provenance, and affected apps. Batch approval for low-risk items; material items individually. Optional external-counsel role (invite via existing partner auth): counsel sees only the Legal tab, annotates, approves — their minutes are spent on judgment, not document assembly.
15. Steerability (Principle 0 applies): operator directives in the Legal prompt box steer everything — "hold all arbitration-clause changes", "US + EU jurisdictions only", "draft this more conservatively", "show me what [competitor] changed this quarter".
16. Full audit trail: every draft, review, approval, publication, and notification is logged with intent_id — exportable as a compliance evidence pack (also answers vendor security/DPA questionnaires from the same data, one click).

## PART 7 — REPO LINKING (any codebase, one click — the intake for everything below)

R1. `legal_repos` registry + connect flow on the Legal tab: link GitHub (App install or PAT), GitLab/Bitbucket, or any git URL in under a minute — per-repo config: which app/entity it belongs to, jurisdictions, autonomy threshold (Part 9). Webhooks (or polling fallback) capture every push/PR/merge. Internal apps are pre-linked; EXTERNAL users (future customers) get the same flow — this is the productizable front door.
R2. Every captured change runs the Part 5 pipeline (practice inventory delta → drift check → legal-relevance screen). Non-relevant changes are logged and dismissed cheaply (cheap-lane screen first, escalate only on signal).
R3. CODE-CHANGE LEGAL EXPLAINER: every legally-relevant change gets a comprehensive plain-English brief — what the code change actually does (mechanically), what data/behavior it touches, WHY it is legally relevant, which clauses/licenses/filings it implicates, and the recommended action — attached to the review item or the autonomous-action record. No reviewer should ever need to read the diff to understand the legal question (the diff stays one click away).
R4. FACT-GATHERING COMMS: when legal relevance can't be determined from the code alone, auto-generate targeted questions to the engineering team (and any other impacted team); for Smarter users these route through Smarter's learned comms workflows (auto-queued, or fully autonomous send if enabled); answers are attached to the item and shared automatically with every internal party who needs to act on the conclusion. Non-Smarter users get draft emails/messages to send manually.

## PART 8 — TRIGGERED LEGAL ACTIONS (Apparently + Smarter integration, toggleable additive)

T1. ACTION MAPPING: when a code change (or jurisdiction/vertical event, Part 10) requires legal activity beyond document edits — new licenses, registrations, regulator notifications, pre-approvals, memo drafting, compliance-doc updates — flag it and route to the right workflow: Apparently's licensing/memo/registration workflows where the user has Apparently; Smarter's learned workflows + the legal user's Smarter queue for final review where they have Smarter. Detection of what's required uses reg-radar knowledge + Apparently's existing requirement mappings (do not rebuild what Apparently/Tomorrow already do — INTEGRATE, and only build lite built-in versions behind a toggle for users without those products).
T2. FILING AUTONOMY (same materiality machinery as Part 9): e.g., a minor Form ADV amendment can be drafted autonomously, and SUBMISSION can also be autonomous if the user explicitly enables it (mirroring how Smarter handles it) — material filings always require human review. Every autonomous filing records its full explainer (R3) and lands in the audit trail + daily digest.
T3. All triggered actions inherit the deadline tracker (Part 11) — the moment an action is flagged, its full milestone chain is scheduled.

## PART 9 — MATERIALITY THRESHOLDS + EARNED AUTONOMY (replaces blanket no-auto-publish)

M1. Every legal event is scored for MATERIALITY (extend legal-risk-assessment severity×likelihood, plus: creates new obligations? new legal risk? affects user rights? regulator-facing? irreversible?). The user sets per-repo/per-app/per-doc-class autonomy thresholds. DEFAULT posture: review required for everything EXCEPT generic/minor changes that are not legally substantive and create no new material risk (typo/formatting, date/address updates, restating existing facts, version-bump boilerplate).
M2. EARNED AUTONOMY (the Smarter pattern, generalized): a shared `autonomy_ledger` tracks, per change-class, how often the user disagreed with / edited / remediated bot output. Classes with sustained low disagreement become autonomy-eligible (surfaced as a suggestion: "you've approved 25/25 cookie-list updates — enable autonomy?"); a remediation event auto-demotes the class back to review-required. Percentages are visible per class so both the user and the bots learn what can safely be autonomous.
M3. SHADOW MODE: while a class is review-required, bots ALSO run the full autonomous path in shadow (nothing published) and score their would-have-been output against what the human approved — so disagreement statistics accumulate BEFORE autonomy is ever granted. Autonomy is earned on evidence, enabled by the user, and revoked automatically on failure.
M4. Hard floor (not user-adjustable): material changes, new-risk-creating changes, and anything regulator-facing above the minor-amendment class ALWAYS require human review. Autonomous ≠ silent: every autonomous action appears in the daily digest with one-click revert.

## PART 10 — EVENT GENERATORS (jurisdiction, vertical, and removals)

G1. One-click impact packs from the Legal tab: NEW JURISDICTION ("we're entering Germany") → localized doc set from the clause library + reg-radar requirements + required registrations/notifications routed via Part 8 + full deadline chain. NEW VERTICAL ("we're adding investment advisory") → same, including the Apparently licensing workflow where applicable. Each pack is a reviewable plan (CADE-drafted, Part 12) before anything executes.
G2. REMOVALS ARE FIRST-CLASS: adjusting or REMOVING features/data practices gets the same scrutiny as additions — deletion obligations, ongoing user rights over already-collected data, surviving clauses, required sunset notices, contract/API commitments that the removal would breach. The drift checker (Part 5) already sees removals; this adds the removal-specific legal checklist and explainer.

## PART 11 — DEADLINE CHAINS (not just the final filing)

D1. Every tracked obligation expands into its FULL milestone chain: preliminary submissions, notices of intent, comment/objection windows, pre-approval requests, draft-review deadlines, effective dates, renewal cycles, post-filing confirmations — each with owner, lead time, and status. The compliance calendar and daily brief surface the next milestone per chain (30/60/90-day lookaheads), and chains auto-instantiate from Part 8 triggered actions and Part 10 packs.

## PART 12 — CADE DRAFTING + COMPETITIVE TERMS ADVANTAGE

C1. Original document drafting and every MATERIAL verbiage change runs through the existing CADE machinery (tournaments/committees): multiple drafts styled on the observable craft of top-tier contract drafting — precision, defined-term discipline, plain-language readability, favorable-but-fair allocation — scored by committee + legal-verify, best draft to review.
C2. COMPETITIVE TERMS BENCHMARKING: score our terms vs each stored competitor snapshot on flexibility (our operational freedom), protection (liability/IP/indemnity posture), user friction, and enforceability-risk. Target: measurably MORE advantageous and MORE flexible than competitors, not parity — the radar (Part 3) stops being copy-the-leader and becomes beat-the-leader. Scores displayed per doc on the Legal tab; regressions block promote.

## PART 13 — 50–500X EXTENSIONS (flags + stubs now, enable per operator decision)

17. `ORCH_LEGAL_JURISDICTION_PACKS`: entering a new market generates the localized doc set from the clause library + reg radar for that jurisdiction (translation included, counsel-gated) — market-entry legal work in hours.
18. `ORCH_LEGAL_DSR_AUTOMATION`: data-subject-request intake (access/deletion) wired to the practice inventory so fulfillment steps are auto-generated per app.
19. `ORCH_LEGAL_DILIGENCE_PACK`: one-click investor/partner/M&A due-diligence bundle — current docs, version history, compliance matrix, drift status, audit trail.
20. `ORCH_LEGAL_TEMPLATE_MARKET`: the clause library + radars generalize into a productizable capability for the portfolio's own customers (Smarter cross-sell) — flag for strategy review, not auto-built.

## GUARDRAILS

21. TIERED AUTONOMY, HARD FLOOR: material changes, new-material-risk changes, and regulator-facing items above the minor-amendment class ALWAYS require human review — this floor is not user-adjustable. Below the user's materiality threshold, autonomy is allowed only when user-enabled AND earned via the autonomy ledger (Part 9), always digest-visible and one-click revertible. AI drafts are decision-support, not legal advice — the Legal tab carries a standing note that material changes warrant licensed-counsel review, and the workflow makes that review take minutes.
22. No verbatim competitor copying: legal-verify enforces a similarity ceiling vs stored competitor snapshots; provenance records the signal, drafting always restates in our voice against OUR practice inventory.
23. Radar jobs are generators: drain_mode, caps, cheap lanes; competitor fetching respects robots.txt and rate limits; snapshots stored privately.
24. All legal lane work respects the pause-arbiter and never blocks or slows the master improvement queue; legal content changes don't touch app logic (content-directory scoped; file_claims enforced).
25. Tests (20+ per module): clause graph round-trip (parse→compose→render identical), fan-out regeneration, similarity ceiling, drift detection true/false positives on fixture apps, version/effective-date/archive flow, notification artifact generation, approval gating (no path to master without operator approval), fail-soft everywhere.

## ACCEPTANCE

- All apps' legal pages render from `legal/` content dirs; editing one shared clause regenerates every consuming doc, passes legal-verify, and ships via PUSH ALL after one batched approval — with public version archive + notification artifacts.
- A seeded competitor changes their privacy policy → within one radar cycle a finding + our-voice proposal appears in the Legal inbox with trigger analysis; similarity check demonstrably rejects a too-close draft.
- A merged product diff adding an analytics SDK triggers a drift flag within minutes, with a corrective clause draft attached.
- Reg radar surfaces a dated upcoming requirement into the compliance calendar and daily brief.
- Operator reviews and ships a batch of 5 legal updates across 3 apps in under 10 minutes, end to end, with full audit trail.
- Repo link → explainer: linking a repo takes <1 min; a test merge adding a tracking SDK produces a legal-relevance flag with a plain-English explainer (what the code does, why it's legally relevant, recommended action) within one cycle; a fact-gathering question routes to engineering (Smarter queue where available).
- Earned autonomy: a minor doc-class accumulates shadow-mode agreement stats; enabling autonomy for it works; a simulated disagreement auto-demotes it to review-required; the ledger percentages render on the Legal tab.
- Triggered action: a change implicating a license requirement routes into the Apparently workflow (or the lite toggle path) with its full deadline chain (preliminary notice + filing + confirmation) on the calendar.
- Removal scrutiny: deleting a data-export feature triggers the removal checklist (user-rights, retention, sunset notice) with explainer.
- CADE + benchmark: a material ToS redraft shows committee-scored drafts and a competitive-terms score vs stored competitor snapshots that beats parity on flexibility/protection.
- `REPORT-legal-radar.md`: walkthrough of each acceptance item + KPI baseline (legal review minutes per change, drift flags found in existing apps — report these immediately, they're the fastest value).
