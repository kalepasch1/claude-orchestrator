PROJECT: smarter

- id: factory-unblock-cont-batch-smarter-af52848
  title: Unblock cont-batch-smarter-af52848 (stuck SHELVED)
  material: no
  proof: npx vue-tsc --noEmit
  prompt: |
    Task 'cont-batch-smarter-af52848' has been stuck in state SHELVED for over 60 minutes. Recorded note: shelved by queue-velocity PID (low EV, integral too high)

    Diagnose the root cause (build failure, merge conflict, flaky test, or a genuine blocker needing a design decision) and fix it, or if it's a duplicate/obsolete task, close it with a reason. Do not just retry blindly — read the actual error.
