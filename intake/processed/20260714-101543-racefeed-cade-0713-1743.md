PROJECT: racefeed

# Apply the CADE prediction + track-record model to racefeed (horse-racing / feed-
# betting) — where prediction is the core product. Predict race outcomes, score
# every prediction against the actual result, publish the tier-gated track record.
# racefeed is Expo/RN with no build script; merge gate = the node test suite.
# Consumes the shared CADE engines (packages/cade-prediction + cade-publication).

- id: racefeed-race-predictor
  title: Race-outcome predictor logged for scoring against actual results
  material: yes
  model: sonnet
  depends: []
  proof: `node --test 'lib/**/*.test.ts'` exits 0 (incl. a new lib/__tests__ for the predictor)
  prompt: |
    Add lib/prediction/racePredictor.ts that turns a race's field/form/odds features
    into a scored set of outcome probabilities (win/place per entrant) and wraps them
    with rankNextEvents + toPrediction from the shared CADE engine
    (packages/cade-prediction; vendor from outputs/cade-prediction-src if the shared
    package is not yet wired). Record each prediction via a ledger seam BEFORE the race
    so it can be scored against the official result (Brier/log-loss). Add a colocated
    lib/__tests__ test for the probability normalization + scoring. This is the ideal
    self-improving domain: fast, frequent, objective resolution. Material: touches
    betting-adjacent predictions (advisory; no wager execution here).

- id: racefeed-trackrecord-screen
  title: Public/track-record screen for race-prediction accuracy (tier-gated)
  material: no
  model: sonnet
  depends: [racefeed-race-predictor]
  proof: `node --test 'lib/**/*.test.ts'` exits 0
  prompt: |
    Add a track-record view (RN screen) rendering racefeed's resolved race-prediction
    accuracy/calibration via the shared cade-publication engine (buildTrackRecordArticle
    data; vendor from outputs/cade-publication-src if needed). Tier-gated: "learning in
    progress" with progress-to-80% until a tier is earned (n>=100 conservative), then
    the scored track record. Because racing resolves fast, this domain likely hits the
    tiers first — a strong early public proof point. Add a pure test for the summary
    builder. Read-only.

OPERATOR:
  - Race predictions are advisory; keep separate from any wager-execution path (compliance).
  - Nothing publishes until the race-prediction domain earns a tier and you approve.
