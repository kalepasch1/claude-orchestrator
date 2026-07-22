PROJECT: beethoven

- id: factory-unblock-canary-gpt-1-slice-1
  title: Unblock canary-gpt-1-slice-1 (stuck BLOCKED)
  material: no
  proof: npm test
  prompt: |
    Task 'canary-gpt-1-slice-1' has been stuck in state BLOCKED for over 60 minutes. Recorded note: groomed: duplicate queued slug
    
    Diagnose the root cause (build failure, merge conflict, flaky test, or a genuine blocker needing a design decision) and fix it, or if it's a duplicate/obsolete task, close it with a reason. Do not just retry blindly — read the actual error.
