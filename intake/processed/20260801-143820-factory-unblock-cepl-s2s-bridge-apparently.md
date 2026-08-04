PROJECT: apparently

- id: factory-unblock-cepl-s2s-bridge-apparently
  title: Unblock cepl-s2s-bridge-apparently (stuck BLOCKED)
  material: no
  proof: npm run typecheck
  prompt: |
    Task 'cepl-s2s-bridge-apparently' has been stuck in state BLOCKED for over 60 minutes. Recorded note: train: approved, but agent/cepl-s2s-bridge-apparently is still missing after 4 rebuilds
    
    Diagnose the root cause (build failure, merge conflict, flaky test, or a genuine blocker needing a design decision) and fix it, or if it's a duplicate/obsolete task, close it with a reason. Do not just retry blindly — read the actual error.
