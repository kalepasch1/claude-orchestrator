PROJECT: kalepasch-com

- id: factory-unblock-qafix-kalepasch-com-34bc56c33a4f
  title: Unblock qafix-kalepasch-com-34bc56c33a4f (stuck BLOCKED)
  material: no
  proof: npm run build
  prompt: |
    Task 'qafix-kalepasch-com-34bc56c33a4f' has been stuck in state BLOCKED for over 60 minutes. Recorded note: verify pass (conf=0.8); integrate=BLOCKED (local) | advisory (shipped on green build): verify: Secrets were added to the configuration without proper protection, and auth/allowlist was made permissive, which may increase security risks.

    Diagnose the root cause (build failure, merge conflict, flaky test, or a genuine blocker needing a design decision) and fix it, or if it's a duplicate/obsolete task, close it with a reason. Do not just retry blindly — read the actual error.
