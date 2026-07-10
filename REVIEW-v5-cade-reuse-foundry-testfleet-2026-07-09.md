# v5 — CADE precedent reuse, cluster-scoped coordination, Contract Foundry, Smarter expansion, Apparently proving ground, Synthetic User Fleet

For operator final review 2026-07-09 — NOT yet queued (will drop as PROMPT files on your go). Extends v4; amends A-1, B-1, B-2.

## 1. CADE Precedent Reuse Engine (kernel + Tomorrow/Smarter war rooms; expands v4 A-1)

Prior determinations become reusable precedent, not sunk cost:

- **Precedent store** — every determination persisted with its full context fingerprint: issue embedding, clause family, jurisdiction, regime-state version (X2 oracle snapshot), counterparty profile version, market-state hash, roster/calibration version. New issues are matched by embedding + fingerprint before any panel is seated.
- **Reuse ladder** (cheapest sufficient wins): (1) exact-context match → reuse outcome directly, zero compute; (2) matched-but-aged → cheap-tier revalidation pass (standing-roster cache) confirming nothing material changed; (3) partial match → **delta determination**: only the changed sub-issues re-run through the panel, unchanged sub-issue conclusions inherited with citations to the prior proof pack; (4) no match → full determination, which then enriches the store.
- **Staleness invalidation, event-driven not clock-driven** — precedents are auto-invalidated by the things that actually change answers: X2 regime events touching the clause family/jurisdiction, counterparty profile shifts past threshold, market-state moves past threshold, roster recalibration. Timely = provably nothing changed, not "less than N days old."
- **Evolution on reuse** — each reuse appends realized outcome data to the precedent (did the reused term get accepted? litigated?), sharpening it; heavily-reused precedents get periodic deep-tier refresh so the corpus improves rather than fossilizes. War-room effect: the 40th materially-similar indemnity dispute costs ~zero and answers better than the 1st.
- **Economics surfaced** — per-room CADE cost report shows precedent-reuse savings ("this room: 11 issues, 9 from precedent, 2 novel — $3.10 compute vs $41 cold"); feeds G13/G16.
- Proof: reuse-ladder tests (all 4 rungs), event-driven invalidation test, delta-determination inheritance test with proof-pack citation chain.

## 2. Cross-app coordination, cluster-scoped (revises v4 B-1/B-2 per operator)

Agreed: Tomorrow↔Hisanta users barely overlap. Split infrastructure (global) from user-facing coordination (clustered):

- **Stays global (app-agnostic plumbing, invisible to users)**: B-3 kernel persona registry, B-4 event fabric, receipts/verifier, guarantee engine, consent spine. These are shared machinery, not shared user experiences — no downside to global.
- **Cluster-scoped (user-facing)**: 
  - **Enterprise cluster**: Tomorrow + Apparently + Smarter + RAISE — full B-1 onboarding graph + B-2 unified wallet + the Loop SKU (X3). Overlap here is the strategy.
  - **Consumer cluster**: Pareto + Hisanta (+ Galop where jurisdictionally sensible) — household-level onboarding graph (P5v2 family mesh IS this graph), family wallet; Hisanta reward-coins → Pareto child lanes as the on-ramp.
  - **Professional cluster**: Triage (+ Smarter career passport S5) — the X4 credibility currency bridges these two only.
- **Opt-in bridges between clusters, claim-level only** — e.g., Galop KYC claim → Pareto underwriting; never profile-level merges across clusters. Keeps consumer/enterprise data postures separate (cleaner privacy story, cleaner M&A optionality per cluster too).

## 3. Tomorrow Contract Foundry — self-improving novel-instrument generation

Extends B9 (payoff compiler) + B11 (instrument discovery) from "generate variants of known instruments" to "originate novel structures autonomously":

- **Demand mining — impasses are product gaps** — every W1 pre-resolution failure, unresolvable war-room point, declined quote, and unhedgeable-clause flag (W2b non-hedgeable overflow) is logged as a structured demand signal: someone needed a contract that doesn't exist. The Foundry's queue is fed by real failures, not brainstorming.
- **Generative loop** — demand signal → CADE panel (finance authorities + mosaic + adversary) drafts candidate structures in the payoff DSL + clause templates (Apparently rails) → compile (B9, fail-closed allowlist) → backtest (B11) → shadow-trade against live flow (G9 pattern) → calibration-gated promotion to catalog → T5 curve coverage extended. Failed candidates enrich the negative corpus.
- **Novelty engine** — recombination across domains the mosaic personas carry (insurance structures × derivatives × legal-clause mechanics); novelty scored against the existing catalog embedding space so the Foundry is rewarded for genuinely new payoff shapes, not parameter tweaks; heretic-quota personas (exploration:true) seeded into Foundry panels specifically.
- **Self-improvement** — Foundry outcomes feed persona calibration (which experts design instruments that trade well?), demand-signal taxonomy auto-refines, and each promoted instrument's realized P&L/adoption re-weights the generation priors. The engine that designs contracts learns from every contract it designs.
- **Guardrails unchanged** — allowlist compile, fail-closed promotion, MATERIAL gate on catalog additions, ECP/bilateral posture locked. Novelty in payoff space, never in legal-posture space without the B22 rail.

## 4. Smarter — junior-associate expansion pack

New capabilities beyond S1–S5/SC1 (the unglamorous ones that actually change associates' lives):

- **SM-1 Autonomous timekeeping** — time entries auto-drafted from workflow telemetry (docs touched, rooms attended, drafts produced), narrative-ready, associate one-click confirms. The single most hated task in law, deleted. Billing-partner view gets matter-economics live.
- **SM-2 Workload & burnout radar** — deadline stacking + hours telemetry + turnaround degradation → early overload detection; auto-drafted staffing rebalance proposals to partners (aggregate-first presentation, consistent with S4v2 posture).
- **SM-3 Impossible-deadline guard** — when a new assignment mathematically can't fit (court dates + existing commitments), the system flags it at assignment time with evidence and a proposed alternative — the associate never has to be the one to say no.
- **SM-4 Manage-up autopilot** — partners' status anxiety generates most interruptions; auto-generated per-partner status briefs (their preferred format/cadence, SC1-style internal profiles) so associates stop being pinged. 
- **SM-5 Meeting eliminator** — agenda items auto-resolved async where the system already has the answer (receipts attached); meetings auto-shrink to genuinely open items (war-room W2 doctrine applied to internal meetings).
- **SM-6 Cross-matter deadline choreography** — one calendar solver across all an associate's matters (court rules-aware date computation, conflict detection, auto-negotiated internal deadlines); no associate ever discovers two briefs due the same day again.
- **SM-7 Skill trajectory** — S5 passport extended with a development planner: gap analysis vs target role, matter-type rotation suggestions, CLE auto-scheduling — career development as an autonomous background process.

## 5. Apparently — pre-launch proving ground (before mass onboarding)

Prove every process now, on synthetic + historical load, so first real users hit a burned-in system:

- **AP-1 Full-lifecycle dress rehearsals** — extend A2 shadow filings from per-lane to end-to-end: synthetic companies (varied sectors/jurisdictions/complexity) run the ENTIRE journey — onboarding → repo link → requirements graph → drafting → deadline ladders → officer sign-off → (sandboxed) submission → renewal cycle — against historical regulatory calendars, replayed at accelerated clock. Every discrepancy vs known-good historical filings is a bug filed automatically.
- **AP-2 Regulator simulation** — CADE examiner personas (skeptical-regulator adversaries, per-agency styles from SC2 corpus) review generated filings and data rooms, issue simulated RFIs/deficiency letters; the system must handle them end-to-end. Exam day is rehearsed before any real examiner logs in.
- **AP-3 Fault injection** — webhook outages, malformed repo diffs, requirements-graph conflicts, deadline-ladder races, partial-submission failures — chaos suite with the dead-man-switch invariant verified under each fault (a deadline must be un-missable even mid-outage).
- **AP-4 Drafting quality gate** — generated filings scored against a golden corpus of accepted real filings (G8 eval-gate); publish the internal quality bar before launch; regression-blocked thereafter.
- **AP-5 Graduated launch** — design-partner cohort (5–10 friendly firms) on production with white-glove monitoring before open onboarding; their journeys become the first real golden journeys.

## 6. Synthetic User Fleet (orchestrator level, recurring)

Yes to test-user bots — and make them a permanent organ, not a launch tool:

- **SF-1 Persona cohort** — 5–10 standing user personas per app (e.g., Tomorrow: mid-size lender CFO, gaming-operator treasurer, skeptical GC; Pareto: young family, pre-retiree, aging-parent caretaker; Galop: casual fan, sharp, cold-streak-prone user; Triage: burned-out ICU nurse, ambitious traveler, skeptical administrator; Hisanta: grandparent, cautious parent, 8-year-old attention span modeled). Personas are versioned like CADE rosters.
- **SF-2 Weekly value runs** — every persona executes its full journey weekly on staging: TTFV measured (A-3 gates), friction logged per step, value-delivery scored ("did the persona get what they came for, how fast, how confused"). Output: per-app UX report + auto-filed improvement demands routed through the G5 pre-generation gate with RICE scores (so bot suggestions compete on equal footing and don't flood the queue).
- **SF-3 Adversarial runs (break/exploit safely)** — a red-team persona class per app attempts abuse: authority-budget evasion (Pareto), wager-window manipulation (Galop), stake-gaming and deanonymization attempts (Triage), over-disclosure coaxing (R2 data rooms), IP-extraction prompts (RAISE), consent-boundary probing (A4v2). STRICTLY sandboxed/staging, never prod money paths, never real third parties. Every successful exploit auto-becomes a permanent CI guard (G11) — the fleet converts its own attacks into immunity.
- **SF-4 20X-demand loop** — personas don't just report bugs; they file structured feature demands from real-time use ("as the treasurer persona, the quote page didn't show me X"), which is exactly the outside-in signal the backlog otherwise lacks pre-launch.
- **SF-5 Cadence** — weekly full-fleet runs on staging + post-deploy smoke subset on prod (read-only personas only); monthly adversarial deep runs; results in the daily digest when red, weekly summary otherwise. Personas run under