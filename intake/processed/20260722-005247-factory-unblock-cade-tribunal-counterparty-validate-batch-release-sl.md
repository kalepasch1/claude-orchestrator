PROJECT: tomorrow

- id: factory-unblock-cade-tribunal-counterparty-validate-batch-release-sl
  title: Unblock cade-tribunal-counterparty-validate-batch-release--slice-3 (stuck TESTFAIL)
  material: no
  proof: npm test
  prompt: |
    Task 'cade-tribunal-counterparty-validate-batch-release--slice-3' has been stuck in state TESTFAIL for over 60 minutes. Recorded note: train: tests failed on rebased agent/cade-tribunal-counterparty-validate-batch-release--slice-3: overlay:8de58af9adc0 > test
    > npx vitest run
    
    node:internal/modules/esm/resolve:271
        throw new ERR_MODULE_NOT_FOUND(
              ^
    
    Error [ERR_MODULE_NOT_FOUND]: Cannot find module '/Users/kpasch/Doc
    
    Diagnose the root cause (build failure, merge conflict, flaky test, or a genuine blocker needing a design decision) and fix it, or if it's a duplicate/obsolete task, close it with a reason. Do not just retry blindly — read the actual error.
