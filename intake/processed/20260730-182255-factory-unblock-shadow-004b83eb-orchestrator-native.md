PROJECT: apparently-law

- id: factory-unblock-shadow-004b83eb-orchestrator-native
  title: Unblock shadow-004b83eb-orchestrator_native (stuck BLOCKED)
  material: no
  proof: npm run typecheck
  prompt: |
    Task 'shadow-004b83eb-orchestrator_native' has been stuck in state BLOCKED for over 60 minutes. Recorded note: verify: Added allowlist and secrets without proper authentication or authorization, which could lead to security vulnerabilities.
    
    Diagnose the root cause (build failure, merge conflict, flaky test, or a genuine blocker needing a design decision) and fix it, or if it's a duplicate/obsolete task, close it with a reason. Do not just retry blindly — read the actual error.
