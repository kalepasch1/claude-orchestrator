PROJECT: vigil

- id: factory-unblock-toolchain-repair-20e984ed
  title: Unblock toolchain-repair-20e984ed (stuck BLOCKED)
  material: no
  proof: npm run release:gate
  prompt: |
    Task 'toolchain-repair-20e984ed' has been stuck in state BLOCKED for over 60 minutes. Recorded note: bankrupted 2026-08-02: quarantine backlog reached 717 rows against 79 lifetime completions. Cleared in bulk to stop rework chains respawning; re-open individually if still wanted.

    Diagnose the root cause (build failure, merge conflict, flaky test, or a genuine blocker needing a design decision) and fix it, or if it's a duplicate/obsolete task, close it with a reason. Do not just retry blindly — read the actual error.
