PROJECT: vigil

- id: factory-unblock-canary-vigil-20260727
  title: Unblock canary-vigil-20260727 (stuck SHELVED)
  material: no
  proof: npm run release:gate
  prompt: |
    Task 'canary-vigil-20260727' has been stuck in state SHELVED for over 60 minutes. Recorded note: shelved by queue-velocity PID (low EV, integral too high)

    Diagnose the root cause (build failure, merge conflict, flaky test, or a genuine blocker needing a design decision) and fix it, or if it's a duplicate/obsolete task, close it with a reason. Do not just retry blindly — read the actual error.
