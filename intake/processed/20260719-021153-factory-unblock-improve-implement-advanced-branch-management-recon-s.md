PROJECT: beethoven

- id: factory-unblock-improve-implement-advanced-branch-management-recon-s
  title: Unblock improve-implement-advanced-branch-management-recon-slice-5 (stuck CONFLICT)
  material: no
  proof: npm --prefix web run test
  prompt: |
    Task 'improve-implement-advanced-branch-management-recon-slice-5' has been stuck in state CONFLICT for over 60 minutes. Recorded note: train: still conflicts after 4 redos - needs manual rebase
    
    Diagnose the root cause (build failure, merge conflict, flaky test, or a genuine blocker needing a design decision) and fix it, or if it's a duplicate/obsolete task, close it with a reason. Do not just retry blindly — read the actual error.
