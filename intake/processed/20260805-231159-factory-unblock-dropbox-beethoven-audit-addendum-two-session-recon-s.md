PROJECT: beethoven

- id: factory-unblock-dropbox-beethoven-audit-addendum-two-session-recon-s
  title: Unblock dropbox-beethoven-audit-addendum-two-session-recon-slice-2 (stuck TESTFAIL)
  material: no
  proof: npm --prefix packages/darwin-kernel run test
  prompt: |
    Task 'dropbox-beethoven-audit-addendum-two-session-recon-slice-2' has been stuck in state TESTFAIL for over 60 minutes. Recorded note: train: tests failed on rebased agent/dropbox-beethoven-audit-addendum-two-session-recon-slice-2: overlay:7f47a5018bfa capability across products (0.217791ms)
    ✔ engage halts all registered products and produces receipts (82.034834ms)
    ✔ disengage restores all products (0.665917ms)
    ✔ propagation rea

    Diagnose the root cause (build failure, merge conflict, flaky test, or a genuine blocker needing a design decision) and fix it, or if it's a duplicate/obsolete task, close it with a reason. Do not just retry blindly — read the actual error.
