PROJECT: tomorrow

- id: factory-unblock-chatgpt-local-reconcile-tomorrow-6f451eba9449
  title: Unblock chatgpt-local-reconcile-tomorrow-6f451eba9449 (stuck BLOCKED)
  material: no
  proof: npm test
  prompt: |
    Task 'chatgpt-local-reconcile-tomorrow-6f451eba9449' has been stuck in state BLOCKED for over 60 minutes. Recorded note: cowork-executor-v6.5 HALT: not completed — prior attempt pushed a REGRESSION. Branch agent/chatgpt-local-reconcile-tomorrow-6f451eba9449 carries pages/index.vue blob 7b8364f5c, byte-identical across 5 sibling reconcile branches. Two-dot diff vs origin/main reverts commit a933b6659 "fix(landing): match .home-nav to the page background" (.home-nav background #000000 -> legacy linear-gradient). Cause: worktree cut from stale base b431cb921 (2026-08-07) instead of origin/main (2026-08-11); legacy pages/index.vue copied over current file, violating the task prompt's own rule "newest/most complete implementation wins". DO NOT MERGE these 5 branches. Needs human review + rebase onto current origin/main before any merge-train pickup. No new commit made this run (would have replicated the revert).
    
    Diagnose the root cause (build failure, merge conflict, flaky test, or a genuine blocker needing a design decision) and fix it, or if it's a duplicate/obsolete task, close it with a reason. Do not just retry blindly — read the actual error.
