PROJECT: smarter

- id: factory-unblock-contracts-smarter
  title: Unblock contracts-smarter (stuck BLOCKED)
  material: no
  proof: npx vue-tsc --noEmit
  prompt: |
    Task 'contracts-smarter' has been stuck in state BLOCKED for over 60 minutes. Recorded note: train: approved, but agent/contracts-smarter is still missing after 4 rebuilds

    Diagnose the root cause (build failure, merge conflict, flaky test, or a genuine blocker needing a design decision) and fix it, or if it's a duplicate/obsolete task, close it with a reason. Do not just retry blindly — read the actual error.
