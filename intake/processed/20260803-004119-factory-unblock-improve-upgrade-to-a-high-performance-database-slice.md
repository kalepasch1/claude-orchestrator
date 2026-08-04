PROJECT: beethoven

- id: factory-unblock-improve-upgrade-to-a-high-performance-database-slice
  title: Unblock improve-upgrade-to-a-high-performance-database-slice-3 (stuck SHELVED)
  material: no
  proof: npm --prefix packages/darwin-kernel run test
  prompt: |
    Task 'improve-upgrade-to-a-high-performance-database-slice-3' has been stuck in state SHELVED for over 60 minutes. Recorded note: shelved by queue-velocity PID (low EV, integral too high)
    
    Diagnose the root cause (build failure, merge conflict, flaky test, or a genuine blocker needing a design decision) and fix it, or if it's a duplicate/obsolete task, close it with a reason. Do not just retry blindly — read the actual error.
