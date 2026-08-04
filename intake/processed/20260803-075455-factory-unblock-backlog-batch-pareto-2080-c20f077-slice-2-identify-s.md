PROJECT: pareto-2080

- id: factory-unblock-backlog-batch-pareto-2080-c20f077-slice-2-identify-s
  title: Unblock backlog-batch-pareto-2080-c20f077-slice-2-identify-stale-primary-backlog (stuck SHELVED)
  material: no
  proof: npm test
  prompt: |
    Task 'backlog-batch-pareto-2080-c20f077-slice-2-identify-stale-primary-backlog' has been stuck in state SHELVED for over 60 minutes. Recorded note: shelved by queue-velocity PID (low EV, integral too high)
    
    Diagnose the root cause (build failure, merge conflict, flaky test, or a genuine blocker needing a design decision) and fix it, or if it's a duplicate/obsolete task, close it with a reason. Do not just retry blindly — read the actual error.
