PROJECT: apparently

- id: factory-unblock-relfix-apparently-07250017
  title: Unblock relfix-apparently-07250017 (stuck BLOCKED)
  material: no
  proof: npm run typecheck
  prompt: |
    Task 'relfix-apparently-07250017' has been stuck in state BLOCKED for over 60 minutes. Recorded note: verify pass (conf=0.8); integrate=BLOCKED (local) | advisory (shipped on green build): verify: Security regressions: allowlist is made permissive (added tags for 'Fintech & Payments' and 'Lending & Consumer Finance'), secrets are not added. Broken error handling in tests: fe; judge: Failed to stub global 'fetch' function in tests/engines/ab-comparator.test.ts before each test | Failed to stub global 'fetch' function in tests/engines/ab-comparator.test.ts befor

    Diagnose the root cause (build failure, merge conflict, flaky test, or a genuine blocker needing a design decision) and fix it, or if it's a duplicate/obsolete task, close it with a reason. Do not just retry blindly — read the actual error.
