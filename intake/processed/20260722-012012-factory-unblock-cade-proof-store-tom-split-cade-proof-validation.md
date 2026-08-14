PROJECT: tomorrow

- id: factory-unblock-cade-proof-store-tom-split-cade-proof-validation
  title: Unblock cade-proof-store-tom-split-cade-proof-validation (stuck TESTFAIL)
  material: no
  proof: npm test
  prompt: |
    Task 'cade-proof-store-tom-split-cade-proof-validation' has been stuck in state TESTFAIL for over 60 minutes. Recorded note: train: tests failed on rebased agent/cade-proof-store-tom-split-cade-proof-validation: overlay:294ba9b1111d > test
    > npx vitest run

    node:internal/modules/esm/resolve:271
        throw new ERR_MODULE_NOT_FOUND(
              ^

    Error [ERR_MODULE_NOT_FOUND]: Cannot find module '/Users/kpasch/Doc

    Diagnose the root cause (build failure, merge conflict, flaky test, or a genuine blocker needing a design decision) and fix it, or if it's a duplicate/obsolete task, close it with a reason. Do not just retry blindly — read the actual error.
