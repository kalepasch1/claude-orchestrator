PROJECT: tomorrow

- id: factory-unblock-oracle-proof-carrying-readings
  title: Unblock oracle-proof-carrying-readings (stuck TESTFAIL)
  material: no
  proof: npm test
  prompt: |
    Task 'oracle-proof-carrying-readings' has been stuck in state TESTFAIL for over 60 minutes. Recorded note: train: tests failed on rebased agent/oracle-proof-carrying-readings: > test
    > vitest run
    
    m/loader:599:35)
        at ModuleJob.syncLink (node:internal/modules/esm/module_job:160:33)
        at ModuleJob.link (node:internal/modules/esm/module_job:245:17) {
      code: 'ERR_MODULE_
    
    Diagnose the root cause (build failure, merge conflict, flaky test, or a genuine blocker needing a design decision) and fix it, or if it's a duplicate/obsolete task, close it with a reason. Do not just retry blindly — read the actual error.
