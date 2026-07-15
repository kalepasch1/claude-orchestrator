PROJECT: smarter

# Public per-app track-record page — the portfolio-wide scoreboard. Consumes the
# shared packages/cade-publication (tiered gate + article + SEO). Prod build gate.

- id: smarter-trackrecord-page
  title: Public track-record page for smarter's next-X predictions (tier-gated)
  material: no
  model: sonnet
  depends: [smarter-nextx-adopt]
  proof: `npm run build` exits 0
  prompt: |
    Add a public /insights/accuracy page rendering smarter's resolved next-client
    prediction track record via packages/cade-publication (buildTrackRecordArticle +
    buildSeo + JSON-LD via useHead). GATED by the tiered gate: shows a private
    "learning in progress" state with progress-to-80% until the domain earns a tier,
    then renders the scored accuracy/calibration + per-domain breakdown. If the shared
    package is not yet wired cross-repo, vendor the small pure engine from
    outputs/cade-publication-src. Read-only; keep the prod build green.

OPERATOR:
  - Nothing renders publicly until smarter's prediction domain earns a tier (>=80%, n>=100) AND you approve in the admin console.
