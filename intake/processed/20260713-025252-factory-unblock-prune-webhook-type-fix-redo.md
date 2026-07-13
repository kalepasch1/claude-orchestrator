PROJECT: tomorrow

- id: factory-unblock-prune-webhook-type-fix-redo
  title: Unblock prune-webhook-type-fix-redo (stuck TESTFAIL)
  material: no
  proof: npm test
  prompt: |
    Task 'prune-webhook-type-fix-redo' has been stuck in state TESTFAIL for over 60 minutes. Recorded note: train: tests failed on rebased agent/prune-webhook-type-fix-redo: /__tests__/dbRoundtrip.test.ts (1 test | 1 skipped)
    
     Test Files  8 failed | 302 passed | 1 skipped (311)
          Tests  17 failed | 7814 passed | 1 skipped (7832)
       Start at  21:59:26
       Duration  36.
    
    Diagnose the root cause (build failure, merge conflict, flaky test, or a genuine blocker needing a design decision) and fix it, or if it's a duplicate/obsolete task, close it with a reason. Do not just retry blindly — read the actual error.
