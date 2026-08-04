PROJECT: sustainable-barks

- id: factory-unblock-weekly-lint-sustainable-barks
  title: Unblock weekly-lint-sustainable-barks (stuck BLOCKED)
  material: no
  proof: true
  prompt: |
    Task 'weekly-lint-sustainable-barks' has been stuck in state BLOCKED for over 60 minutes. Recorded note: verify pass (conf=0.0); integrate=BLOCKED (local) | advisory (shipped on green build): verify: Security regression: `PETFINDER_API_KEY` and `PETFINDER_SECRET` are added to `.env` (and Vercel env vars) without being properly secured or managed. This allows sensitive informati
    
    Diagnose the root cause (build failure, merge conflict, flaky test, or a genuine blocker needing a design decision) and fix it, or if it's a duplicate/obsolete task, close it with a reason. Do not just retry blindly — read the actual error.
