PROJECT: beethoven

- id: factory-unblock-cx-outcome-horizons
  title: Unblock cx-outcome-horizons (stuck TESTFAIL)
  material: no
  proof: npm --prefix web run test
  prompt: |
    Task 'cx-outcome-horizons' has been stuck in state TESTFAIL for over 60 minutes. Recorded note: train: tests failed on rebased agent/cx-outcome-horizons: PayoffCompiler.test.ts [2m([22m[2m0 test[22m[2m)[22m
    
    [2m Test Files [22m [1m[31m1 failed[39m[22m[90m (1)[39m
    [2m      Tests [22m [2mno tests[22m
    [2m   Start at [22m 03:31:53
    [2m 
    
    Diagnose the root cause (build failure, merge conflict, flaky test, or a genuine blocker needing a design decision) and fix it, or if it's a duplicate/obsolete task, close it with a reason. Do not just retry blindly — read the actual error.
