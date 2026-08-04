PROJECT: tomorrow

- id: factory-unblock-cade-tribunal-counterparty
  title: Unblock cade-tribunal-counterparty (stuck BLOCKED)
  material: no
  proof: npm test
  prompt: |
    Task 'cade-tribunal-counterparty' has been stuck in state BLOCKED for over 60 minutes. Recorded note: train: immutable integration identity failed: remote-publish-failed
    
    Diagnose the root cause (build failure, merge conflict, flaky test, or a genuine blocker needing a design decision) and fix it, or if it's a duplicate/obsolete task, close it with a reason. Do not just retry blindly — read the actual error.
