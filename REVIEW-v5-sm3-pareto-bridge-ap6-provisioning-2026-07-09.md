# v5 addenda — SM-3 × Pareto leave-planning bridge + AP-6 execution-environment provisioning

Operator direction 2026-07-09. Two items: an opt-in bridge from the Smarter leave advisor into Pareto trip planning, and the missing provisioning that lets AP-6 actually run live. Dedup G7; reconciliation rules (ENHANCE vs NET-NEW) apply.

## 1. SM-3 ↔ Pareto Leave-to-Trip Bridge (opt-in, consented, user-owned)

When the SM-3 Leave/PTO Timing Advisor surfaces recommended leave windows, let the user (if they choose) hand those windows to Pareto to plan the actual time off — trips, vacations, family logistics — using existing Pareto capabilities.

- **Bridge shape**: narrow, explicit, consented — exactly the v5 §2 "bridge only where a real user journey exists" pattern (this is a professional↔personal hop, so it crosses the consent/barrier spine, v4 A-5). Default OFF; the associate opts in per-window ("plan this window in Pareto"). Nothing about the associate's leave or health ever flows back to Smarter partners (S4v2 boundary intact) or to their employer.
- **Handoff payload (minimal)**: dates + duration + optional soft prefs (budget band, destination type, who's coming) — NOT matter data, NOT workload/burnout telemetry, NOT firm info. Barrier receipt on the hop (what crossed, under which consent).
- **Pareto side (reuse existing capabilities — do NOT build new travel infra)**: P1 goal/state-machine + P2 delegation firewall + existing travel/negotiation/planning engines plan and (within the user's authority budget) book/hold: flights, lodging, itinerary, family coordination, cost optimization against their financial plan; surfaces as a ready-to-approve trip (never auto-charges beyond the trust-ratchet authority budget). 
- **Round-trip nicety**: once a trip is confirmed in Pareto, the SM-3 advisor marks that window "planned" and stops nudging for it; if firm-side critical dates later collide with a booked window, the associate is alerted early (SM-1 calendar watch) with Pareto re-accommodation options.
- **Identity/account model**: works whether or not the same human uses both apps under one passport — if they do (financial-cluster onboarding graph, B-1), it's one-click; if not, a lightweight consented link. Financial-cluster coordination already exists (passport/identity graph) — reuse it.
- Classification: ENHANCE — a consented bridge over existing SM-3, Pareto P1/P2, passport, and consent spine. NET-NEW only: the small handoff contract + barrier receipt + "planned" state sync. Proof: opt-in-required test (no handoff without consent); payload-minimization test (no matter/health/firm data in payload); barrier-receipt test; partner-isolation test (leave/trip data never reaches partner aggregate); authority-budget test (no booking beyond budget).

## 2. AP-6 execution-environment provisioning (unblock the live regulator tests)

AP-6 (live regulator-portal recon/dry-run/sandbox submission) cannot execute until its environment is provisioned. Make provisioning an explicit, gating prerequisite task so AP-6 doesn't silently no-op.

- **AP-6-PROV-a Chrome connectivity check** — AP-6 runs must verify the Claude-in-Chrome extension (or equivalent headless browser automation in the fleet's execution environment) is connected and reachable BEFORE attempting portal work; if absent, the run fails LOUD (opens a provisioning task + flags the launch gate as blocked), never silently passes. Determine whether the fleet can run browser automation server-side (headless) vs. requiring the operator's connected extension, and document which portals need which.
- **AP-6-PROV-b Credential & sandbox vault** — stand up a secrets-managed store (existing secrets handling / fleet_control safe-config pattern — NO secrets in code/repo, per house rules) for: per-portal test/sandbox accounts (NMLS test, FINRA CAT test, IARD test, etc.), sandbox API keys, and any non-production auth. Enumerate per target portal: does a sandbox exist, what credentials it needs, how to obtain them. Operator-provided secrets injected via the vault, never committed.
- **AP-6-PROV-c Provisioning gap report** — first AP-6 action is to produce a readiness matrix per portal: {browser-automatable? sandbox available? credentials provisioned? blockers}. Portals that are ready run immediately; portals that aren't open an operator action item (via Smarter/RAISE-style flagged task) listing exactly what's needed (e.g., "request NMLS test-env account"). This makes the human dependency explicit and actionable instead of a silent stall.
- **AP-6-PROV-d Degrade path** — where live/sandbox access isn't yet provisioned, AP-6 still runs READ-ONLY recon (public portal pages, published form specs, documented API schemas) so we capture requirements now and slot true-submission tests in as access lands. Never block all AP-6 value on full provisioning.
- **Constitution (unchanged, reinforced)**: `live_regulator_submit_without_operator` → deny; sandbox-only true submissions; synthetic data only; no real fees; provisioning secrets via vault only. Proof: fail-loud-on-missing-browser test; readiness-matrix output; degrade-to-recon test; secrets-not-in-repo lint.

## Queue
Cue both now. AP-6-PROV-* are prerequisites to AP-6 and therefore sit on the launch-gate critical path — schedule them first within the Apparently pre-launch block. SM-3↔Pareto bridge follows SM-3 core.
