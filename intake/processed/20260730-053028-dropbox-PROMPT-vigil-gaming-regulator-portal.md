# Vigil × Apparently — Gaming Regulator Portal (build now)

Operator directive 2026-07-30. Build the regulator-facing compliance portal for GAMING regulators
first, aligned with the existing Vigil compliance-portal architecture (vigil repo:
`vigil_supervisory_fabric`, `vigil_fabric_regulator_profiles`, examiner-agent and official-source
tables) and Apparently's compliance passport / regulator intake portal (migrations 337/339).

## Objective
A read-only, consent-gated portal a gaming regulator can open and see a licensed operator's LIVE
compliance posture — the full comprehensive exam materials organized, analyzed, and pre-responded,
exactly as the Vigil examiner-agent flow does: exam request → evidence mapping → draft responses →
examiner view. If one agency adopts it we become infrastructure, not a vendor.

## Scope (in order)
1. Exam-material canon for gaming: ingest the standard exam/audit request lists for NV, NJ, PA, MI
   (internal controls, AML program, RG program, key-person files, financials, technical standards)
   into a structured checklist model keyed by jurisdiction + license type.
2. Evidence mapping: connect each checklist item to the operator's live artifacts (Apparently
   compliance data, Foulkon verdict cards, document vault) with freshness badges — "verified
   against law as of N minutes ago" — and gap flags where evidence is missing.
3. Pre-drafted responses: for each exam item, a standing draft response memo (gauntlet-reviewed,
   citation-backed) that updates when underlying evidence or authority changes.
4. Regulator view: read-only, consent-gated (operator grants per-agency access, revocable,
   watermarked, full audit log of what the regulator viewed). Soft-nudge instrumentation: every
   operator-side exam-prep surface includes "invite your regulator" with the one-pager on why
   examiners save weeks.
5. Same posture rules as Vigil: no raw entity ranking, no cross-operator leakage, receipts/digests
   on everything.

## Constraints
- Reuse the Vigil tables/flows wherever they exist; extend, don't fork.
- All new tables RLS default-deny; regulator role sees only consented workspaces.
- Every AI-drafted response is labeled draft, operator-approved before any regulator can see it.
- 50-500X hooks: response drafts carry the verdict-card authority chain so an examiner can click
  through to the operative rule; exam-prep time is measured and shown ("prepared in 3 days, not
  3 months") as the marketing stat.
