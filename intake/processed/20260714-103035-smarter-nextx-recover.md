PROJECT: smarter
- id: smarter-nextx-adopt
  title: Predict a client's next request / legal issue and log it for scoring
  material: yes
  model: sonnet
  depends: [tomorrow:cade-prediction-extract]
  proof: `npm run build` exits 0
  prompt: |
    Add server/utils/nextClientPredictor.ts: from a client's matter/interaction history,
    scored candidate next events (request, legal issue, license, filing) via rankNextEvents +
    toPrediction from packages/cade-prediction (vendor from outputs/cade-prediction-src if not
    wired). Record via ledger seam for scoring vs the realized matter. Read-only
    server/api/predict/next-client.post.ts. Material: client data.
- id: smarter-prediction-scorecard
  title: Prediction scorecard - accuracy vs actual, per associate/matter
  material: no
  model: sonnet
  depends: [smarter-nextx-adopt]
  proof: `npm run build` exits 0
  prompt: |
    GET /api/predict/scorecard via buildTrackRecord + aggregateExpert over resolved
    predictions, by associate/model, + a scorecard panel in the dashboard. Keep build green.
OPERATOR:
  - Confirm the matter-outcome source that resolves next-client predictions.
