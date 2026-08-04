PROJECT: vigil

- id: factory-unblock-recover-missing-branch-remediate-weekly-lint-vigil-a
  title: Unblock recover-missing-branch-remediate-weekly-lint-vigil-add-weekly-ci-workflow-d41219-run-lint-script (stuck BLOCKED)
  material: no
  proof: npm run release:gate
  prompt: |
    Task 'recover-missing-branch-remediate-weekly-lint-vigil-add-weekly-ci-workflow-d41219-run-lint-script' has been stuck in state BLOCKED for over 60 minutes. Recorded note: bankrupted 2026-08-02: quarantine backlog reached 717 rows against 79 lifetime completions. Cleared in bulk to stop rework chains respawning; re-open individually if still wanted.
    
    Diagnose the root cause (build failure, merge conflict, flaky test, or a genuine blocker needing a design decision) and fix it, or if it's a duplicate/obsolete task, close it with a reason. Do not just retry blindly — read the actual error.
