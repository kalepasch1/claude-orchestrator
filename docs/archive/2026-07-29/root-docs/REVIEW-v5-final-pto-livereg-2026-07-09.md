# v5 FINAL additions — SM-3 leave-timing optimizer + AP-6 live regulator-portal tests (run NOW)

Operator direction 2026-07-09. Two additions to v5; then queue everything. Read alongside PROMPT-v5-reconciliation-enhance-not-rebuild (ENHANCE vs NET-NEW rules apply). Dedup G7.

## 1. SM-3 enhancement — Leave/PTO Timing Advisor (Smarter; associate-owned, extends SM-3)

Add to the SM-3 wellbeing dashboard an autonomous, associate-owned recommendation of WHEN to take PTO/leave for lowest cost to career + highest recovery value:
- **Inputs**: personal workload trend + burnout signal (existing SM-3 telemetry); forward matter calendar and deadline density (SM-1 PM engine); firm/practice seasonal fluctuation (historical workload by week/month — e.g., pre-quarter-end filing crunch, court recess windows, deal-cycle lulls); upcoming assignment pipeline; team coverage/overlap; accrued balance + use-it-or-lose-it expiry; blackout/critical-date conflicts.
- **Output**: ranked "best windows to take N days" with rationale ("Aug 11–15: post-close lull, no deadlines within your matters, low historical utilization, coverage available"), plus a burnout-triggered "take time soon" nudge when signals cross threshold. One-tap draft of the leave request routed for normal human approval (never auto-books; SM-2 approval boundary).
- **Boundaries (locked)**: associate-owned; ONLY aggregate/anonymized capacity signals reach partners (S4v2 boundary — a specific person's health/leave plan never surfaces to partners); firm-side sees "team capacity dips week of X," not who or why. Access test required.
- **Framing**: this is wellbeing/retention infrastructure, not attendance tracking — the recommendation optimizes the associate's recovery and career, and partners get only the capacity-planning aggregate.
- Classification: ENHANCE SM-3 (rides SM-1 calendar + existing telemetry + A6 seasonal data). Proof: window-ranking test on fixture calendar; named-individual leave data stays associate-side (access test); burnout-nudge threshold test.

## 2. AP-6 — Live regulator-portal reconnaissance & submission tests (Apparently; RUN NOW, pre-launch)

Before mass onboarding, actively test real regulator websites/APIs via Claude-in-Chrome (and any documented regulator APIs) to find every weakness, missing process, or unsupported step — so launched users hit zero friction. Extends the §5 proving harness (AP-1..AP-5); uses existing harnesses, adds a LIVE external tier.

- **AP-6a Portal reconnaissance** — for each target license (financial/gaming/insurance/banking + priority states/agencies: NMLS, FINRA, SEC/IARD, CFTC/NFA, state DFPI/DOB/gaming boards, etc.), drive the actual portal via Claude-in-Chrome: map the real submission flow, every field, required attachments, format constraints, session/auth model, CAPTCHA/MFA gates, fee-payment steps, portal quirks. Output a per-portal capability + gap report. READ/NAVIGATE ONLY in this phase.
- **AP-6b Dry-run form fill (no submit)** — populate real forms with synthetic-but-valid fixture data up to the final submit step; screenshot + diff against our generated filing to confirm field-level mapping is correct and complete. STOP before submission. Flags every field we can't yet auto-populate. 
- **AP-6c Sandbox/test-environment true submissions** — where a regulator provides a test/sandbox environment (many do: NMLS test, FINRA CAT test, etc.), execute END-TO-END real submissions there to prove the full pipeline including confirmations/receipts/error handling. Enumerate which portals offer sandboxes; use them.
- **AP-6d Gap→remediation loop** — every weakness (unmappable field, unsupported attachment type, auth we can't automate, undocumented step, format rejection) auto-opens a prioritized remediation task via prompt_factory, so the build closes gaps before real users arrive. This is the point of running now.
- **AP-6e Portal change monitors** — standing Chrome/API monitors on each portal detect layout/requirement/fee changes (feeds A1 requirements graph + A6 deadlines); re-run AP-6a on change.
- **HARD LIMITS (constitution-enforced):** NO real production submission against a live registrant record; synthetic data only; sandbox environments only for true submissions; no real fees paid; no real MFA/identity of actual users; any accidental live-submit path denied (`live_regulator_submit_without_operator` → deny) and escalated. Link-safety + credential handling per house rules. Proof: recon report per portal; dry-run field-diff test; sandbox e2e where available; gap tasks filed; live-submit deny test.
- Classification: NET-NEW live external tier on the EXISTING proving harness (do not rebuild the harness; add the Chrome/API tier). Runs NOW and on portal-change.

## Queue instruction
Cue ALL v5 work now (this file + PROMPT-v5-reconciliation as scope-of-truth + the earlier PROMPT-v5 items, reconciled). Priority order for immediate pre-launch: (1) Apparently AP-1..AP-6 proving [AP-6 gates launch], (2) §6 test-bot fleet TB-1..TB-4, (3) CADE reuse enhancements, (4) SM-* incl. SM-3 advisor, (5) Tomorrow CG-*, (6) cross-app coordination. AP-6 findings may generate P0 remediations — those jump the queue.
