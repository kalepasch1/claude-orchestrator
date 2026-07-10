PROJECT: apparently

- id: factory-unblock-rework-secret-rework-secret-license-passport-ad7131a
  title: Unblock rework-secret-rework-secret-license-passport-ad7131a-fb5b135 (stuck BLOCKED)
  material: no
  proof: npm run typecheck
  prompt: |
    Task 'rework-secret-rework-secret-license-passport-ad7131a-fb5b135' has been stuck in state BLOCKED for over 60 minutes. Recorded note: blocker-quarantine: escalated after 2+ rework attempts (category=legal); needs human review instead of another auto-rework. Last blocker: train: tests failed on rebased agent/rework-secret-rework-secret-license-passport-ad7131a-fb5b135: > typecheck
    > NODE_OPTIONS=--max-old-space-size=8192 nuxt typecheck
    
    599:35)
        at onImport.tracePromise.__proto__ (node:internal/modules/esm/loader:628:32)
        at TracingChannel.tracePromise (node:d
    
    Diagnose the root cause (build failure, merge conflict, flaky test, or a genuine blocker needing a design decision) and fix it, or if it's a duplicate/obsolete task, close it with a reason. Do not just retry blindly — read the actual error.
