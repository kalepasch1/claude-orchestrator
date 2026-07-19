PROJECT: santas-secret-workshop

# Apply the CADE model to SSW WHERE RELEVANT + child-safe: PARENT-facing gift
# guidance (predict a household's likely next gift interest / redemption) — NEVER
# child-targeting or child behavioral profiling. Scored against actual outcomes to
# improve; track record aggregate/redacted only. SSW build = build:web; tests = node
# --test. Consumes shared CADE engines. CHILD-SAFETY gated.

- id: ssw-gift-guidance-predictor
  title: Parent-facing gift-interest predictor (child-safe), logged for scoring
  material: yes
  model: sonnet
  depends: []
  proof: `npm run build:web` exits 0
  prompt: |
    Add lib/prediction/giftGuidance.ts that, from PARENT/household-level, non-minor
    signals (wishlist/registry activity, prior redemptions at the household level),
    predicts the likely next gift interest / redemption and wraps it with rankNextEvents
    + toPrediction from the shared CADE engine (packages/cade-prediction; vendor from
    outputs/cade-prediction-src if not yet wired). STRICT child-safety: no per-child
    behavioral profiling, no targeting minors, run through checkContent()/the existing
    ai_safety guardrails, and enforce the age<18 boundaries. Record via a ledger seam for
    scoring against the realized gift/redemption. Add a lib/__tests__ test for the pure
    ranking + a guardrail test. Material: touches child-adjacent data (safety-gated).

- id: ssw-trackrecord-aggregate
  title: Aggregate, redacted gift-guidance accuracy track record (tier-gated)
  material: no
  model: sonnet
  depends: [ssw-gift-guidance-predictor]
  proof: `npm run build:web` exits 0
  prompt: |
    Add an AGGREGATE, fully-redacted track-record summary (household-level only, never
    a child) of gift-guidance accuracy via the shared cade-publication engine, tier-
    gated (nothing shown until >=80% + n>=100). Internal/admin-facing by default; any
    public surface is aggregate-only. Add a pure test for the summary builder. Read-only.

OPERATOR:
  - Child-safety + legal review REQUIRED before any gift-prediction feature ships or any accuracy is shown; household-level + aggregate only, opt-in, never targeting minors.
