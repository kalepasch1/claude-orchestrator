PROJECT: tomorrow

- id: factory-unblock-rework-rework-corpus-entity-dealflow-link-c7630bd
  title: Unblock rework-rework-corpus-entity-dealflow-link-c7630bd (stuck BLOCKED)
  material: no
  proof: npm test
  prompt: |
    Task 'rework-rework-corpus-entity-dealflow-link-c7630bd' has been stuck in state BLOCKED for over 60 minutes. Recorded note: blocker-quarantine: escalated after 2+ rework attempts (category=legal); needs human review instead of another auto-rework. Last blocker: train: tests failed on rebased agent/rework-rework-corpus-entity-dealflow-link-c7630bd: server/utils/otc/rings/__tests__/capacityFormation.test.ts (12 tests) 8ms
    
     Test Files  44 failed | 245 passed (289)
          Tests  52 failed | 7151 passed (7203)
       Start at  17:05:38
       Duration  84.0
    
    Diagnose the root cause (build failure, merge conflict, flaky test, or a genuine blocker needing a design decision) and fix it, or if it's a duplicate/obsolete task, close it with a reason. Do not just retry blindly — read the actual error.
