PROJECT: beethoven

- id: factory-unblock-canary-xai-6
  title: Unblock canary-xai-6 (stuck TESTFAIL)
  material: no
  proof: npm --prefix packages/darwin-kernel run test
  prompt: |
    Task 'canary-xai-6' has been stuck in state TESTFAIL for over 60 minutes. Recorded note: train: tests failed on rebased agent/canary-xai-6: overlay:40c70bc90bc7 e cohorts; reproducible with seed (0.06625ms)
    ✔ secureSum refuses below k-floor, sums above (0.04475ms)
    ✔ publish + discover + instantiate a capability across products (0.190458ms

    Diagnose the root cause (build failure, merge conflict, flaky test, or a genuine blocker needing a design decision) and fix it, or if it's a duplicate/obsolete task, close it with a reason. Do not just retry blindly — read the actual error.
