PROJECT: pareto-2080

- id: factory-unblock-qafix-pareto-2080-3c05a8d323cd
  title: Unblock qafix-pareto-2080-3c05a8d323cd (stuck CONFLICT)
  material: no
  proof: npm test
  prompt: |
    Task 'qafix-pareto-2080-3c05a8d323cd' has been stuck in state CONFLICT for over 60 minutes. Recorded note: train: still conflicts after 4 redos - needs manual rebase.
    
    Diagnose the root cause (build failure, merge conflict, flaky test, or a genuine blocker needing a design decision) and fix it, or if it's a duplicate/obsolete task, close it with a reason. Do not just retry blindly — read the actual error.
