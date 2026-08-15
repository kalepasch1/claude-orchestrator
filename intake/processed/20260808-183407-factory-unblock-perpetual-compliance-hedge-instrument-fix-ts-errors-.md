PROJECT: tomorrow

- id: factory-unblock-perpetual-compliance-hedge-instrument-fix-ts-errors-
  title: Unblock perpetual-compliance-hedge-instrument-fix-ts-errors-and-run-tests-run-tests (stuck CONFLICT)
  material: no
  proof: npm test
  prompt: |
    Task 'perpetual-compliance-hedge-instrument-fix-ts-errors-and-run-tests-run-tests' has been stuck in state CONFLICT for over 60 minutes. Recorded note: train: still conflicts after 4 redos - needs manual rebase. Conflicting files: server/utils/risk/__tests__/covenantVerifier.test.ts
    server/utils/risk/covenantVerifier.ts.
    
    Diagnose the root cause (build failure, merge conflict, flaky test, or a genuine blocker needing a design decision) and fix it, or if it's a duplicate/obsolete task, close it with a reason. Do not just retry blindly — read the actual error.
