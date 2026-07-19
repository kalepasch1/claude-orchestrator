PROJECT: pareto-2080

# Public per-app track-record page for pareto's next-life predictions. Consumes
# shared packages/cade-publication. Prod build gate.

- id: pareto-trackrecord-page
  title: Public track-record page for next-goal / next-life predictions (tier-gated)
  material: no
  model: sonnet
  depends: [pareto-nextx-adopt]
  proof: `npm run build` exits 0
  prompt: |
    Add a public /insights/accuracy page rendering pareto's resolved next-life
    prediction track record via packages/cade-publication (buildTrackRecordArticle +
    buildSeo + JSON-LD). Tier-gated: private "learning in progress" with progress-to-
    80% until a tier is earned, then the scored accuracy/calibration + per-domain
    breakdown (aggregate/redacted — never an individual user's predicted life event).
    Vendor from outputs/cade-publication-src if the shared package is not yet wired.
    Read-only; keep the prod build green.

OPERATOR:
  - Aggregate/redacted only; nothing publishes until a domain earns a tier and you approve.
