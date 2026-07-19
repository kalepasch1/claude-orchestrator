PROJECT: apparently

# Public per-app track-record page for apparently's next-regulatory predictions.
# Consumes shared packages/cade-publication. Follow apparently RLS + typed-client
# conventions. Prod build gate.

- id: apparently-trackrecord-page
  title: Public track-record page for next-compliance-exam / regulatory predictions
  material: no
  model: sonnet
  depends: [apparently-nextx-adopt]
  proof: `npm run build` exits 0
  prompt: |
    Add a public /insights/accuracy page rendering apparently's resolved next-
    regulatory prediction track record via packages/cade-publication
    (buildTrackRecordArticle + buildSeo + JSON-LD). Tier-gated: private "learning in
    progress" with progress-to-80% until a tier is earned, then the scored accuracy/
    calibration + per-domain breakdown (aggregate/redacted — never a named client's
    predicted exam). Vendor from outputs/cade-publication-src if the shared package is
    not yet wired. Read-only; RLS default-deny; keep the prod build green.

OPERATOR:
  - Counsel review before any regulatory-prediction accuracy is shown publicly; publish aggregate/redacted only, tier-gated.
