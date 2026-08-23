PROJECT: tomorrow

- id: relfix-v15-tomorrow-43b1039e
  title: relfix-v15-tomorrow-43b1039e
  material: no
  model: 
  submitted-by: Codex operator-directed remediation
  depends: []
  proof: Tomorrow's production build and release preflight pass, and the release train records a successful release newer than failed SHA 43b1039e.
  prompt: |
    Repair the current Tomorrow release blocker at 43b1039e. Reproduce the production build failure involving components/segments/MarketSegmentExperience.vue, capture the complete compiler error, and make the smallest type/template/import correction that preserves behavior. Run the focused checks and full production build, then return the commit to the existing release train. Do not weaken build or public-copy gates and do not deploy directly.
