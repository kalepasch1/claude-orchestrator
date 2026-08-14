PROJECT: beethoven

- id: factory-unblock-oc-autoclear-policy
  title: Unblock oc-autoclear-policy (stuck BLOCKED)
  material: no
  proof: npm --prefix packages/darwin-kernel run test
  prompt: |
    Task 'oc-autoclear-policy' has been stuck in state BLOCKED for over 60 minutes. Recorded note: train: approved, but agent/oc-autoclear-policy is still missing after 4 rebuilds

    Diagnose the root cause (build failure, merge conflict, flaky test, or a genuine blocker needing a design decision) and fix it, or if it's a duplicate/obsolete task, close it with a reason. Do not just retry blindly — read the actual error.
