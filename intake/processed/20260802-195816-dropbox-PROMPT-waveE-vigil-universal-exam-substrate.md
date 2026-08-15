# WAVE E: Vigil universal exam substrate — coverage audit + MC exam simulation into Foulkon
# (operator directive 2026-07-31, CRITICAL — root-cause of a coverage blind spot)

project: vigil

## WHY THIS EXISTS (root cause)
Vigil has real exam-prep machinery (examiner workbench, records, assurance, evidence,
interagency reuse, ecosystem routing) — but it is DEMAND-DRIVEN and SCOPE-LIMITED: it prepares
what it is asked about, from the sources wired to it. Nobody ever asserted the inverse property:
"EVERY repo, email, document folder, user action, and decision across ALL apps is continuously
exam-covered, and the gaps are named." So a coverage gap could not be detected — there was no
coverage MEASUREMENT, only per-request preparation. This wave makes coverage a first-class,
continuously-measured property and feeds the simulation output into Foulkon's gradient.

## E1 — UNIVERSAL COVERAGE LEDGER (build first)
Enumerate every EXAMINABLE SURFACE across the ecosystem and assert coverage per surface:
  repos (every app + orchestrator), email domains/mailboxes, document folders/data rooms,
  user populations + their actions, decisions (Foulkon gradients, approvals, policy changes,
  releases), filings, contracts, positions/hedges, vendor relationships, marketing artifacts.
For each: is it INGESTED, MAPPED to requirements, EVIDENCED, and CURRENT (freshness)?
Emit a per-surface coverage score + a NAMED GAP LIST (never a silent zero). Alert as CRITICAL
when a surface has activity but no coverage — the exact failure class that hid this.
Publish coverage to the progress console and to Apparently's compliance dashboard.

## E2 — CONTINUOUS EXAM SIMULATION (the Monte-Carlo engine)
Run standing simulated examinations per jurisdiction/regime against the CURRENT state of the
covered surfaces — not a point-in-time snapshot:
  - sample exam-item canon (existing regulator MC work) × the org's actual evidence state;
  - simulate examiner sampling, document requests, follow-ups, and findings;
  - output: probability of finding by category, expected finding severity, expected remediation
    cost + time, and the SPECIFIC evidence gaps that drive each — with the exact document or
    control that would close it.
Run on schedule + on material change (new decision, new filing, new repo activity).

## E3 — FEED FOULKON'S GRADIENT (the missing wire)
Every Foulkon gradient option is scored THROUGH the exam simulation before display:
  - each steering option is simulated as a hypothetical state ("if we take this path, here is
    the exam posture that results") — so `expected_loss_usd` and `p_action` in EnforcementSpec
    are derived from simulated examinations, not priors alone;
  - options that improve exam posture are surfaced as such ("this path also closes 3 open
    evidence gaps in NJ");
  - options that degrade it carry the cost explicitly;
  - the exam-derived evidence gap list becomes 1-click remediation tasks (File & Resolve).
Contract: publish an S2S endpoint Foulkon calls per option (HMAC, cached, fail-soft — never
block the gradient; enrich asynchronously like the hedge bridge).

## E4 — EVIDENCE AUTO-HARVEST
Where a gap is closable from existing systems, close it automatically: repo commits/PR reviews
as change-control evidence; approval records as authorization evidence; provenance-graph edges
as decision-rationale evidence; email threads (consented, scoped) as notice/communication
evidence. Human review only for what auto-harvest cannot establish.

## E5 — CONTINUOUS EXAMINATION READINESS (client-facing product)
A scoped, read-only, cryptographically verifiable view a regulator or investor can be given —
live, never assembled in a panic. Per-requirement: satisfied / gap / in-progress, with evidence
links and provenance. This is the artifact that makes exam preparation a permanent STATE rather
than an event, and it doubles as the sales proof (prospects see rigor before buying).

## E6 — 100X EXTENSIONS
- SUCCESSION LAYER: when a compliance officer/GC/key person departs, their decisions,
  rationales, relationships, pending obligations, and unwritten context are already in the
  matter spine + provenance graph — successor onboards in hours. Departures become non-events.
- CROSS-CLIENT PATTERN PRIORS (k-anonymized): what examiners actually ask across the client
  base sharpens every simulation without exposing any client.
- EXAM-DRIVEN ROADMAP: aggregate simulated findings rank the product/compliance backlog by
  expected regulatory cost avoided — the roadmap is written by the simulation.

BINDING: no insurance framing anywhere — Tomorrow instruments are SWAPS/parametric risk
transfer under the existing ECP/bilateral posture; Vigil outputs are evidence and simulation,
never guarantees. Consent + scope required for any email/document ingestion. Tests per module.
Commits kalepasch1 <kalepasch@gmail.com>.
