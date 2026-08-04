PROJECT: racefeed

- id: factory-unblock-toolchain-repair-6096aa2b-fix-node-modules-install-s
  title: Unblock toolchain-repair-6096aa2b-fix-node-modules-install-slice-5 (stuck SHELVED)
  material: no
  proof: npm test
  prompt: |
    Task 'toolchain-repair-6096aa2b-fix-node-modules-install-slice-5' has been stuck in state SHELVED for over 60 minutes. Recorded note: shelved by queue-velocity PID (low EV, integral too high)
    
    Diagnose the root cause (build failure, merge conflict, flaky test, or a genuine blocker needing a design decision) and fix it, or if it's a duplicate/obsolete task, close it with a reason. Do not just retry blindly — read the actual error.
