# Operator revisions — CADE war rooms, W7 de-risking, R2 minimization, Galop live-concurrent, Triage anonymity, RAISE IP firewall, N5 deferral

Operator (Macey) revision pass, 2026-07-09. Amends already-ingested prompts: PROMPT-tomorrow-simplification-v2v3 (W2/W3/W7), PROMPT-apparently-autonomy-v2v3 (R2), PROMPT-galop-experience-v2v3 (GE2a), PROMPT-triage-buildout-v2v3 (TM2), PROMPT-orchestrator-raise-layer (F2–F4), PROMPT-hisanta-family-v2 (N5). Where decomposed tasks already exist for these items, update them rather than duplicating (intake dedup G7 applies). This file is also the operator's change-review record.

## 1. W2/W3 — CADE-optimized rooms with per-user Position Profiles (Tomorrow; replaces prior W2/W3 spec)

- **W2a Position Profile per user** — learned strategy/bias model per client: positions taken across past rooms, ratification history, declared playbooks, risk appetite from the T3 mandate. CADE roster includes the user's own **advocate persona** (arguing their bias faithfully) and an **adversary persona** red-teaming it; room staging is optimized against the user's profile, not a generic negotiator.
- **W2b Clause bifurcation: hedgeable vs non-hedgeable** — classifier splits contested points:
  - **Hedgeable** → W3 priced redlines (live risk price from T4/T5 curves: "this indemnity change costs 3.2bps RUM / $41k expected").
  - **Non-hedgeable action/compliance-oriented terms** (reporting frequency, reporting comprehensiveness, covenant mechanics, notice/cure periods, information rights) → **CADE determination** of most-likely-accepted terms given both sides' Position Profiles, clause-marketplace acceptance rates, counterparty scouting data, and pricing context; output = recommended term + confidence + dissenting factions + proof pack.
- **W2c Contentious-clause completeness lint** — the enumerated set (risk disclaimers, events of default, definition adjustments, default triggers, bankruptcy/insolvency provisions, indemnities, termination, plus any clause with marketplace contention score above threshold) must each leave the room either W3-PRICED or CADE-OPTIMIZED. Fail-closed: a room cannot present a settlement path while any contested clause is neither. Proof: lint test on fixture room.
- **W2d Commercial-decision escalation ("no overpriced lawyer needed")** — classifier tags items that are commercial business decisions rather than market-standard calls → user is prompted with the full option set: per-option plain-language implication cards built from `packageForReviewer` (consensus position, dissent + why, cost ranges, precedent acceptance rates, downstream obligations), plus a "what we need from you" prompt when CADE flags missing information (`unsettled` determinations auto-generate the information request). User can steer any determination; steers feed back into their Position Profile. Proof: fixture commercial decision renders option cards + info-request path.

## 2. W7 — Outcome band guarantee, de-risked rollout (Tomorrow; replaces prior W7)

Confidence-gated, capped, and shadowed first — the answer to "can we do this confidently at first":
- **Phase 0 (shadow)**: bands computed and hit-rates tracked internally per negotiation class; no client-facing guarantee. Default posture: **band transparency** — publish the expected band + our historical hit rate on that class (already unmatched in market, zero liability).
- **Phase 1 (guarantee)**: per negotiation class, guarantee activates only when rolling calibration ≥ threshold on ≥ N shadowed rooms (W5 corpus). Guarantee = **fee credits only, capped at that room's allocated subscription fee** — never uncapped, never cash out.
- **Controls**: band width priced from realized dispersion; per-room guarantee reserve accrual; per-class auto-suspend circuit breaker if rolling hit rate degrades (falls back to band transparency, existing guarantees honored). Proof: gating fail-closed test; cap test; circuit-breaker test.

## 3. R2 — Regulator Data Rooms: minimization + check-the-box + per-examiner fit (Apparently; extends prior R2)

- **R2a Disclosure minimization gate (default-deny)** — an artifact is exposable ONLY if it maps to (a) an explicit requirement citation in the A1 requirements graph for that agency/license, or (b) a learned-precedent rule (this agency or examiner historically requests it — from exam/follow-on-request corpus). Everything else is blocked from the room. Attempted over-disclosure is logged and requires an officer override receipt. Proof: fail-closed exposure test; override-receipt test.
- **R2b Check-the-box mirror** — compliance rendered in the agency's OWN checklist/workpaper taxonomy (per-agency templates), each checklist row → one-click pre-indexed evidence with citation; sampling interfaces match the agency's sampling style.
- **R2c Per-examiner customization** — SC2 interaction-playbook data (professional patterns only — schema constraint carries over) tunes format, ordering, sampling presentation, and correspondence cadence per examiner representative.
- **R2d Follow-on predictor** — model of likely follow-up requests pre-stages responsive packages PRIVATELY; released only when actually requested (consistent with R2a: predicted ≠ disclosed).
- **R2e Goodwill loop** — response-SLA dashboard visible to the examiner, post-exam feedback capture feeding the playbook; goal: exams painless for both sides, agency-by-agency reputation as the reference registrant.

## 4. GE2a — Live-concurrent betting stack (Galop; replaces prior swipe-stack spec)

Real-time first, TikTok-viewing loop: many events run concurrently and the user should never leave live racing.
- **Live stack**: the swipe-stack surfaces races IN PROGRESS and races inside their betting window (approaching post) across all circuits, interleaved so something is always live and something is always bettable; global circuit scheduling guarantees "always a race about to go off."
- **Concurrent viewing**: multi-view (primary stream + thumbnail rail or PiP of other live races), one-swipe switching mid-race; auto-advance to the next going-off race at finish.
- **Concurrent betting**: one-tap bets from saved presets on any race still inside its window while watching another; Portfolio Slip aggregates concurrent positions; drawer keeps aggregate at-risk + live P&L always visible (velocity never hides exposure — retained).
- Bets accepted only within official betting windows per feed rules (post-time close enforced by the tote integration — the hook is constant live viewing + rapid window-to-window movement, not synthetic in-race markets). Proof: window-enforcement test; concurrent-slip aggregation test.

## 5. TM2a — Contributor anonymity firewall vs employers (Triage; extends TM2)

Employers must never be able to identify the underlying contributor:
- **Voice**: all audio evidence re-synthesized (voice transformation) before any employer-visible surface; originals sealed platform-side.
- **Image**: redaction beyond patient identifiers — reporter-identifying elements too (reflections, badges, handwriting, uniforms, EXIF/metadata stripped).
- **Text**: stylometry normalization (writing-style neutralization) on report prose.
- **Timing/context**: publication jitter + shift-decorrelation so report timing can't be mapped to rosters; k-anonymity thresholds on unit-level displays (suppress below k contributors).
- **Platform-side identity retained** under strict access controls — required for staking/credibility (TR-B), retaliation tripwire (TR-I), and lawful-process handling; never in any employer-facing payload (serialization test: employer API responses contain no contributor identifiers, direct or derived). Proof: end-to-end anonymization pipeline tests incl. metadata and serialization checks.

## 6. RAISE — IP firewall (orchestrator; extends F2–F4)

No IP is ever shared autonomously — generalities only; the human introduces IP (technical, strategy, legal strategy/decisions) when they choose:
- **Outbound content classifier**: allow metrics, outcomes, receipts, market descriptions, team/traction generalities; DENY technical mechanisms/architecture, novel legal structures, clause designs, legal strategy, negotiation posture, unfiled filings. Kernel constitution rule `ip_disclosure_in_outreach` → deny (sits beside the F3 truth gate).
- **Data rooms**: whitelisted fact classes only; diligence auto-answers restricted to the whitelist; any IP-level question auto-escalates to the human via F6 with suggested framing ("happy to walk through under NDA in the meeting").
- Proof: classifier deny tests on fixture IP content; escalation-path test.

## 7. N5 Hisanta school mode — DEFERRED (operator direction)

Remove N5 from active decomposition/queue; park as backlog note (do not build now; no focus expansion). H1–H4 unchanged and remain queued.

---
Everything else from the v2/v3 queue pass stands as ingested, per operator: all uncommented items proceed unchanged.
