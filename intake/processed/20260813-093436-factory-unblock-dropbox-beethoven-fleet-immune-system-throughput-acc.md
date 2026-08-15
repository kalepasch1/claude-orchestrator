PROJECT: beethoven

- id: factory-unblock-dropbox-beethoven-fleet-immune-system-throughput-acc
  title: Unblock dropbox-beethoven-fleet-immune-system-throughput-accelerators-operat-2-machine-pipeline-heartbeat-alerts-p0 (stuck CONFLICT)
  material: no
  proof: npm --prefix packages/darwin-kernel run test
  prompt: |
    Task 'dropbox-beethoven-fleet-immune-system-throughput-accelerators-operat-2-machine-pipeline-heartbeat-alerts-p0' has been stuck in state CONFLICT for over 60 minutes. Recorded note: train: still conflicts after 4 redos - needs manual rebase. Conflicting files: packages/darwin-kernel/src/passport/passport.ts.
    
    Diagnose the root cause (build failure, merge conflict, flaky test, or a genuine blocker needing a design decision) and fix it, or if it's a duplicate/obsolete task, close it with a reason. Do not just retry blindly — read the actual error.
