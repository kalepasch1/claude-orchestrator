PROJECT: apparently

- id: factory-unblock-recover-stash-a5d92776e792
  title: Unblock recover-stash-a5d92776e792 (stuck BLOCKED)
  material: no
  proof: npm run typecheck
  prompt: |
    Task 'recover-stash-a5d92776e792' has been stuck in state BLOCKED for over 60 minutes. Recorded note: cowork-executor-v6.5: NO-ARTIFACT-JUSTIFIED — BLOCKED on a product decision, not a technical failure. Re-verified against CURRENT origin/master 42de5701 (master moved since the prior run's b1e0b0e7, so this is a fresh check, not a copied verdict). stash a5d92776e792 (stash@{0}) is a 639-line rewrite of app/pages/index.vue that DELETES 2159 of master's 2676 lines. Its own author labelled it "landing-index-rewrite-639line-FAILS-GUARD-SUITES-20260813". WHAT IS MISSING, precisely: tests/regulatory-os-landing.test.ts:32 asserts the homepage contains <LazySupervisionReadinessEconomicsCalculator /> (note: the guard has since been renamed to the Lazy- prefix on current master); the stash version contains 0 occurrences of SupervisionReadinessEconomicsCalculator. To unblock, a human must decide which absorbed-capability surfaces survive a deliberate 2159-line content cut and reinstate that component in the new layout, then reconcile against master's current index.vue. That is landing-page product judgment, not a mechanical merge, so no commit was fabricated and no stub was pushed. This task has now been requeued twice as "transient"; it is not transient and will not clear without an owner decision. Stash left read-only and untouched.
    
    Diagnose the root cause (build failure, merge conflict, flaky test, or a genuine blocker needing a design decision) and fix it, or if it's a duplicate/obsolete task, close it with a reason. Do not just retry blindly — read the actual error.
