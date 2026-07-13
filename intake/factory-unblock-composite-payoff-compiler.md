PROJECT: tomorrow

- id: factory-unblock-composite-payoff-compiler
  title: Unblock composite-payoff-compiler (stuck TESTFAIL)
  material: no
  proof: npm test
  prompt: |
    Task 'composite-payoff-compiler' has been stuck in state TESTFAIL for over 60 minutes. Recorded note: train: tests failed on rebased agent/composite-payoff-compiler: 
    
    Diagnose the root cause (build failure, merge conflict, flaky test, or a genuine blocker needing a design decision) and fix it, or if it's a duplicate/obsolete task, close it with a reason. Do not just retry blindly — read the actual error.
