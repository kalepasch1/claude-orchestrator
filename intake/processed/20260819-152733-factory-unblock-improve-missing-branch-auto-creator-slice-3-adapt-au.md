PROJECT: beethoven

- id: factory-unblock-improve-missing-branch-auto-creator-slice-3-adapt-au
  title: Unblock improve-missing-branch-auto-creator-slice-3-adapt-auto-branch-patch (stuck CONFLICT)
  material: no
  proof: npm --prefix packages/darwin-kernel run test
  prompt: |
    Task 'improve-missing-branch-auto-creator-slice-3-adapt-auto-branch-patch' has been stuck in state CONFLICT for over 60 minutes. Recorded note: train: still conflicts after 4 redos - needs manual rebase. Conflicting files: packages/darwin-kernel/src/passport/passport.ts.
    
    Diagnose the root cause (build failure, merge conflict, flaky test, or a genuine blocker needing a design decision) and fix it, or if it's a duplicate/obsolete task, close it with a reason. Do not just retry blindly — read the actual error.
