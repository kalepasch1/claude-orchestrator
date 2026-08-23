# apparently-law: the Uber-model expert network — triage router, contribution graph, financed onboarding, Guild, clause-level routing

SUBMITTED-BY: kale@smrter.us (operator/counsel) via Cowork strategy session 2026-07-28. Strategy reference: PORTFOLIO_STRATEGY_V2 Part 10 (beethoven repo root — READ 10.1-10.4 before building). (Rename to PROMPT-… to activate AFTER the apparently-law site wave has landed in dev.)

WORKFLOW: governed_heavy

Operating model of record (REVISED round 8 — strategy 11.4): Apparently Law is NOT a traditional firm — it is a minimal firm shell + an Uber-model network: AI handles volume → triage routes what needs a human → independent network attorneys take it under their own licenses → token settlement. **LAUNCH POSITIONING: Apparently Law launches as a GAMING LAW FIRM — the best in the market** — aligned with the Apparently beachhead. The anchor expert ("Brian" operationally) + the full gaming stack IS the brand at launch; other specialties layer in as experts join Apparently/Smarter (membership perk / embedded BD allowance). Launch-week productized offers: (1) sweeps-memo audit ("bring your existing counsel's sweeps memo; we'll show what's already wrong and keep it right forever" — prove-then-complete applied to competitor work product, converts + harvests the stale-advice demand map), (2) license-expansion scan (X/100 optimizer), (3) NAL/comment request drafting (winning-argument corpus). Enforcement-defense standby lines sold next to the risk (Tomorrow S2S).

CORPORATE STRUCTURE (11.4 — build the paper + entitlements to this shape; counsel holds the pen): firm = PLLC/PC owned by the anchor attorney (Brian) — operator holds NO firm equity while at Skadden; a Darwn subsidiary ("Apparently Law Brands LLC") owns ALL IP (brand/marks/processes/playbooks/tech) and grants the firm a TERMINABLE EXCLUSIVE LICENSE + arm's-length managed-services agreement (economics flow as license/service fees, never a share of legal fees — 5.4-clean); termination/step-in + successor-owner mechanics keep the brand durable and the shell replaceable; client files/privilege belong to firm/clients (non-negotiable) with platform hosting/processing + k-anonymized derived-data rights via engagement consents; ABS variant config-gated for the operator's post-Skadden step-in. CADE generates the full paper pack — and templatize it: this architecture is the franchise template Apparently OS boutiques adopt (11.8.5).

ECONOMICS: the recruitment model + pitch (item 9) must implement the reviewed model in /Users/kpasch/Documents/beethoven/APPARENTLY_LAW_NETWORK_ECONOMICS_2026-07-28.md — including its honest demand-constraint caveat (recruit behind demand, never ahead) and the adopted message: "we pay for what only you can do; the rest is priced by the market." Use its scenario/sensitivity tables as the pitch-page math.

## 1. Matter triage router
- Apply the workflow-router pattern (see claude-orchestrator/runner/workflow_router.py for the shape) to MATTERS: classify each incoming matter/deliverable unit by specialty, novelty (corpus-answerable vs novel), risk grade, and route: AI-only → AI+expert-review → expert-led → anchor. Deterministic + overridable; every routing decision logged with rationale (attribution rules apply).
- Proof: fixture matters route correctly across all four lanes; override honored; routing log written.

## 2. Independent network attorney onboarding (solo-friendly)
- Onboarding flow for independent attorneys: bar credential verification, specialty tags, jurisdiction admissions, malpractice cert upload (or enrollment in the network-arranged program), engagement-letter templates naming the attorney as counsel + platform as technology/administration provider, platform-wide conflict registration (reuse apparently's coi-checker engines via S2S). No per-attorney firm entity required.
- Proof: fixture solo onboards end-to-end; conflicts check runs platform-wide; engagement letter generates with correct counsel-of-record naming.

## 3. Platform-fee ladder + signing advance (10.1c — COMPLIANCE-CRITICAL, read carefully)
- DO NOT build revenue/profit-sharing with the platform (Rule 5.4 outside ABS). Build the inverted structure: attorney keeps 100% of legal fees; platform charges a TIERED PLATFORM FEE (AI stack, triage, client flow, malpractice program, back office) that STEPS DOWN with trailing collected volume + network-value score: 20% base → stepping down to 10% at $1MM+ trailing (exact breakpoints config-driven). Network-value rebates (item 4) further reduce the fee.
- Signing advance: a payback-contingent advance ledger (bar dues, malpractice premium, setup costs) — forgiven on schedule against active-network months, repaid ONLY from network earnings otherwise. Ledger + disclosure docs via the CADE doc engine.
- ABS variant (AZ): a config-gated alternate structure where true profit-share/equity is permitted — default OFF, counsel flips per jurisdiction.
- Proof: fee computation tests across the ladder + rebate interactions; advance accrual/forgiveness/repayment ledger tests; ABS variant gated off by default; grep confirms no revenue-split code path in the default structure.

## 4. Contribution graph + network-value scoring (10.2a)
- Per-member score composed from: legal quality (revision acceptance, outcome results, errors found-vs-caused), converting introductions (client referrals, partner intros — tracked to conversion), convening power (verified meetings organized, e.g. with regulatory officials — hook the regulatory-interaction studio calendar), responsiveness/communication quality (Smarter timing/tone signals via S2S), corpus contributions, Guild mentorship. Score drives: token pricing of the member's time, platform-fee rebates, routing priority, and directory placement.
- Intangibles are FIRST-CLASS: an intro that converts pays like work product. Every scored event is attributed + auditable.
- Proof: score computation from fixture event streams; each component moves the score; rebate hook into item 3 verified.

## 5. Hedge-capped pricing surface (10.2b)
- On any deliverable with a CEPL grade + available hedge quote (Tomorrow recommendation gate via S2S): display the residual-risk transfer cost alongside expert-enhancement pricing — the UI makes explicit that marginal-certainty value is capped by the hedge price. Expert pricing bands for corpus-answerable work are anchored to it; novel/long-tail work (no trigger exists) and relationship work are uncapped.
- Proof: fixture deliverable shows hedge-capped band for standard work and uncapped band for novel-flagged work.

## 6. The Guild v1 (10.3 — UPL-safe)
- Student membership: verified enrollment, scoring, token wallet. v1 task types (STRICTLY non-practice): adversarial QA bounties ("beat the AI" — findings feed the eval corpus), proofreading/cite-checking queues, document sourcing for the omniscience corpus (verified-source submissions), tool-building on our skills surface, papers/scoring-model submissions. NO legal advice tasks, NO client counseling. Token rates scale with member scoring; leaderboard; "matched with an expert" pipeline flag at score thresholds.
- Proof: task taxonomy enforced (a practice-shaped task cannot be created); bounty finding round-trips into the eval corpus; scoring/rates/matching flags work on fixtures.

## 7. Clause-level expert routing v1 (10.4)
- On multi-specialty matters: decompose via the CADE inbound unit engine (contestable units) → route units to best-scored niche experts at per-unit token prices → coordinating expert holds the whole → reassembled deliverable records per-unit expert provenance. v1 can require manual confirmation of the proposed unit-expert map.
- Proof: fixture multi-specialty document decomposes, routes to 2+ fixture experts, reassembles with provenance.

## 8. Expert-enhancement rung on prove-then-complete (10.2c)
- After AI completion of any deliverable: offer expert enhancement (tokens, priced by score) — insights, judgment, intro attachments, elevation. Dual provenance recorded (AI + expert layers). This is a generic rung — build it on the shared prove-then-complete primitive so Consulting/Wealth reuse it.
- Proof: enhanced deliverable carries both provenance layers; pricing pulls from the contribution graph.

## 9. Recruitment economics + pitch surface (10.1d)
- Build the economic model as a real artifact: network earnings distribution vs big-law comp by seniority/specialty (Cravath-scale reference data), break-even volume per recruit, sensitivity to token pricing — rendered as an internal dashboard AND a public-facing recruit pitch page ("what you'd keep here vs. what you keep there"), honest assumptions disclosed.
- Proof: model computes from config inputs; pitch page renders scenario sliders.

## 10. Round-9 additions (strategy 12.2-12.5)
- CADE PAPER PACK: route the full drafting of the Darwn/Apparently Law pack through the CADE doc engine using /Users/kpasch/Documents/beethoven/DARWN_APPARENTLY_LAW_PAPER_PACK_2026-07-28.md as the drafting contract — all 7 agreements + engagement-letter consent language + the parameterized FRANCHISE TEMPLATE variants (any OS boutique inherits the architecture). Drafts land for operator review; never auto-execute.
- THE SURVIVAL FRAME LEADS (round 10; strategy 13.1 + econ doc §5d): every recruit surface opens with the urgency thesis — partners are replacing associates with AI right now; the choice is "be replaced by the AI, or be the one who owns it." Campaign line: "They're replacing you with AI. We're arming you with it." Survival first → hours calculator second → income multiple third. Include the PMI displacement-barometer hook (recurring data piece on AI displacement in big law; coordinate with the PMI Publius engine).
- HOURS-WORKED MARKETING: recruit surfaces use the hours-WORKED basis (2,200-2,500 big-law reality) + the "Hours of Your Life" calculator (class year + hours → side-by-side income AND hours) per the updated econ doc §5b. Quality-of-life is the emotional core; income multiple the proof.
- PAPER-PACK DELIVERY (13.4): on completion, route the CADE drafts through the Smarter formatting swarm and deliver the final formatted documents into the operator's Smarter workspace (kalepasch@gmail.com) as a review collection with notification — never auto-execute.
- MID-LEVEL CENTER (12.3b): dual-track recruiting — 3-5 yr associates as the volume engine (supervision layer via routing rules), blocked seniors as matter owners. Mid-level pitch page: "you already do the work — keep the credit, the client, and 80-90% of the fee." Track-specific economics pages from econ doc §5c.
- AUTONOMOUS CAREERS ENGINE (12.5a): when routed matter volume in a specialty approaches expert capacity, auto-generate Apparently Law careers listings (track-specific) and/or boutique-recruitment listings ("bring your AI-native firm onto the network — franchise architecture included"); publish to the careers page; applicants flow into network onboarding. Hiring driven by demand telemetry.
- THREE PRACTICE VERTICALS AT INCEPTION (12.4a-b): (1) Gaming (the launch brand); (2) Regulated Financial Services page — CFTC/SEC/OCC/FDIC/Treasury/state lending/MSB/FinCEN, "AI-native regulatory & compliance counsel for regulated finance," wired as the Illuminati upsell landing; (3) AI & Data Regulatory page (EU AI Act, state AI, privacy — every Illuminati customer is this client). FDA/defense as "opening 2027" teasers only.
- Proof: CADE pack drafts generate from the term-sheet contract; calculator renders both tracks; a fixture demand spike auto-generates a listing; three practice pages live with correct funnels.

## Constraints
- All fee/advance/trust-adjacent code is MATERIAL (stamped). No client trust accounting in this pass (operating-account flows only; IOLTA is a later, counsel-designed pass). Apparently CLAUDE.md conventions; ai-call-logger; RLS default-deny; no secrets.
