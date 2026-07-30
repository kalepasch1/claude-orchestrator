# Portfolio Simplification & Super-Intelligence Review — 2026-07-09

Scope: Tomorrow, Apparently, Smarter, Pareto, Galop, Hisanta, Darwin→Triage, Sustainable Barks, Orchestrator.
Method: reviewed ORCHESTRATOR_INTAKE_BACKLOG.md (sections A–I), cowork-backlog/backlog.json (30 tasks), TASKS.md (G1–G21), Galop strategy docs, Pareto/2080 roadmap. Everything below is **additive** to queued work; where an idea overlaps a queued item, the item ID is cited and the recommendation extends it.

**Naming note:** deliberately NOT named `PROMPT-*.md` so intake_watcher does not auto-ingest. Accepted items should be cherry-picked into `PROMPT-<name>.md` drop-box files individually.

---

## 0. The one portfolio-wide simplification lever

The backlog already contains the answer to "few clicks" and it's currently scoped too narrowly. The **decision-budget (5/95) + trust-ratchet + passport/claims** stack (B4–B7, C7, B3, E1, F2) is Tomorrow/Smarter-specific today. Promote it to **portfolio doctrine**:

- **P0-DOCTRINE — One Decision Budget spec, all apps.** Every user-facing surface in every app declares a max decision count and a lint (`lint-decision-budgets.mjs` already exists in B5). Target: any core journey in any app ≤ 3 decisions, graduating to 1 via trust-ratchet. This is the codified version of "so simple, a few clicks."
- **P0-PASSPORT — One Household/Firm Passport.** B3/E1/F2 mint claims per app. Additive: a single cross-product passport wallet surface — an ECP onboarded on Tomorrow is instantly KYC'd on Galop, licensed-status-aware on Apparently, underwritten on Pareto. The flywheel exists (runFlywheel, B3); the missing piece is the *user-visible* "you're already done" moment on every product's first screen.
- **P0-RECEIPTS — "Why did the machine do that?" as a product.** Kernel receipts (G12, H3, H4) are back-office today. Additive: a consumer-grade explanation surface (one card: what was done, counterfactual cost of not doing it, undo button). Trust is the binding constraint on autonomy everywhere below; receipts are how you buy trust cheaply.

---

## 1. Tomorrow — war room / risk exchange

### Honest correction first (this changes the pitch, not the product)
"Eliminate perpetually all risk **plus** earn massive profits **while** reducing VaR/CVaR" is not achievable as stated — risk is conserved; liquidity-provision returns are compensation for bearing it. Selling it as stated invites regulatory and litigation exposure when a participant loses money. What IS achievable, and is a stronger pitch:

1. **Compression is the free lunch.** Multilateral netting removes *gross* exposure with no one taking new risk. Lean the marketing on this.
2. **Diversification/mutualization genuinely cuts per-party tail risk.**
3. **Liquidity provision earns premia in exchange for risk** — let ECPs pick a point on the frontier with one knob (B5's One-knob already models this).

### Additive recommendations (beyond B1–B22)
- **T1 — Multilateral compression cycles.** B14 (mesh-of-rings) is topology; add a scheduled *compression run* (triReduce-style): solver finds gross-notional-reducing cycles across the mesh, proposes a single one-click "compress" to all parties, mints avoided-exposure receipts (feeds B20 benefit receipts). This is the purest "click once, risk disappears" mechanic that is actually true.
- **T2 — Mutualized default fund + tranched backstop.** B15/B16 gate and remediate credit; add a small mutualized fund (basis points on notional) so ECPs' bilateral loss-given-default goes near zero. This is how you honestly get close to "risk eliminated": the pool absorbs idiosyncratic tail, priced transparently.
- **T3 — Hedge-as-subscription.** Flat monthly fee → the perp-lifecycle loop (B8) keeps the ECP inside their declared risk budget perpetually. One purchase decision, zero ongoing decisions. ⚠️ If payoff is contingent on loss events this walks into insurance regulation — structure as derivatives under the existing ECP/swap posture, or partner with a fronting carrier.
- **T4 — Clause hedging = contract-outcome parametric contracts.** The clause marketplace + effectiveness/risk-scoring engines already price clause risk. Additive product: parametric contracts paying on objectively verifiable contract events (termination triggered, indemnity claimed, renewal lapsed), priced from Smarter's clause-outcome corpus (C5 opsignal feed is the data pipe), drafted via Apparently (D5 emitters). ⚠️ Two regulatory rails: (a) event contracts / CFTC treatment, (b) anything indemnifying legal *costs* is insurance. Keep payoffs parametric and ECP-only. This doesn't "kill the legal industry" — it kills the *pricing opacity* of legal risk, which is the defensible claim.
- **T5 — Clause Risk Index (data product).** Publish anonymized clause-outcome curves ("probability an uncapped indemnity clause is invoked, by industry") as a paid index. Zero balance-sheet risk, pure margin on data the fleet already collects, and it markets T4.
- **T6 — Swarm economics: bots bid, book clears.** 70+ bots currently coordinate via pub/sub. Additive: an internal auction where bots submit priced intents and a clearing layer nets them *before* anything hits the external book — the hivemind becomes an internal exchange. Cuts external execution cost and makes bot P&L attributable (feeds G16 ROI attribution pattern).
- **T7 — "State your balance sheet, get a package."** B21 (outbound onboarding) pre-computes packages from public data; additive inbound version: ECP uploads a trial balance / loan tape, exposure catalog auto-maps it, and the first screen is a single pre-priced "accept hedging program" button. Combined with B6 (mandate collapse) this is the literal few-clicks experience.

---

## 2. Apparently — autonomous licensing/registration

### Honest correction
"Delete your compliance team" cannot be literally true: most regimes require an accountable natural person (MLRO, compliance officer, qualified individual, broker-in-charge) and filings carry personal attestations. The achievable — and safer to market — claim is the **5/95 compliance department**: one accountable officer, everything beneath them generated, evidenced, and filed by the system. Conveniently, this is the same decision-budget doctrine already queued (B5/C7); apply it here too.

### Additive recommendations (beyond D1–D5)
- **A1 — Requirements-graph crawler with diff-watch.** Bots crawl every regulator's rulebook/portal into a versioned requirements graph per (jurisdiction × sector × license type). Nightly diffs trigger auto-regeneration of affected filings and a customer alert. The moat is the *graph freshness*, not the filings.
- **A2 — Lane certification via shadow filings.** Before any lane (license type) goes autonomous, it must pass N shadow runs replayed against historically successful filings — the champion-challenger pattern queued as G9, propagated to Apparently (exactly what G14 fix-propagation is for). Lanes carry a certification level: drafted → officer-reviewed → auto-file.
- **A3 — Cross-license sequencing solver.** Multi-state/multi-sector applicants have dependency-ordered prerequisites (entity formation → registered agent → state A → reciprocity in B…). A DAG solver (planner.py's contract-first pattern, reused) that outputs the critical path and files in optimal order is a visible 10X over any human compliance team.
- **A4 — Smarter-activity learning, consent-gated.** Learning from Smarter user activity requires an explicit cross-product consent claim on the passport plus the information barrier D4 already enforces. Ship it as an opt-in with a visible dividend (I3's data-cooperative pattern): firms that share negotiation/compliance exhaust get cheaper licensing.
- **A5 — Perpetual compliance calendar as the retention product.** The license is the acquisition hook; renewals, CE credits, annual reports, and exam-readiness binders (H4 export bundle, productized) are the subscription. Auto-assembled examiner packets — "your audit binder is already done" — is the single feature that makes firing most of a compliance team feel safe.

---

## 3. Smarter — junior-associate autonomy

### Additive recommendations (beyond C1–C7)
- **S1 — Matter exhaust → playbooks.** Every completed matter auto-distills into a reusable playbook (the learn_from_merges pattern, applied to legal work product). New matters open pre-populated to ~90%. This is the compounding 1000X, and it feeds T5/T4 pricing data.
- **S2 — The Flagged-Only Workday.** Invert the UI: the associate's home screen is *only* the human-required queue (UPL-gated items, final sends, judgment calls C1 already escalates). Everything else runs in a visible-but-collapsed autonomous lane with receipts. This is C7's 5/95 taken to its logical end-state UI.
- **S3 — Relationship autopilot.** Cadence engine over the contact graph: drafts check-ins, remembers matter anniversaries, preps meeting briefs; associate approves sends (stays inside the C1 pre-send gate). External comms must stay human-approved — privilege and UPL make full autonomy here a malpractice generator, and the approval *is* the flagged task.
- **S4 — "Problematic employee" flagging — reframe or it backfires.** Covert performance surveillance creates GDPR/works-council exposure, discrimination-claim discovery risk, and destroys adoption (associates are the users). Defensible version: (a) *self-directed* analytics for the associate, (b) *aggregate, matter-level* risk signals to partners (missed deadlines, stalled negotiations — C5 already emits these to Tomorrow as ops signals; mirror them internally), with named-individual reporting only via documented, disclosed policy.
- **S5 — Career passport, associate-owned.** The recruiting exchange has a channel conflict: firms pay for Smarter; a poaching rail burns them. Resolve by making the verified skill/matter-history passport *owned by the associate* (kernel claims, F2 pattern), portable, and monetized as recruiter-side search on opted-in profiles only. Same revenue, no betrayal of the paying customer.

---

## 4. Pareto — life-goal financial autonomy

### Honest correction
"Advisory/educational to avoid needing to register" does not survive contact with regulators if the system gives personalized recommendations for compensation (RIA territory) or executes autonomously (discretionary management, and money movement can trigger custody/MTL questions). Labels don't control; substance does. Three viable postures: (a) partner/white-label with registered entities and be the tech layer, (b) register a lean RIA — cheaper than it sounds and it *unlocks* the full autonomous promise legally, (c) keep genuinely non-discretionary: system proposes, user's one click executes. The 2080 trust-graduation architecture maps cleanly onto (c)→(b).

### Additive recommendations (beyond A1–A2 and the 2080 phase roadmap)
- **P1 — Goal solver over the 57 engines.** The engines are deterministic specialists; add the top-layer inversion: user states destinations ("kids' college 2035, retire at 55, Lisbon summers"), solver runs the engine graph backwards to a funding/action plan, and surfaces only deviations. The user interface to their entire financial life becomes a *map with a progress line*, not accounts.
- **P2 — Financial firewall.** All inbound financial noise (bills, renewals, rate changes, fee hikes, subscription creep) lands on the system, not the user. Auto-negotiate/cancel/re-shop within a user-set annual authority budget (trust-ratchet B7 pattern: $0 → $500 → unlimited). Users stop touching the financial system; they touch the firewall's monthly one-card digest.
- **P3 — Annual sweeps as events.** Tax-loss harvesting, benefits open-enrollment optimization, insurance re-shop, estate-doc refresh — each an automated annual sweep producing a signed "we saved you $X" receipt (B20 pattern). Receipts with dollar amounts are the retention engine.
- **P4 — Legal-lite via Apparently rails.** Rental disputes, small claims prep, estate basics: generate documents + process guidance through Apparently's engines with explicit "not legal advice / not your law firm" boundaries and escalation to licensed partners when thresholds trip (mirrors C1's UPL gate). Referral-fee revenue instead of UPL risk.
- **P5 — Family mesh.** Household-level passport (F2's guardian_of edges, generalized): spouses, kids' custodial accounts, aging-parent finances under one goal map with per-member autonomy budgets.

---

## 5. Galop — horse-racing gaming

### Design-ethics line (also the commercial argument)
I'd steer away from wagering-coupled variable-ratio reinforcement ("dopamine/operant conditioning" tuned to increase betting). Beyond ethics: UKGC, Ontario iGaming, and Australian rules increasingly prohibit exactly these mechanics; app stores scrutinize them; and an ADW license application (already on the roadmap) gets harder with a dark-pattern record. The durable moat you named yourself: **the platform where bettors get better**. Engagement mechanics below are conditioning-free but sticky.

### Additive recommendations (beyond E1–E3 and the GALOP_* roadmaps' queued items)
- **G1 — Calibration score as the core progression.** Rate every pick's *forecast quality* (Brier score vs. the tote), not just W/L. Skill tree, leagues, and badges hang off calibration improvement. This is the "bet better" mechanic with real substance — losing bettors measurably improve, which is also your regulator story.
- **G2 — Cold-streak circuit breakers (formalized).** Your instinct, made concrete: rolling drawdown triggers → stake cool-down, auto-shift to free-to-play races, "review your last 10 picks" coaching interstitial, optional self-set loss limits with celebration (not shame) framing. Route the trigger through the kernel constitution (E2 pattern) so it's provably enforced.
- **G3 — Verified tipster ledger.** The roadmap's creator network + kernel receipts: every public pick is timestamped pre-race, ROI ledgers are tamper-evident (G12 signing). Kills fake-tout fraud, creates a real creator economy, and generates the 24/7 feed content between races.
- **G4 — 24/7 feed without 24/7 racing.** Global circuit ingestion (JRA night racing, HK, harness), auto-cut replay highlights, "past race mystery" prediction reruns (free-to-play, calibration-scored), stable/ownership storylines. Feed density from content, not from wager prompts.
- **G5 — Syndicates.** Group bankrolls with role-based picks (one member handicaps pace, another breeding), shared calibration league. Social retention that displaces solo loss-chasing.

---

## 6. Hisanta — kids + Santa

### Design-ethics line
Variable-ratio ("random") reward schedules aimed at children, coupled to purchases/gifts, is the loot-box pattern — banned or restricted for minors in several jurisdictions and squarely against COPPA/UK Children's Code enforcement trends. F1 already escalates `open_loot_box` and denies `charge_child` — the constitution is ahead of the product spec here. Keep it that way: **predictable, effort-contingent rewards; surprise as decoration, never as the purchase loop.**

### Additive recommendations (beyond F1–F3)
- **H1 — Mastery engine.** Spaced-repetition learning quests (reading, math, kindness/social skills) where the adaptive_difficulty capability (F3) tunes challenge, and rewards are earned-schedule (finish the week's quest → advent door opens). Educational efficacy is the parent-retention metric; publish it.
- **H2 — Grandma rail.** A dedicated elder-relative surface: daily 2-minute recorded story slot, reaction feed of grandkid milestones (guardian-approved, F2's no-PII edges), one-tap gift funding into parent-controlled queues. Grandparents are the highest-LTV, lowest-CAC payer in the system and nobody builds for them.
- **H3 — Kindness quests with real-world proof.** Parent-verified acts (helped sibling, wrote thank-you note) mint reward coins. Social development with the parent as oracle — no AI judging children's behavior (keeps F1's open_ended_child_chat deny intact).
- **H4 — Family gifting protocol.** Ad-hoc + advent + earned-reward gift lanes unified under parent approval (F1 escalation), with relative-funded "match jars" (grandma matches every earned coin). All purchase authority stays adult-side.

---

## 7. Darwin → "Triage" — healthcare recruiting

### This one needs a redesign, not a 50X
Rename to Triage: good. But paying healthcare workers to report their "worst colleagues," marketed as an "outlet for fury," with threats to escalate employers to regulators — that bundle is legally radioactive and I'd advise against building it in that shape: defamation liability (paid negative reports about named professionals), retaliation/whistleblower-interference exposure, HR-record discovery problems for the employers you want as customers, and financially-incentivized negative reporting produces *unreliable* data, which guts the safety mission. "We will report willful negligence unless the employer pays for training" reads as coercive leverage — don't go near it.

### The defensible version keeps every goal you listed
- **TR1 — Peer-endorsement recruiting exchange (the money).** Positive-signal marketplace: clinicians endorse colleagues' verified skills; endorsers earn the recruiting fee when a placement closes (the "you get the payout, not some random recruiter" promise, intact and legal). Kernel-signed endorsement receipts prevent gaming.
- **TR2 — Safety reporting through protected channels (the mission).** Route incident reports into Patient Safety Organization (PSQIA-privileged) structures or employer-sanctioned programs — reporters get legal protection, data gets federal privilege, and Triage becomes infrastructure hospitals *want*, not fear. Aggregate, de-identified unit-level risk analytics is the employer-paid product.
- **TR3 — Verified career ledger (the darwinian sorting).** Portable clinician passport (S5/F2 pattern): credentials, case volumes, endorsements. The best rise on verifiable signal; the sorting is transparent without a fury market.
- **TR4 — The "fury" energy → advocacy fuel.** Give frustrated clinicians agency that's safe: one-tap generation of a *proper* incident report, staffing-ratio data contribution, anonymous unit-culture surveys that feed TR2 analytics. Outlet preserved; liability not.

---

## 8. Sustainable Barks

### Tax-structure honesty (not a lawyer/tax advisor — verify with one)
Two corrections to the pricing concept: (1) a charitable *deduction* is not a *credit* — a $1 donation saves a corporate payer ~$0.21–0.30 of tax, so "donation equal to what they'd pay in taxes" doesn't net to zero for the hotel; (2) donated *services* (marketing, shelf space) are generally **not** charitable deductions for the donor, though the hotel can usually expense those costs as ordinary marketing anyway. The framing that actually is a no-brainer: **cause-marketing sponsorship priced as marketing spend** — the hotel buys ESG content, local press, and guest-experience differentiation at below their normal marketing CPM, and the cash component is set under their marketing (not tax) budget. Mind UBIT: keep nonprofit acknowledgments as sponsorship recognition, not priced advertising, or account for it separately.

### Autonomy recommendations
- **SB1 — Agentic ops dispatch.** Volunteer recruitment (auto-posted shifts to volunteer platforms), route-optimized pickup/clean/deliver runs, automated shelter-supply matching. Human involvement = approving the weekly plan (one click, decision-budget doctrine again).
- **SB2 — Hotel self-serve onboarding.** Landing page → e-sign sponsorship kit (Apparently doc rails) → auto-shipped starter kit → QR-tagged toys reporting distribution counts.
- **SB3 — Auto-generated impact receipts.** Per-hotel quarterly impact report (toys distributed, shelter hours funded, press mentions) — the B20/P3 receipt pattern; it's also their marketing asset, which closes the renewal loop autonomously.

---

## 9. Orchestrator — collective learning & the rebate network

Much of "all apps get smarter together" is already queued: G8 (eval gates), G9 (shadow), G12 (provenance), G14 (fix propagation), G16 (ROI attribution), G17 (decision feedback), plus learn_from_merges shipped. Additive:

- **O1 — Pattern registry with metered rebates (your external-network idea, made concrete).** Merged-work patterns (already auto-extracted) become versioned, signed registry entries (G12 signing). External subscribers' usage is metered per pattern-application; a revenue-share ledger credits the originating project as AI-token rebates. Requires an **IP/privacy scrubbing gate** at publication (process patterns only — no domain data, no identifiers) — this gate is the product's trust foundation and should be built first.
- **O2 — Cross-app golden-journey regression suite.** G8's eval gates are per-repo. Add portfolio-level golden journeys (ECP onboards on Tomorrow → passport → instant Galop KYC → Pareto underwrite) run on every material merge anywhere. Catches the cross-product breakage that per-repo gates can't see.
- **O3 — Capability marketplace internal pricing.** H2 builds the dependency graph; add internal transfer pricing on capability calls so G13's portfolio allocator can optimize on *realized cross-app value*, not proxy scores — and so the external rebate economics of O1 have a tested pricing engine before outsiders arrive.
- **O4 — Doctrine propagation as first-class intake.** When a doctrine (5/95, trust-ratchet, receipts-as-product) proves out in one repo, auto-generate the adoption tasks for the other repos via prompt_factory. Section 0 of this doc should be the first test case.

---

## Suggested sequencing (highest leverage per unit work)

1. **P0-DOCTRINE + O4** — portfolio-wide decision budgets; multiplies every other item.
2. **T1 compression + T7 inbound package** — makes Tomorrow's few-clicks promise literally true.
3. **A1 crawler + A2 lane certification** — Apparently's moat and its safety case, together.
4. **TR1/TR2 Triage redesign** — do this before any code; the current concept shape is a liability.
5. **S1 matter exhaust** — compounding asset that also feeds T4/T5 pricing data.
6. **G1/G2 Galop calibration + circuit breakers** — the regulator-friendly moat before the ADW application.
7. **O1 pattern registry** — after G12 lands, since it depends on signing.
