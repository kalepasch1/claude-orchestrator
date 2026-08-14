PROJECT: tomorrow

- id: factory-unblock-curation-coherence-bot
  title: Unblock curation-coherence-bot (stuck BLOCKED)
  material: no
  proof: npm test
  prompt: |
    Task 'curation-coherence-bot' has been stuck in state BLOCKED for over 60 minutes. Recorded note: train: approved, but agent/curation-coherence-bot is still missing after 4 rebuilds

    Diagnose the root cause (build failure, merge conflict, flaky test, or a genuine blocker needing a design decision) and fix it, or if it's a duplicate/obsolete task, close it with a reason. Do not just retry blindly — read the actual error.
