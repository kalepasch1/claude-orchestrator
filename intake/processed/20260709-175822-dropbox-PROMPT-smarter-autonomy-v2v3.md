# Smarter — matter exhaust, shadow associate, counterparty scoring, room scouting

Target repo: smarter.
Source specs: REVIEW v2 §3, REVIEW v3 §4. Depends on queued C1–C7 (don't re-implement). UPL/pre-send gates (C1) are locked constraints.

## Objectives

1. **S1v2 Matter exhaust → playbooks → marketplace** — every completed matter auto-distills to a reusable playbook (learn-from-merges pattern applied to legal work product); new matters pre-populate from playbook library; anonymized playbooks as marketplace SKUs per practice area (clause-marketplace anonymization rules). Proof: fixture matter distills; new matter opens ≥90% pre-populated.
2. **S2v2 Flagged-Only Workday + shadow associate** — home screen = human-required queue only (C1-escalated items); autonomous lane collapsed with receipts. Shadow duplicate of human-completed tasks per task class (G9 champion-challenger on work product); class auto-graduates to autonomous lane when shadow ≥ human quality threshold (B7 trust-ratchet on job functions); graduation receipts. Proof: fixture task class graduates only after quality threshold met over N samples.
3. **S3 Relationship autopilot** — cadence engine over contact graph: drafted check-ins, matter anniversaries, meeting briefs; ALL external sends remain human-approved (C1 gate — locked). Proof: no external send path bypasses approval (fail-closed test).
4. **S4v2 Counterparty/colleague scoring — non-Smarter-users first** [MATERIAL] — scores derived ONLY from verifiable workflow telemetry (turnaround, missed commitments, doc error/redline-churn, negotiation-stall events; C5 taxonomy pointed inward); every score decomposes to timestamped events; opinion inputs stored separately, labeled, excluded from headline score; Conduct Receipt export (signed chronological evidence pack); right-of-response claim flow for scored non-users (conversion funnel); scored population initially excludes Smarter users per operator direction. Proof: score-decomposition test; opinion-exclusion test; export verifies.
5. **SC1 Scouting into rooms** — opponent-counsel card auto-attached to every matter and embedded in war-room UI via bridge (C4): median turn time, concession curve, escalation triggers, clause-fight history; live in-room pattern alerts; post-room auto-update of profiles; feeds B13 ZOPA. Proof: fixture matter attaches card; room outcome updates profile.
6. **S5 Career passport (associate-owned)** — verified skill/matter-history kernel claims, portable, opt-in recruiter search only. Proof: claim mint + opt-in gate tests.
7. **RAISE funnel inbox** — receive fundraising human-required actions from orchestrator RAISE layer (meetings/term decisions) as flagged tasks with context packs. Contract-first: pin the inbound action contract in contracts (C3 pattern). Proof: fixture RAISE event lands as flagged task.

Guardrail retained (one line): telemetry-backed scores + labeled-opinion separation is what makes S4v2 exports usable as support rather than discoverable liability — do not relax in implementation.
