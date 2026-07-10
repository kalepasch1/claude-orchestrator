# Pareto — life-goal autonomy stack

Target repo: pareto/2080.
Source specs: REVIEW v2 §4, REVIEW v3 §8 (N3). Depends on queued A1–A2 (pareto section) + the 2080 phase roadmap — check the repo roadmap before decomposition to avoid overlap with phased items already planned. Designs are regulatory-posture-agnostic; execution actions ship behind user one-click approval with graduated authority budgets.

## Objectives

1. **P1v2 Life state machine** — goals compile to continuously re-planned state machine over the deterministic engine graph; Monte Carlo confidence bands; single map/progress-line/one-knob UI; deviation-only interrupts; plain-language replan receipts. Proof: fixture goal set compiles; injected shock replans with receipt.
2. **P2v2 Delegation firewall** — inbound bill/mail/email parsing → classify → act within graduated authority budget ($0 approval-only → $500 → unlimited-with-receipts, trust-ratchet pattern); auto-negotiation bots (bills/rates/fees/subscription-creep); dispute-letter drafting; monthly one-card digest. Proof: authority-budget fail-closed test; fixture bill negotiated in sim.
3. **P3v2 Daily micro-sweeps** — continuous small-scale harvesting/benefit-window/insurance-reshop/idle-cash sweeps; signed savings receipts; live "paid for itself ×N" meter. Proof: sweep engine test + meter computation from receipts.
4. **P4v2 Regime-aware household legal** — consume shared regime oracle (portfolio X2): jurisdiction rule changes auto-update affected user documents + proactive notification; household legal-protection subscription tier (monitoring + remediation legs, consumer-sized). Escalation to licensed partners on thresholds. Proof: fixture regime event updates fixture lease template.
5. **P5v2 Intergenerational mesh** — household passport (guardian_of edge pattern); aging-parent graduated takeover protocol (reverse trust-ratchet); estate continuity (docs + beneficiary sync always current); child lanes graduating to own accounts. Proof: mesh authority tests fail-closed.
6. **P6 Earnings-only interface** — end-state surface: income is the only user-facing financial object; all else behind firewall with receipts. Proof: decision-budget lint on core journeys.
7. **P7 Crowd benchmark exchange** — anonymized outcomes corpus (negotiation results by category) powering negotiation bots with base rates; k-anonymity gates on publication. Proof: anonymity-gate test.
8. **N3 Audit-proof life** — every financial action auto-packaged with documentation into standing audit-defense file (personal compliance-bundle pattern); drafted return + evidence binder at tax season. Proof: fixture year assembles binder.
