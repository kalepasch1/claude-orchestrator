PROJECT: darwn

# darwn hosts the darwin-kernel (the shared primitives the CADE engines build on)
# and is a Nuxt content site. WHERE RELEVANT: publish the KERNEL'S OWN track record —
# the accuracy/calibration of CADE determinations that flow through the kernel — as a
# tier-gated insights page, so the kernel's site is itself proof of the primitives'
# quality. Consumes shared packages/cade-publication. Prod build (nuxt build) gate.

- id: darwn-kernel-trackrecord-insights
  title: Kernel-level CADE track-record / insights page (tier-gated)
  material: no
  model: sonnet
  depends: []
  proof: `npm run build` exits 0
  prompt: |
    Add a /insights/accuracy page rendering the darwin-kernel CADE determination track
    record (accuracy/calibration/tier) via packages/cade-publication (buildTrackRecord
    Article + buildSeo + JSON-LD via useHead). Read the resolved-prediction summary from
    the kernel/tomorrow CADE ledger behind an injected client (fixtures for now; live
    read is OPERATOR). Tier-gated: private "learning in progress" with progress-to-80%
    until a tier is earned. Vendor from outputs/cade-publication-src if the shared
    package is not yet wired. Read-only; keep the prod build green. If darwn's primary
    domain is not determination-accuracy, treat this as the kernel showcase page and
    note the intended domain for operator confirmation.

OPERATOR:
  - Confirm darwn's intended prediction domain (kernel determination accuracy assumed). Provide read-only ledger creds for the live track record.
