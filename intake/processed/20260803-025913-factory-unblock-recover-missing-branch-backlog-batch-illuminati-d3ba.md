PROJECT: illuminati

- id: factory-unblock-recover-missing-branch-backlog-batch-illuminati-d3ba
  title: Unblock recover-missing-branch-backlog-batch-illuminati-d3ba8c6-weekly-lint-merge-master-checkout-branch-weekly (stuck BLOCKED)
  material: no
  proof: npx nuxi typecheck
  prompt: |
    Task 'recover-missing-branch-backlog-batch-illuminati-d3ba8c6-weekly-lint-merge-master-checkout-branch-weekly' has been stuck in state BLOCKED for over 60 minutes. Recorded note: bankrupted 2026-08-02: quarantine backlog reached 717 rows against 79 lifetime completions. Cleared in bulk to stop rework chains respawning; re-open individually if still wanted.

    Diagnose the root cause (build failure, merge conflict, flaky test, or a genuine blocker needing a design decision) and fix it, or if it's a duplicate/obsolete task, close it with a reason. Do not just retry blindly — read the actual error.
