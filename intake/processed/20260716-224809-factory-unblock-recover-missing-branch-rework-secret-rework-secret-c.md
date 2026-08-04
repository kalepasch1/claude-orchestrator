PROJECT: smarter

- id: factory-unblock-recover-missing-branch-rework-secret-rework-secret-c
  title: Unblock recover-missing-branch-rework-secret-rework-secret-cont-e8ca57b5-8b2c573-2253ae5 (stuck BLOCKED)
  material: no
  proof: npx vue-tsc --noEmit
  prompt: |
    Task 'recover-missing-branch-rework-secret-rework-secret-cont-e8ca57b5-8b2c573-2253ae5' has been stuck in state BLOCKED for over 60 minutes. Recorded note: blocker-quarantine: escalated after 2+ rework attempts (category=legal); needs human review instead of another auto-rework. Last blocker: Repo path not in connected folders — inaccessible.
    
    Diagnose the root cause (build failure, merge conflict, flaky test, or a genuine blocker needing a design decision) and fix it, or if it's a duplicate/obsolete task, close it with a reason. Do not just retry blindly — read the actual error.
