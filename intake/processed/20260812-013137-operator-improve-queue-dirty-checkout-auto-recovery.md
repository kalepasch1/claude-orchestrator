PROJECT: beethoven

- id: improve-queue-dirty-checkout-auto-recovery
  title: improve-queue-dirty-checkout-auto-recovery
  material: no
  model: 
  submitted-by: Codex operator-directed remediation
  depends: []
  proof: New dirty-checkout recovery tests pass and a fixture repo 16 commits behind with compatible local edits converges to a clean layered head without data loss.
  prompt: |
    Implement durable dirty-checkout recovery for the orchestrator host. When tracked changes block fleet auto-pull, acquire the maintenance fence, inventory and test the changes, preserve them on a named recovery ref or validated commit, integrate upstream without overwriting compatible work, and resume only from a clean checkout. Never stash or reset untracked operator evidence. Publish an approval/incident card with before/after SHAs, changed files, tests, and any quarantined residue. Add tests for clean fast-forward, valid dirty layer, invalid dirty layer, concurrent writer, and upstream overlap.
    
    Queue context: The live host remained behind because 26 tracked changes blocked auto-pull; this closes that indefinite stall mode.
