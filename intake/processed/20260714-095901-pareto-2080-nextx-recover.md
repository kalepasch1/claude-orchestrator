PROJECT: pareto-2080
- id: pareto-nextx-adopt
  title: Predict next goal / license / life-event and log for scoring
  material: yes
  model: sonnet
  depends: [tomorrow:cade-prediction-extract]
  proof: `npm run build` exits 0
  prompt: |
    Add server/utils/nextLifePredictor.js: from profile+goals+spend+life-event signals
    (reuse predictionSignals/LifeEvents), scored candidate next events via rankNextEvents +
    toPrediction from packages/cade-prediction (vendor from outputs/cade-prediction-src if
    not wired). Record via ledger seam. Read-only server/api/predict/next-life.post.js.
- id: pareto-predictive-prestage
  title: Pre-stage the likely next financial action behind the approval inbox
  material: yes
  model: sonnet
  depends: [pareto-nextx-adopt]
  proof: `npm run build` exits 0
  prompt: |
    On confidence threshold, pre-stage a Tier-A/B proposal in the Approvals inbox (reuse
    agentLedger/approvalPolicy) - goal->funding plan, license->checklist. Proposal only,
    never auto-moves money. Material: approval proposals.
OPERATOR:
  - Confirm the realized-event source that resolves next-life predictions.
