# RAISE — autonomous fundraising layer for the orchestrator

Target repo: claude-orchestrator (new subsystem, e.g. runner/raise/ + web console tab).
Source spec: REVIEW v3 §7 (F1–F7). Integrates: A6 deadline engine (grant windows), R2 data-room infra (investor data rooms), SC2 interaction-playbook machinery (send-time/channel optimization), G13 allocator, G16 ROI attribution, Smarter inbox contract (see smarter prompt item 7).

## Objectives

1. **F1 Target graph** — crawled, continuously refreshed profiles: VCs (thesis/stage/check/partner interests/recent deals), state+federal grants (SBIR/STTR, state funds; windows on deadline engine), accelerators/incubators (cohorts), strategic corporates; per-app match scores. Proof: profile freshness + match-score tests.
2. **F2 Pitch factory + investor data rooms** — per-app pitch kits auto-generated from live product state (decks, one-pagers, financial models, demo links); investor data room per app reusing R2 infra (queryable, receipts-backed, access-logged). Proof: kit generation from fixture app state; data-room access-log test.
3. **F3 A/B optimization with truth gate** [MATERIAL] — variants differ in narrative/ordering/branding/subject/deck emphasis per segment; bandit allocation on reply/meeting/term rates. HARD INVARIANT (kernel constitution): every quantitative claim in every variant resolves to a signed receipt in the facts ledger — A/B varies framing, never facts; test `unreceipted_claim_in_outreach` → deny. Grant certifications/signatures route to accountable human via Smarter flagged task (fail-closed). Proof: truth-gate fail-closed test; bandit allocation test.
4. **F4 Outreach engine** — sequenced personalized outreach, send-time optimization, response classification, diligence auto-answers from data room, meeting auto-scheduling; rate-limited + reputation-aware (match score gates volume; never spray). Proof: rate-limit and gating tests.
5. **F5 Live pitch refresh** — app progress events (merges, revenue/RUM receipts, milestones) auto-update all live pitches + notify engaged investors with delta summaries. Proof: fixture event propagates to fixture pitch + notification.
6. **F6 Human funnel** — meetings/term discussions/signatures → Smarter inbox flagged actions with context packs (who, thesis, history, talking points). Nothing binding is ever executed autonomously — commitments, term acceptance, signatures are human-only [MATERIAL, constitution-enforced]. Proof: binding-action deny test.
7. **F7 Allocator tie-in** — RAISE effort weighted by G13 (traction × capital need); RAISE activity ROI-attributed via G16. Proof: allocation test on fixture portfolio.
