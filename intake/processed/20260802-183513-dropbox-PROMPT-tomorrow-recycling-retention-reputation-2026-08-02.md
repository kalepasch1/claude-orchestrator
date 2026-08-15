# tomorrow (+apparently bridges): Value recycling + agentic auto-deploy, retention engine, residual-risk grade, reputation fabric, displacement swarm — perpetual-spine v1 EXTENSION (operator directive 2026-08-02, APPROVED)

SUBMITTED-BY: kale@smrter.us (operator) via Cowork strategy session 2026-08-02. Operator has APPROVED this document in full — build it.

BINDING POSTURE (restated): N4 advisory/stale/non-price-forming pricing. N5/N6 — never a pool/CCP/mutualization; multilateral discovery only; execution = named bilateral legs, all-or-nothing consent. No house/affiliate capital ever fills a leg. Zero-spread RUM revenue only. Ledger separation (platform accounts never touch event-contingent money). Non-custodial payment rails (instruct, never hold). Extends PROMPT-tomorrow-perpetual-spine-v1-2026-08-02 and PROMPT-tomorrow-strategy-fixes-2026-08-01 — where overlapping, extend/verify, do NOT duplicate.

## 0. AGENCY POSTURE (operator correction of record — binding, resolves a prior mischaracterization)
- The USER'S OWN relationship agents/bots negotiate and execute on the USER'S behalf under the user's own mandate. Tomorrow does NOT exercise discretion over user accounts, does NOT act as a discretionary manager, and does NOT issue "platform recommendations" that it then executes.
- Quotes/IOIs are BOT-TO-BOT indications arising from real agentic counterparty relationships (relationship agents on each side), not platform advice. Language across code, UI, and docs must reflect this: "your agent", "counterparty agent", "agent-negotiated IOI" — NEVER "our recommendation", "we execute for you", "managed account".
- Consequence: NO CTA discretionary-authority/Part 4 discretionary-account gate applies. Auto-deploy (§2) ships ENABLED — no further approvals required. Conservative defaults at onboarding, user-selectable up or down.
- Evidencing: every agent action records principal (user), agent identity, mandate id/version, consent bands, and counterparty agent — persist via agent_identities / agent_mandates / mandate_execution_authorizations / a2a_messages / agent_activity_log with full audit chain. Purge any residual "discretionary"/"we recommend then execute" framing found in code or copy.

## 1. Payout recycling — Coverage Credits (two custody-clean lanes)
- Same-pair lane (DEFAULT): payouts book as Coverage Credits inside the user↔capacity netting set, offsetting future funding fees, retentions, and new-position obligations BEFORE any cash instruction issues. A credit is at all times an obligation of the named capacity provider — never platform value, never a platform liability. One-click "withdraw instead" always present (lets the instruction issue on the next cycle, or off-cycle above threshold).
- Cross-pair lane: to apply fund A's payout against a position with fund B, credits sweep by auto-instruction into the USER-TITLED custodian sub-account (same account as prepaid cycles and retention pre-funding) and serve as collateral/prepayment to any counterparty. Tomorrow instructs; user owns; no platform custody.
- Credit objects: origin trade, age, expiry (if any), lane, current application, full lineage to the payout event and its oracle attestation. Terminology: "Coverage Credits" — never betting/house-money language in product copy.
- CI invariants (extend existing suite): a credit exists ONLY as (a) a netting-set entry against a named capacity provider or (b) cash in a user-titled custodian account; no credit is ever a platform-account balance; no payout originates from a platform account.

## 2. Agentic auto-deploy — the Risk Reflex (SHIPS ENABLED; user-agent mandates, per §0)
- The user's relationship agent deploys Coverage Credits autonomously under the user's own standing mandate — the user-side mirror of capacity-side band-consent mandates, on the same Mandate/authorization rails. Execution stays named-bilateral: the user's agent and the counterparty's agent agree an IOI inside pre-consented bands; nothing executes outside a band.
- Mode A — Next-best hedge: on credit arrival, the user's agent computes highest risk-reduction-per-dollar across the user's quantified exposure map (extend position / tighten retention / open top-ranked unhedged exposure) and negotiates + executes within mandate bands.
- Mode B — Risk reflex (deploy on incurrence): when a steering choice in the build creates a new identifiable risk (Illuminati/CADE flag → trigger spec generated in real time), the user's agent binds coverage for that specific risk at the moment it is incurred. Risk creation and risk transfer become one event. This is the platform's signature capability — surface it prominently.
- Mandate configuration surface (full user control): mode (off / propose-to-me / auto), per-deploy and per-period caps, theme/jurisdiction filters, structure preference (retention-first | extend-first | new-hedge-first), max funding-rate bands, confirm-threshold above which the agent pauses for one-tap owner approval, cooling-off window, instant kill switch, complete audit trail of every agent action and counterparty-agent exchange. Onboarding default: conservative auto (low caps, tight bands) — not off, not unlimited.
- Reuse mandate_edit_cooling_off, HiveMandateChangeLog/Attestation, conviction/negotiation rails; no new consent primitives.

## 3. Retention Engine — tail-first as the DEFAULT product (flagship)
- Retention ladder on EVERY quote: interactive retention↔rate ladder showing the swap funding rate (ECP) or the LOC keep-open/premium rate (non-ECP wrapper) falling as retention rises, recomputed live from the factor model. Tail-first is the DEFAULT selected position; first-dollar coverage is the expensive opt-in. Target effect: 40–70% lower carrying cost at default.
- Structures: attachment-point (pays above X) and franchise (pays in full once X breached) variants; exhaustion cap Y sized to quantified exposure; corridor structures for sophisticated users. Applies to BOTH wrappers — swap rate reduction for ECPs, LOC premium/keep-open reduction for non-ECPs — with the retention expressed loan-side as an uncovered first-loss band, not as a swap term.
- Optimal-retention advisor: from the user's loss distribution compute and display the efficient point ("optimal retention $85K — 96% of tail-value protection at 34% of first-dollar cost"), with methodology one tap away.
- Dynamic retention (posture-linked): retention tightens automatically as compliance posture improves (CADE/Consilium, Illuminati telemetry), recomputed AT RESETS within pre-agreed formula bounds so it remains a lifecycle event, never a re-execution. Deterioration may widen retention only at reset, within bounds, with advance notice — never mid-period.
- Credit-funded retention: Coverage Credits pre-fund retentions ("your protection is self-funding" — computed, not promised).
- Capacity-side: publish per-theme retention→rate curves as part of the funding-curve data product; give attachment-point bundles priority slots in capacity auctions; let funds bid retention floors alongside rates (second competitive dimension).
- Terminology discipline (hard): "retention", "attachment point", "exhaustion" in all contracts/UI. NEVER "deductible", "premium" (in swap context), "policy", "insurance", "coverage limit" as terms of art in legal documents.

## 4. Value telemetry (reinforcement layer)
- Three ledgers on one screen: (a) REALIZED — all payouts earned/paid lifetime + period, net of funding fees; (b) ACCRUAL — synthetic/predicted period P&L accruing in real time as event probabilities move (hivemind + factor model), per position and per book, rendered as live accrual bars; (c) RISK REDUCTION — headline meter: "this month your positions reduced modeled loss exposure by 90% / $152,000", computed from expected_loss_usd with and without the book, methodology one tap away.
- Display compliance built into the components (not a legal page): advisory/N4 labels, two-sided rendering (predicted cost shown beside predicted payout), no profit framing, no guarantees. NFA 2-29 checklist attaches to each component.
- Board-report export: one-click PDF/live-link artifact — residual exposure after coverage, program cost, credits earned — feeding §5.

## 5. Residual Risk Statement + Residual Risk Grade (RRG) — marketplace asset
- Residual Risk Statement: live, receipt-verified statement of regulatory/legal exposure after coverage, retentions, and credits. Four views: private (operator), board, investor, consented-public. Machine-readable — stable JSON schema + signed verification link — so VCs, lenders, and vendor-diligence teams ingest programmatically.
- Residual Risk Grade: graded mark (A–F) with subscores (coverage ratio, retention adequacy, posture, concentration), versioned methodology, receipts. Embeddable badge ("Tomorrow Protected · RRG A−") for websites, decks, vendor-security pages; every verification click lands on the marketplace. Ship badge via the same signed-embed mechanism as the Apparently Law doc fabric (PROMPT-apparently-law-docfabric-tomorrow-2026-08-02) — one embed system, two content types.
- Consented public directory of protected companies by sector/grade: social proof for the hedger funnel + origination surface for capacity (funds browse as deal flow). Consent-gated, revocable, version-hashed.

## 6. Reputation fabric — netting credit inside the composite
- Keep the netting-set reputation credit as its own contract-grade ledger (settlement timeliness, cure history, dispute record) AND feed a unified counterparty reputation composite: CONDUCT layer (netting/settlement ledgers, recert/covenant compliance, disclosure quality, agent-negotiation conduct) + POSTURE layer (CADE/Consilium, exam readiness, remediation velocity). Every metric versioned, receipt-backed, separately queryable; composite computed by published methodology.
- Contract-grade metrics: LOC program agreements and bulk LOI / standing-capacity agreements incorporate defined score formulas BY REFERENCE with methodology-version pinning and audit rights (templates drafted in the Apparently Law doc fabric).
- Reputation-priced capacity: fund mandates specify auto-fund bands per score tier, so a score improvement instantly expands standing capacity and tightens retention floor — notify in-product at the moment it happens ("score → A−: standing capacity +$250K, retention floor −15%").

## 7. Insurance displacement swarm + calculator
- Standing swarm agents per line (D&O, tech E&O, cyber, contingent legal/JPI, R&W, tax, parametric) continuously capture, normalize, and citation-tag PUBLIC/PUBLISHED sources into a live displacement dataset: NAIC SERFF rate filings (per-line, per-state), broker market indices (Marsh/Aon/WTW quarterly pricing reports), carrier statutory filings and loss ratios, published benchmark surveys, law-firm alerts on JPI/contingent pricing, specimen policy libraries for exclusion mapping. Every comparable carries source + date + confidence; staleness decays confidence; hivemind flags market moves. Reuse the existing watch/corpus/editorial-source machinery — do not build a new crawler stack. NO paywalled/confidential scraping.
- Displacement card at every quote: comparable insurance path (cited premium range, applicable exclusions, claims friction, no credits, no recycling, no instant binding) beside the Tomorrow structure (rate, retention, credits, agent-bound coverage, transparent trigger). Where no comparable exists, say so explicitly — "no insurance market writes this risk" — as a cited finding.
- Same dataset powers: (a) the displacement card, (b) a licensable insurance-market-intelligence feed for capacity, (c) the Apparently Cost-Displacement Projections page evidence base.

## 8. Market rhythm + custodian program (carried from approved spec)
- The Monthly Funding Fix: netting settlement date doubles as the market event — settlements net, funding curve prints, capacity-auction results publish, predicted-IOI calibration scores update, consented case-study drops ship. One branded day; automate via the editorial rails.
- Auction clearing rates seed the OFFICIAL funding curve (real prints are the spine; predicted IOIs are interpolation and must be displayed as such, with realized-vs-predicted calibration, e.g. "6-month predicted IOIs within 11bps of cleared").
- Referral/case-study engine: consented outcomes from filled users render as two-sided assets (hedger stories for the funnel, book-performance stories for capacity) with validation badges ("priced by N institutional counterparties"). Consent captured in transparency-room flow, version-hashed, revocable.
- Custodian sub-account program: ONE user-titled account serving prepaid funding cycles, cross-pair credits (§1), and retention pre-funding (§3). Tomorrow instructs only. Per-account fee handling configurable (pass-through or absorbed).

## 9. UI placement (into the seven-bucket nav from spine v1)
- Dashboard: credits balance + pending auto-deploys, risk-reduction meter, accrual bars, RRG tile, next Funding Fix countdown.
- Hedge: retention ladder on every quote + optimal-retention advisor; Coverage Credits panel; agent mandate configuration (§2) with kill switch always visible.
- Trade: retention-floor bidding in auctions; attachment-point bundle priority; reputation-tier auto-fund band configuration.
- Intelligence: displacement cards/dataset, retention→rate curves, funding curve + calibration, RRG methodology.
- Operations: custodian sub-account, credit lineage, netting statements.
- Compliance: reputation composite receipts, agent action audit chain, consent/version-hash records.

## PROOFS (vitest + e2e, all required)
- Credit invariants: no credit as platform balance; lane routing correct; withdraw path issues instruction and clears credit.
- Agentic auto-deploy: Mode A picks max risk-reduction-per-dollar within bands; Mode B binds within N seconds of an Illuminati/CADE risk flag; nothing executes outside mandate bands; kill switch halts instantly; every action records principal/agent/mandate-version/counterparty-agent; NO code path frames the platform as recommender-then-executor.
- Retention: ladder recomputes rate for both wrappers (swap funding rate + LOC keep-open); optimal point matches the loss distribution fixture; dynamic retention only adjusts at reset within bounds; credit-funded retention reduces cash-required to zero in the golden fixture.
- RRG: statement + grade reproducible from receipts; badge embed honors domain allowlist + revocation; public views strictly consent-gated.
- Reputation: composite recomputes from versioned metrics; score-tier change updates fund auto-fund band and retention floor and fires the notification.
- Displacement: swarm produces citation-tagged comparables with confidence decay; card renders "no comparable market" state correctly; no paywalled sources ingested.
- E2E golden path: risk incurred in build → user agent binds coverage inside mandate → adverse event attested → payout books as credit → auto-deploy funds a retention on a new hedge (zero cash) → telemetry shows realized + accrual + risk-reduction → Funding Fix nets, prints curve, publishes calibration → RRG updates → reputation tier improves → fund mandate expands standing capacity.

OPERATOR (logged, never queued):
- NFA 2-29 promotional review of retention ladders, displacement cards, RRG badges, telemetry components, and Funding Fix content.
- Custodian relationship + account-control agreement execution.
- Counsel review (via Apparently Law doc fabric) of: user-agent mandate terms, retention/attachment contract language, reputation metrics incorporated by reference into LOC/LOI templates, RRG public-disclosure terms.
