# Portfolio Simplification v2 — 2026-07-09 (operator-feedback pass)

Supersedes item-level content in `REVIEW-portfolio-simplification-2026-07-09.md` where they conflict. Incorporates operator direction: Tomorrow pushed hardest; Pareto/Galop objections accepted as directed (designs made posture-agnostic); Smarter S4 rebuilt per direction (non-user scoring first); Triage rebuilt on the original model. Still **not** queued — cherry-pick into `PROMPT-*.md` files.

Standing note, once: I'm not a lawyer/financial advisor; the structuring concepts below (default fund, SEF avoidance, regime swaps, non-user scoring) need counsel sign-off as standing legal artifacts (B22 pattern) before build.

---

## 1. TOMORROW — v2

### On "arbitrage / risk-free profits" — the precise version, because precision is the weapon
There are four *real, harvestable surpluses* in this system, and naming them precisely is what makes the pitch unkillable:

1. **Netting surplus** (risk-free, genuinely): when N bilateral exposures form a reducible cycle, compression releases margin/capital with zero new risk. This surplus is created by the *network*, and Tomorrow decides how it's split. Participants experience it as free money — because for them, it is.
2. **Fragmentation spread**: bilateral OTC prices are dispersed; a party standing between two mispriced bilaterals captures spread. Near-riskless when simultaneous and offsetting — this is the "arbitrage" ECPs will feel, and the swarm should *manufacture these opportunities and hand them to participants* (see T6v2) rather than keep them, because distributed arb profits are the acquisition engine.
3. **Funding dislocations**: perp funding rates vs. realized drift — harvestable by bots and by ECPs who take the balancing side.
4. **Diversification premium**: pooled tail risk is cheaper than the sum of individual tails; the delta is distributable.

So: "massive earnings potential" = engineered distribution of (1)–(4) to participants. That's honest, defensible, and *no competitor even measures these four numbers*. Instrument them (B20 receipts) and publish per-ECP "surplus captured" statements monthly.

### T2v2 — Synthetic default fund, zero custody, embedded in the paper itself
Design goal per operator: no pooled funds, no custody, minimal regulatory surface.

- **Mechanism — the Mutualization Clause**: every contract on the platform carries a standard clause in which each party pre-commits a *contingent bilateral obligation*: on a defined default event anywhere in their ring/mesh (objective trigger: missed settlement > X hours, verified by the multi-source settlement validator), each non-defaulting member owes the affected party a pro-rata assessment, capped (e.g., 25bps of their gross notional). No fund exists; the "fund" is a lattice of standing contingent obligations that nets through the same settlement rails as everything else.
- **Equivalent event-contract form**: each participant, as a condition of membership, *writes* a small default-contingent swap (payout on "member default event") to a rotating basket of counterparties. Same economics, expressed as an instrument the platform already knows how to price, margin, and settle — and B15's credit gate auto-prices each member's contribution (riskier members write more protection or pay wider).
- **Self-pricing credit market as a bonus**: because default-contingent swaps now exist per member, their live prices ARE the credit spread — feeding B19's underwriting score with a market-implied input no competitor has.
- **Waterfall**: defaulter's margin → defaulter's own pre-committed penalty (B15 portable penalty) → mutualization assessments → only then loss allocation. Model it: at plausible densities the assessment layer makes bilateral LGD ≈ 0.
- **Regulatory footprint**: no custody, no separate fund entity, no discretionary claims-paying — it's contract law between ECPs. That is the *best available* shape; it is not a guarantee of no characterization risk (clearing-like mutualization is exactly what regulators look at). Ship the clause pack through B22 with a counsel opinion attached as a receipt, and gate activation on it (fail-closed, per house rules).

### T3v2 — Subscription-only, zero transaction fees: yes, and here's why it's a kill-shot
Analysis of the model flip:

- **Incentive inversion**: per-trade fee venues earn from churn and are *structurally opposed to compression* (every netted trade is lost revenue). A subscription venue is the only venue that can run T1's compression cycles aggressively — competitors literally cannot copy this without cannibalizing their P&L. This is the moat, state it exactly this way in sales materials.
- **Pricing axis**: tier on **Risk Under Management (RUM)** — gross notional under perpetual protection — not trade count. RUM grows as the lifecycle loop (B8) does its job, so revenue compounds with client success, not client activity.
- **Comprehension**: "flat monthly fee, all your risks stay inside your declared budget, forever" is explainable to a CFO in one sentence. Complex swap menus become an implementation detail the client never sees (pairs with B6 mandate collapse: the subscription *is* the mandate).
- **Guardrails**: usage governors (compute/novelty budgets per tier) so a subscriber can't spin unbounded exotic structuring; overage priced as tier upgrade prompts, never per-trade.
- **Tiers sketch**: Protect (hedging program only) → Protect+Earn (adds surplus-harvest participation, (1)–(4) above) → Protect+Earn+Legal (adds T4v2 regime coverage) → House (white-label the whole stack to a bank/originator, B21 outbound as the funnel).
- **Economics check**: model breakeven RUM per tier against bot compute + mutualization exposure; the continuous AI analyzer already tracks per-org cost. Add a `subscription-economics` engine with backtests before pricing goes live (G8 eval-gate pattern).

### T4v2 — Regime Perpetuals: protect the *validity of the paper*, not the counterparty's option
Refocused per operator: the unit of coverage is **"does this clause/structure remain valid law in this jurisdiction"** — DE banning non-competes, MA declaring sweeps casinos illegal, an agency reinterpreting ECP scope — not whether a party exercises a right.

- **Product shape**: one-time issuance + ongoing subscription (fits T3v2 tiers) per (clause-family × jurisdiction). Two legs:
  1. **Monitoring leg** (subscription): the regime-event oracle (below) watches every relevant docket/register/legislature; client's contracts are tagged to clause-families so exposure is computed automatically from their actual paper.
  2. **Swap leg** (payout): on a regime-change event — good or bad, per operator — a pre-agreed settlement pays, sized to re-papering cost + exposure delta. Symmetric payouts (you pay in when regime moves *in your favor* on covered positions) keep it a swap between ECPs, not one-way indemnity — this is also the structural argument that it's a derivative, not insurance.
  3. **Remediation leg (the law-firm killer)**: payout is not just cash — the event auto-triggers Apparently to re-draft every affected contract and Smarter to run the amendment workflow with counterparties. "A memo tells you the law changed. We pay you AND your paper is already fixed by Friday." Law firms sell point-in-time opinions with no forward liability; this is perpetual validity with a balance-sheet consequence for being wrong. No firm can match it without becoming a derivatives counterparty.
- **Regime-event oracle**: multi-source (court dockets, legislative APIs, agency registers, gazette feeds) through the existing multi-source settlement validator with quorum rules; every determination minted as a signed receipt (contestable, auditable). This oracle is a *shared kernel service* — see X2, it also powers Apparently A1 and Pareto P4v2.
- **Issuance economics**: who takes the other side? (a) parties with opposite regime exposure (a MA sweeps operator vs. a MA sweeps skeptic-investor — natural two-way market), (b) the mutualized lattice (T2v2 mechanism reused for regime events at small size), (c) Tomorrow's own book, capped and hedged across jurisdictions (regime events are near-uncorrelated across states → the portfolio is the hedge).
- **Data moat**: Smarter's clause corpus + Apparently's requirements graph give base rates for regime-change probability that no one else possesses. T5v2 publishes the curves; T4v2 monetizes the tails.

### T5v2 — From index to ratings agency
Publish the **Enforceability Curve** family (probability of adverse regime change, by clause-family × jurisdiction × horizon), then: license to insurers/underwriters, embed scores in Apparently drafts ("this clause: AA validity, 0.4% 5-yr adverse-regime prob"), and sell law firms the terminal they'll resent needing. Long-run: the "Moody's of contract validity," with T4v2 as the tradable layer on top — the classic index → derivatives → clearing progression, but for law.

### T6v2 — Swarm economy without the SEF trap: the Bilateral Choreographer
Constraint honored: no multilateral RFQ, no many-to-many quote interaction; multilateral *benefit* via a large volume of bilateral relationships.

- **Architecture**: split brain from mouth. A central **choreography solver** (sees the whole mesh) computes the globally optimal *set* of bilateral trades — but no participant ever sees a multilateral book. Execution is strictly sequential/parallel *one-to-one* negotiations run by relationship bots using existing friendly-DNA state. Bots never broadcast a quote to >1 party; IOIs are one-to-one; firm quotes are responses within an established bilateral relationship.
- **The arb hand-off (feeds surplus #2)**: when the solver finds a fragmentation spread, it doesn't cross it centrally — it *routes the opportunity to a participant* as a pre-packaged pair of bilateral trades ("accept both, lock X bps"). Participants experience recurring near-riskless pickups; Tomorrow takes no principal risk and stays out of the execution-facility frame. Rotation/fairness policy for who gets handed opportunities = loyalty lever (tie to subscription tier).
- **Internal netting before external**: bots submit priced intents to the solver; offsetting intents cancel internally as bilateral trades between the bots' principals. External venues only see residuals.
- **Standing legal artifact**: the choreography spec (what the solver may/may not do, quote-dissemination rules) is a versioned document with counsel sign-off, enforced in code by the kernel constitution (deny `multiparty_quote_broadcast`), tested like B12's gates. Facts-and-circumstances risk remains; the spec + receipts are the defense file, pre-built.

### T7v2 — Inbound package ⊕ subscription quote ⊕ live re-ingestion
- Upload trial balance / loan tape → exposure catalog maps it → output is a **priced T3v2 subscription quote** (tier, RUM, projected surplus capture, mutualization contribution) with one accept button. The quote page IS the onboarding (B6/B21 fused).
- **Live balance sheet**: post-acceptance, link ERP/loan-system/data-warehouse pipes (mirror of Apparently A7's repo-linking — build the connector layer once, X2) so the hedging program follows the books continuously. Client never re-uploads; drift in their business auto-adjusts the program (B8 loop consumes the feed).

### New Tomorrow concepts (not previously listed)
- **T8 — Counterparty-gravity rebates**: subscription credits for bringing counterparties into the mesh (each new member raises everyone's netting surplus — quantify the marginal surplus per join and rebate a slice of it; provable via receipts, so the rebate is literally funded by measured surplus).
- **T9 — Origination embedding**: B19's underwriting score extended into an API for loan-origination/booking systems: every new contract a client signs *anywhere* arrives pre-hedged (hedge quote at the moment of origination). Distribution wedge: be in the workflow before the risk exists.
- **T10 — Public proof network**: publish aggregate, client-consented avoided-loss and surplus receipts on a public verifier page (G2 service). Competitors can't answer verifiable numbers with brochures. This is the marketing site.
- **T11 — Own-industry regime coverage**: T4v2 pointed at the client's *operating* risk (their license regime, their sector's rules) using Apparently's requirements graph as the underwriting base. A gaming operator buys MA-sweeps regime coverage from the same subscription that hedges their FX. Nobody else has the two datasets in one house.

---

## 2. APPARENTLY — v2

### A4v2 — Behavioral learning as default (per operator direction)
Default-on learning from anonymized behavior/text, no per-event consent. Build it so the default survives scrutiny:
- **Scrub-before-learn pipeline**: PII/IP/client-identifier strippers run *before* anything enters the learning store; the kernel mints a receipt per learning event proving what fields were dropped (auditable "we only learn process, never content" claim). ToS disclosure + a visible opt-out toggle; keep an EU/UK legitimate-interest assessment on file since anonymized-behavioral learning still gets asked about there. The receipt trail is what lets you keep the default.
- **Dividend made visible**: firms see "your lanes are N% faster because the network learned X" — turns the default from a suspicion into a perk (I3's cooperative economics, surfaced).

### A6 — Deadline Omniscience (new, per operator)
Not just final deadlines — the **full lifecycle ontology**: pre-application windows, intent-to-file notices, comment periods, exam scheduling windows, fingerprint/background expiry, renewal look-backs, fee schedules, publication requirements.
- **Invariant: no silent deadline.** Every dated obligation has (a) an owner (bot or human), (b) a countdown ladder (T-90/T-30/T-7/T-24h escalating through channels), (c) a **dead-man switch**: if completion isn't *verified* (not just claimed) by T-x, auto-escalate to the accountable officer AND open a Smarter validation matter. Missing a deadline should require defeating three independent mechanisms.
- **Autonomous ops feed**: user-visible timeline of everything the hive did/will do (P0-RECEIPTS surface): "collected 14 documents, drafted 3 filings, 2 awaiting your officer sign-off, next hard date Aug 4 (NMLS window opens Jul 20)." The *watching the machine work* view is the retention product.
- **Completeness engine**: per-filing checklist synthesized from the requirements graph; submissions blocked (fail-closed) until every element is present or an explicit officer waiver receipt exists — "all information always provided in full" as a lint, not a hope.

### A7 — Filings-as-Code (new, per operator; this is the 100X item)
Link GitHub repos, data pipelines, and product configs to the licensing system:
- **Change classifier**: webhook on merge → diff classified against a map of (product surface → filing sections affected). New payment flow merged? The money-transmitter application's flow-of-funds exhibit regenerates itself and diffs are shown like a PR.
- **Continuous compliance integration**: filings become build artifacts with CI gates (reuse G8's eval-gate pattern): a filing "build" fails if repo state and filing text diverge. Submissions are always current *by construction*.
- **Cross-team sign-off via Smarter**: each regenerated filing opens a Smarter validation workflow — compliance, engineering, legal each confirm their sections (C4 bridge, pointed at Apparently); reminders ride the A6 countdown ladders; the final-submission receipt bundles all three sign-offs (H4 export pattern). "Advance notice + repeated reminders + verified final submission" as one pipeline.
- **Sales framing**: "your regulator filings are now CI/CD." No compliance vendor on earth talks like this; every VC-backed fintech/gaming company instantly understands it.

---

## 3. SMARTER — v2

### S4v2 — Counterparty & colleague scoring, non-users first (per operator direction)
Direction accepted: score non-Smarter users first; Smarter users see the scores; usable as validation/support.
- **Receipts, not opinions — this is what makes the weapon safe to hold**: scores derive from *verifiable workflow telemetry* Smarter already observes — turnaround times, missed commitments, error/redline-churn rates in documents, negotiation-stall patterns (C5's signal taxonomy, pointed inward). Every score decomposes into timestamped events. Opinion/sentiment inputs are stored separately, labeled as opinion, and never enter the headline score. Reason it matters for *your users*: a telemetry-backed score is a shield in a partner dispute ("here are 11 timestamped instances"); a vibes score is discovery ammunition against them. Same feature, but only one version survives being forwarded.
- **Conduct Receipt export**: one click produces a signed, chronological evidence pack about a counterparty/colleague interaction history — exactly the "support if challenged" artifact the operator described, in a form that helps rather than hurts the user producing it.
- **Right-of-response → conversion flywheel**: scored non-users get notified ("a verified professional-conduct profile about you exists; claim it to respond/improve") — the Glassdoor dynamic that converts the scored into users, which also (deliberately) migrates them into the protected-user class over time.
- **Opposing-counsel scouting reports (20X)**: every new matter auto-attaches the counterparty attorney's profile: median turn time, concession patterns, clause-fight history from the marketplace corpus. Junior associates open negotiations knowing the opponent's tells; feeds B13's ZOPA pre-computation.

### Unchanged-but-pushed
- **S1v2 — Matter exhaust → playbooks → sellable practice templates**: distilled playbooks become a marketplace SKU per practice area (anonymized, marketplace-pattern from Tomorrow's clause pool). New firm onboarding = "inherit 400 battle-tested matter playbooks day one."
- **S2v2 — Flagged-Only Workday + shadow associate**: the autonomous lane runs a *shadow duplicate* of every human-completed task for a while (G9 champion-challenger, applied to work product); when shadow ≥ human quality for a task class, that class auto-graduates to the autonomous lane (B7 trust-ratchet, applied to job functions). The 1000X path is measured, not asserted.

---

## 4. PARETO — v2 (posture-agnostic per operator; designs work under any regulatory arrangement)

- **P1v2 — Life state machine**: goals compile to a continuously re-planned state machine with Monte Carlo confidence bands; the user sees one map, one progress line, one knob (risk/ambition). Deviation-only interrupts (decision-budget doctrine). Every replan minted as a receipt with plain-language "what changed and why."
- **P2v2 — Full delegation firewall**: inbound mail/email/bill parsing → classify → act within graduated authority budget (trust-ratchet: $0 approval-only → $500 → unlimited-with-receipts). Auto-negotiation bots for bills/rates/fees; subscription-creep execution; dispute letters auto-drafted (P4 rails). Monthly single-card digest: "handled 34 items, saved $612, 1 needs you."
- **P3v2 — Micro-sweeps, daily**: harvesting, benefit windows, insurance re-shop, rate arbitrage on idle cash — run continuously at small scale rather than annually; a live "Pareto has paid for itself ×N" meter funded by signed savings receipts. This meter is the entire retention strategy.
- **P4v2 — Regime-aware household legal**: consume the X2 regime oracle — when a state changes rental law/estate rules, affected users' documents auto-update and they're told *before* landlords/counterparties know. Household legal protection as a subscription tier (same T3v2 economics: monitoring leg + remediation leg, consumer-sized).
- **P5v2 — Intergenerational mesh**: aging-parent graduated takeover protocol (mirrors trust-ratchet in reverse), estate continuity (documents + beneficiary sync always current), child financial-literacy lanes that graduate into their own Pareto accounts (and Hisanta reward-coins as the on-ramp — cross-app funnel).
- **P6 — Earnings-only interface (new)**: the end-state pitch, made literal: the only financial surface the user retains is income. Everything else — outflows, optimization, disputes, planning — lives behind the firewall with receipts. Market it exactly that way.
- **P7 — Crowd benchmark exchange (new)**: anonymized outcomes corpus ("what 4,100 users actually got when negotiating this hospital bill / this lease clause") powering negotiation bots with real base rates — the data flywheel competitors can't cold-start.

---

## 5. GALOP — v2

Per operator: full engagement/dopamine stack is in-bounds for **free play**; paid play gets none of the conditioning mechanics and instead gets production-grade reliability. (One line, once: I've kept variable-ratio reward schedules out of the real-money loop by design — free-play is where that machinery lives; the paid loop stays clean. Everything below is built to that split.)

### Free-play: the full modern engagement arsenal
- Streaks, daily quests, battle-pass seasons themed to racing calendar (Triple Crown season pass), cosmetic loot (silks, stable upgrades), variable surprise drops (cosmetic-only), leagues/relegation, limited-time events synced to real race cards, social co-op (syndicate free-play leagues, G5), calibration mastery tree (G1) as the *prestige* axis. Free-play is also the cold-streak landing zone (G2): a paid-play cool-down routes into free-play events so the session continues without spend.

### Paid play: real, live, boringly reliable, 24/7 — the production buildout (per operator)
- **Vendor integration matrix**: licensed ADW/wagering partner links, official tote/price feeds, settlement rails, per-jurisdiction geo/KYC (E1/E2 already gate this) — tracked as a live integration dashboard with per-vendor status.
- **Video everywhere**: contracted video sources per circuit (domestic tracks + international: JRA/HK/AUS/harness for overnight coverage), **multi-source failover** (primary/backup per race, auto-switch on stall), latency budget enforced.
- **24/7 verified-working invariant**: synthetic golden-journey probes every few minutes — place-bet, video-start, odds-refresh, settlement — across regions/devices; failures page on-call and auto-mint incident receipts; a public-facing status page. "It always works" is the paid-play brand promise and most ADW incumbents visibly fail it.
- **Fast, honest settlement**: settlement-time SLO with receipts; disputed-photo/DQ handling surfaced with explanation cards. Payout speed + explanation quality is the retention mechanic that needs no conditioning.
- **Bet-quality tooling in the paid loop** (allowed, additive): calibration score on real bets (G1), pre-bet "field context" card (pace/bias/class), post-race "what the winner had that your pick didn't" — improvement loop, not stimulation loop.
- **G4v2 (per operator's split)**: rerun/mystery content and auto-cut highlights are free-play only; the paid surface never presents synthetic/replayed events as bettable. Between live cards, the paid tab shows *upcoming* global races and analysis — feed density on the paid side comes from the global circuit calendar itself.

---

## 6. TRIAGE — v2, rebuilt on the original model (per operator)

Rebuilt from the original spec: healthcare workers report worst AND best colleagues; employers pay for flagged-risk intelligence + training pathways; unaddressed substantiated risk escalates to regulators; reporters earn from recruiting placements; premium, fun, cathartic, financially rewarding. Engineering below makes each of those pillars load-bearing at scale. One structural constraint kept from v1, because it protects the model itself: **regulator escalation fires automatically on substantiation age, never conditioned on whether the employer pays** — this makes the deterrent credible, keeps the platform out of coercion territory, and is *more* frightening to negligent employers, not less.

- **TR-A — The dual ledger.** Every clinician has two write-paths about colleagues: **Risk Reports** (incidents, patterns, near-misses) and **Gold Endorsements** (verified skill, saves, mentorship). Both are staked (below). The app leads with the endorsement economy publicly and the risk economy operationally — talent market on the front, safety intelligence in the engine room.
- **TR-B — Staked reporting: the "investment" mechanic, engineered for truth.** Reporters stake reputation-coin on every report. Stakes resolve against *outcomes*: corroboration by independent reports, employer investigation findings, later incidents, credential actions. Confirmed reports multiply the stake and reporter's credibility score; contradicted ones burn it. Add peer-prediction scoring (reward reports that match the *distribution* of what other independent observers report) so even unverifiable claims are truth-incentivized. This converts "paid negative reporting is unreliable" from a fatal flaw into the core game: the platform is a **prediction market on colleague risk**, and its calibration record is the sellable asset.
- **TR-C — Rage capture → evidence.** The catharsis moment, engineered: 60-second voice note at peak fury → AI structures it into an evidence-graded incident report (who/what/when/witnesses/severity), strips the venting, files the venting into a private journal the reporter keeps. The user gets the emotional release AND a report that survives scrutiny. Grade badges (Documented > Corroborated-pattern > Single-observation) shown everywhere a report travels.
- **TR-D — Employer product: the Risk Dossier + training rail.** Employers subscribe to unit-level risk intelligence; individual flags unlock with substantiation thresholds (k independent staked reports or 1 documented incident). Each flag ships with a prescribed remediation pathway (targeted training, supervision changes, credential review) and a clock. Employers who act clear the flag with a receipt; the dossier + response history becomes their defense file in litigation — that's the reason to *want* to be a customer.
- **TR-E — The escalation ladder (automatic).** Substantiated flag + no employer action within the clock → auto-file to the state board/federal channel with the evidence pack, and the employer's *inaction interval* is part of the record. Fully automated, receipt-proven, no discretion, no negotiation — announced to employers on day one. The business model is subscription + training marketplace; escalation is an invariant, not leverage.
- **TR-F — Recruiting exchange (the payout engine).** Gold Endorsements feed a placement market: endorsers of a placed clinician split the recruiting fee (healthcare recruiting fees are 20–30% of first-year salary — route the majority to the endorsing peers). High-credibility reporters (TR-B score) get larger splits: the same credibility currency powers both ledgers, so being an honest reporter literally raises your recruiting income.
- **TR-G — Unit safety-culture scores.** Aggregate staked reports into hospital/unit-level scores; talent flows toward high-scoring units through the exchange; low scorers bleed recruits and pay more — Darwinian pressure at the organizational level operating continuously, which is what actually moves patient safety.
- **TR-H — Premium & fun.** Leagues for endorsement accuracy, Guardian status tiers (report credibility), placement-earnings leaderboards, seasonal "unit turnaround" storylines. The tone target: premium fintech-meets-fantasy-league, not grievance forum — the staking economy does the tone enforcement (venting is free in the journal; publishing costs stake).
- **TR-I — Whistleblower armor.** In-app retaliation tripwire: if a reporter's schedule/assignments degrade post-report, the pattern itself is flagged and packaged (retaliation is separately reportable). Protecting reporters is both ethical and the supply-side moat.

---

## 7. SUSTAINABLE BARKS — v2 (agreed items stand; two pushes)
- **SB4 — ESG-ingestion targeting**: crawl hotel groups' published ESG/community commitments; auto-generate outreach that quotes their own report back to them with a pre-priced sponsorship kit. Close rate does the work; zero human selling.
- **SB5 — Grant/CSR autopilot**: auto-drafted grant applications and corporate-giving submissions (Apparently doc rails), calendar-driven (A6 deadline engine, reused). The org's human involvement converges to: approve weekly plan, attend nothing.

---

## 8. NEW CROSS-PORTFOLIO CONCEPTS (not in v1)

- **X1 — Autonomy Console for end users.** Every app's users get the same surface the operator gets internally (I1, consumer-ized): what my bots did, receipts, one pause button, one authority slider. Trust is the scaling constraint on every product above; this is the single trust-manufacturing asset, built once.
- **X2 — Shared Regime-Change Oracle (build once, sell four times).** One kernel service watching courts/legislatures/agencies → consumed by Tomorrow (T4v2 settlement), Apparently (A1 diff-watch), Pareto (P4v2 household docs), Smarter (practice alerts). Also the connector layer for "linked live data" (T7v2 ERP pipes, A7 repos) is one framework. Highest-leverage single build in this document.
- **X3 — The Loop as the enterprise pitch.** Smarter (matter exhaust) → Tomorrow (clause pricing/hedging) → Apparently (drafting/filing) → back to Smarter (validation) is a closed loop no point-solution competitor can enter. Package it as one enterprise SKU ("Legal Risk Operating System") with T3v2-style flat pricing across all three.
- **X4 — Cross-app credibility currency.** TR-B's staked-credibility math, S4v2's telemetry scores, Galop's calibration score, and Tomorrow's reputation scoring are the same primitive: *verified predictive credibility per identity*. Standardize it as a kernel claim type (extends B3/E1/F2 passports) — one person's demonstrated judgment ports across products. No competitor can offer "your track record follows you," because no competitor has more than one product.
- **X5 — Regime-event prediction markets (internal first).** Before T4v2 sells regime swaps externally, run internal prediction markets on regime events among the fleet's own bots + opted-in users; calibration from these markets prices the external swaps. The Galop calibration engine is reusable here — the horse-racing scoring stack is secretly the legal-risk pricing stack.

---

## Sequencing delta vs. v1
1. **X2 oracle** first — it unblocks T4v2, A1, P4v2 simultaneously.
2. **T3v2 subscription economics engine** before any pricing goes public.
3. **A7 filings-as-code** — highest wow-per-engineering-hour in the portfolio.
4. **T2v2 clause pack** through counsel (B22 rail) in parallel with T6v2 choreography spec — both are documents before they are code.
5. **TR-B staking engine** before any Triage reporting UI ships — the truth mechanics must exist before the fury arrives.
6. **Galop paid-play vendor matrix + 24/7 probes** — revenue-critical and independent of everything else.
