PROJECT: racefeed

- id: relfix-v15-racefeed-f0a41d3a
  title: relfix-v15-racefeed-f0a41d3a
  material: no
  model: 
  submitted-by: Codex operator-directed remediation
  depends: []
  proof: No conflict markers remain; the focused common-brain test and production build pass; the release train records a successful racefeed release newer than failed SHA f0a41d3a.
  prompt: |
    Repair the current release blocker at f0a41d3a only. The release train reports a merge conflict in lib/commonBrain.test.ts while refreshing staging/prod. Reproduce against the current integration and production branches, preserve compatible assertions from both sides, remove every conflict marker, run the focused common-brain test plus the repository production build, and commit the minimal resolution. Then return it to the existing release train; do not deploy directly. Record the resolved branch heads and test evidence so release backpressure can turn green.
