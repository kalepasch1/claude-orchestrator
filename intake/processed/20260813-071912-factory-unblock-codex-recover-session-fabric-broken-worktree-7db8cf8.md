PROJECT: beethoven

- id: factory-unblock-codex-recover-session-fabric-broken-worktree-7db8cf8
  title: Unblock codex-recover-session-fabric-broken-worktree-7db8cf82 (stuck SHELVED)
  material: no
  proof: npm --prefix packages/darwin-kernel run test
  prompt: |
    Task 'codex-recover-session-fabric-broken-worktree-7db8cf82' has been stuck in state SHELVED for over 60 minutes. Recorded note: shelved by queue-velocity PID (low EV, integral too high)
    
    Diagnose the root cause (build failure, merge conflict, flaky test, or a genuine blocker needing a design decision) and fix it, or if it's a duplicate/obsolete task, close it with a reason. Do not just retry blindly — read the actual error.
