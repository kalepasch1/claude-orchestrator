PROJECT: kalepasch-com

- id: factory-unblock-weekly-lint-kalepasch-com
  title: Unblock weekly-lint-kalepasch-com (stuck BLOCKED)
  material: no
  proof: command not found
  prompt: |
    Task 'weekly-lint-kalepasch-com' has been stuck in state BLOCKED for over 60 minutes. Recorded note: verify pass (conf=0.9); integrate=BLOCKED (local) | advisory (shipped on green build): verify: Missing authentication and allowlist configurations, potential for security vulnerabilities due to secret exposure, removed tests and only minor refactorings without adding new fun; sweep:gate-red (
    > test
    > vitest run
    
    sh: vitest: command not found
    )
    
    Diagnose the root cause (build failure, merge conflict, flaky test, or a genuine blocker needing a design decision) and fix it, or if it's a duplicate/obsolete task, close it with a reason. Do not just retry blindly — read the actual error.
