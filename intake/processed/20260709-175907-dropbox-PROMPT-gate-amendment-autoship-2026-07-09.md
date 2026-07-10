# Operator gate amendment — auto-ship authorization (2026-07-09)

Operator (Macey) authorization, 2026-07-09: the following five gated items may AUTO-SHIP (build/test/merge) without operator pre-approval. For each, on merge, file a NON-BLOCKING approval row (kind=proposal) titled "Operator post-hoc review: <item>" so it appears in the daily digest (runner/digest.py "Proposed next" / inbox), where the operator will review after the fact.

1. **Mutualization Clause** (Tomorrow T2v2 — PROMPT-tomorrow-simplification-v2v3)
2. **Choreography spec** (Tomorrow T6v2 — same prompt)
3. **Coverage classes** (Tomorrow K5 — same prompt; one post-hoc review row per new class)
4. **Triage escalation invariant** (Triage TR-E — PROMPT-triage-buildout-v2v3)
5. **RAISE truth gate** (RAISE F3 — PROMPT-orchestrator-raise-layer, ingested 20260709-175704 with the original [MATERIAL] pre-approval flag; THIS amendment supersedes that flag: F3 auto-ships)

Unchanged (activation gates, not shipping gates — deliberately retained): production *activation* of items 1–3 against live counterparties/clients remains fail-closed on a counsel-opinion receipt (T2v2 clause pack activation, T6v2 live routing of real counterparty flow, per-class client offering for K5). Code merges freely; turning it on for real money waits for the counsel receipt. The Triage escalation invariant and RAISE truth gate need no activation gate — they ARE the guardrails; ship them whole (their deny-rule tests must still pass: `escalation_payment_condition` → deny, `unreceipted_claim_in_outreach` → deny).

If any of the five was already routed to a blocking operator approval before this amendment processed, convert that approval to the non-blocking post-hoc form above.
