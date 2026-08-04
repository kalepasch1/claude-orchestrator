PROJECT: racefeed

- id: factory-unblock-relfix-racefeed-07060650-sub-task-1-update-package-j
  title: Unblock relfix-racefeed-07060650-sub-task-1-update-package-json (stuck CONFLICT)
  material: no
  proof: npm test
  prompt: |
    Task 'relfix-racefeed-07060650-sub-task-1-update-package-json' has been stuck in state CONFLICT for over 60 minutes. Recorded note: train: still conflicts after 4 redos - needs manual rebase
    
    Diagnose the root cause (build failure, merge conflict, flaky test, or a genuine blocker needing a design decision) and fix it, or if it's a duplicate/obsolete task, close it with a reason. Do not just retry blindly — read the actual error.
