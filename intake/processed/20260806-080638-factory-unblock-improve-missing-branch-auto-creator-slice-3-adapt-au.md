PROJECT: beethoven

- id: factory-unblock-improve-missing-branch-auto-creator-slice-3-adapt-au
  title: Unblock improve-missing-branch-auto-creator-slice-3-adapt-auto-branch-patch (stuck TESTFAIL)
  material: no
  proof: npm --prefix packages/darwin-kernel run test
  prompt: |
    Task 'improve-missing-branch-auto-creator-slice-3-adapt-auto-branch-patch' has been stuck in state TESTFAIL for over 60 minutes. Recorded note: train: tests failed on rebased agent/improve-missing-branch-auto-creator-slice-3-adapt-auto-branch-patch: overlay:ea9dae2a6bfb nstantiate a capability across products (0.303458ms)
    ✔ engage halts all registered products and produces receipts (73.799ms)
    ✔ disengage restores all products (2.420375ms)
    ✔ propa
    
    Diagnose the root cause (build failure, merge conflict, flaky test, or a genuine blocker needing a design decision) and fix it, or if it's a duplicate/obsolete task, close it with a reason. Do not just retry blindly — read the actual error.
