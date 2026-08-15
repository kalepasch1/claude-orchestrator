PROJECT: smarter

- id: relfix-v15-smarter-c7599db3
  title: relfix-v15-smarter-c7599db3
  material: no
  model: 
  submitted-by: Codex operator-directed remediation
  depends: []
  proof: Smarter's public-copy gate and production build pass, and the release train records a successful release newer than failed SHA c7599db3.
  prompt: |
    Repair the current Smarter release copy-gate blocker at c7599db3. The gate flags pages/approve.vue around line 130 for publicly naming a proprietary mechanism ('CADE support Inspect'). Rewrite only the public-facing copy to value-level language while preserving routing, accessibility, tests, and behavior. Run the repository's public-copy gate and production build, then return the commit to the release train; do not deploy directly or suppress the gate.
