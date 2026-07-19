PROJECT: tomorrow

- id: factory-unblock-warranty-constitution-gate
  title: Unblock warranty-constitution-gate (stuck BLOCKED)
  material: no
  proof: npm test
  prompt: |
    Task 'warranty-constitution-gate' has been stuck in state BLOCKED for over 60 minutes. Recorded note: executor-1: server/utils/cade/warranty/gates.ts does not exist on main - cannot fix call-site mismatch in nonexistent file
    
    Diagnose the root cause (build failure, merge conflict, flaky test, or a genuine blocker needing a design decision) and fix it, or if it's a duplicate/obsolete task, close it with a reason. Do not just retry blindly — read the actual error.
