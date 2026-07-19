PROJECT: apparently
- id: apparently-nextx-adopt
  title: Predict next compliance exam / regulatory issue and log for scoring
  material: yes
  model: sonnet
  depends: [tomorrow:cade-prediction-extract]
  proof: `npm run build` exits 0
  prompt: |
    Add server/engines/prediction/nextRegulatoryPredictor.ts: from licensing/regulatory
    profile + regulator-intel feeds, scored candidate next events (exam incl unscheduled,
    enforcement/regulatory issue, required disclosure) via rankNextEvents + toPrediction from
    packages/cade-prediction (vendor from outputs/cade-prediction-src if not wired). Record
    via ledger seam. Read-only API route (typed Supabase client + Zod; RLS default-deny).
- id: apparently-exam-readiness-prestage
  title: Pre-build exam-readiness pack when a predicted exam crosses threshold
  material: yes
  model: sonnet
  depends: [apparently-nextx-adopt]
  proof: `npm run build` exits 0
  prompt: |
    On threshold, pre-assemble a readiness pack (filings, gaps, disclosure checklist) as a
    draft. Reuse disclosure/regulator-intel engines; log AI calls. Material: client artifact.
OPERATOR:
  - Confirm the realized-outcome source. Counsel review before showing a predicted unscheduled exam.
