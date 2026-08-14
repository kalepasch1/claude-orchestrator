PROJECT: beethoven

- id: factory-unblock-canary-claude-73-slice-1
  title: Unblock canary-claude-73-slice-1 (stuck TESTFAIL)
  material: no
  proof: npm --prefix packages/darwin-kernel run test
  prompt: |
    Task 'canary-claude-73-slice-1' has been stuck in state TESTFAIL for over 60 minutes. Recorded note: train: tests failed on rebased agent/canary-claude-73-slice-1: overlay:898b378364e3 for large cohorts; reproducible with seed (0.195667ms)
    ✔ secureSum refuses below k-floor, sums above (0.143375ms)
    ✔ publish + discover + instantiate a capability across products (

    Diagnose the root cause (build failure, merge conflict, flaky test, or a genuine blocker needing a design decision) and fix it, or if it's a duplicate/obsolete task, close it with a reason. Do not just retry blindly — read the actual error.
