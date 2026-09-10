# ChatGPT/Codex local build-evidence reconciliation — beethoven

Audit fingerprint: `cae39c712fe5cb155e3380b0463c6f7ba3c0b9a76558aa63a3d7a6429beb7541`

Base: `origin/master` @ `bcacf428ecb1` · generated 2026-09-10T04:47:14.762Z

Regenerate with:

```bash
node scripts/reconcile-evidence.mjs \
  --fingerprint cae39c712fe5cb155e3380b0463c6f7ba3c0b9a76558aa63a3d7a6429beb7541 \
  --default-branch master \
  --json docs/recovery/chatgpt-local-reconcile-beethoven-cae39c712fe5.json
node scripts/recovery-ledger-report.mjs --ledger docs/recovery/chatgpt-local-reconcile-beethoven-cae39c712fe5.json --project beethoven
```

## Result

**4341 evidence items classified, 0 UNKNOWN.** The evidence source was treated as read-only throughout — nothing was deleted, reset, cleaned, popped or moved. Classification is recomputed from live refs, not from the snapshot in the task prompt.

| Classification | Count | Disposition |
|---|---:|---|
| RECOVERABLE_VALUE | 1034 | queue a focused recovery task; apply in a fresh isolated worktree |
| SUPERSEDED_BY_NEWER | 1 | no action — newer implementation on the default branch wins |
| ALREADY_PRESENT | 3306 | no action — value already on the default branch |

## Items with remaining value

1034 item(s) below keep durable provenance in `docs/recovery/chatgpt-local-reconcile-beethoven-cae39c712fe5.json` (source ref, sha, subject, touched files, carrier branches). None were applied in this pass — per the coordination rule, conflicts get a focused follow-up rather than a forced overwrite.

| Source ref | Class | Files | Subject |
|---|---|---:|---|
| `refs/heads/agent/approval-digest-batching` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 5 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/approval-digest-batching-add-max-turns-error-handling-logging-fie` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 3 file(s) not on origin/main. NO remote branch prese |
| `refs/heads/agent/approval-digest-batching-add-max-turns-regression-tests` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 3 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/approval-digest-batching-add-repair-automated-test-coverage-for-m` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 4 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/approval-digest-batching-end-to-end-guard-ensure-max-turns-failur` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 3 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/approval-digest-batching-handle-max-turns-terminal-reason-in-clau` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `refs/heads/agent/approval-digest-batching-implement-robust-max-turns-detection-in-` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 3 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/approval-digest-batching-isolate-conflict-free-rewrite-of-runner-` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 3 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/approval-digest-batching-test-coverage-max-turns-detection-in-tes` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 4 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/approval-digest-batching-wire-ci-lint-checks-to-catch-conflict-ma` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 6 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/backlog-batch-beethoven-01b6ed7` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 4 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/backlog-batch-beethoven-22ee5bc-convention-conform-slice-4` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 3 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/backlog-batch-beethoven-22ee5bc-prompt-evolution-bandit-implement-performance-tr` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/backlog-batch-beethoven-22ee5bc-recover-pinned-exp-slice-1` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/backlog-batch-beethoven-22ee5bc-recover-pinned-exp-slice-2` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 1 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/backlog-batch-beethoven-22ee5bc-remaining-stale-backlog-items` | RECOVERABLE_VALUE | 0 | 75 unique commit(s) touching 121 file(s) not on origin/main. NO remote branch pr |
| `refs/heads/agent/backlog-batch-beethoven-2863be9-merge-changes-slice-1` | RECOVERABLE_VALUE | 0 | 3 unique commit(s) touching 4 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/backlog-batch-beethoven-2863be9-merge-changes-slice-2` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 1 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/backlog-batch-beethoven-2863be9-update-tests-slice-3` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 3 file(s) not on origin/main. NO remote branch prese |
| `refs/heads/agent/backlog-batch-beethoven-2863be9-update-tests-slice-4` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/backlog-batch-beethoven-35584ad` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/backlog-batch-beethoven-45ec7f9` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/backlog-batch-beethoven-52d9da1` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 5 file(s) not on origin/main. NO remote branch prese |
| `refs/heads/agent/backlog-batch-beethoven-63cf995-recover-pinned-express-lane` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 1 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/backlog-batch-beethoven-7371e3f-setup-config-consumer-module-implement-comprehen` | RECOVERABLE_VALUE | 0 | 5 unique commit(s) touching 25 file(s) not on origin/main. NO remote branch pres |
| `refs/heads/agent/backlog-batch-beethoven-a661cf9` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/backlog-batch-beethoven-a86bb21-recover-convention-slice-4` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 5 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/backlog-batch-beethoven-a86bb21-recover-economic-scheduler-revenue-verify-and-re` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 1 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/backlog-batch-beethoven-a86bb21-recover-pinned-exp-slice-1` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 4 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/backlog-batch-beethoven-a86bb21-recover-remaining--slice-3` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 1 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/backlog-batch-beethoven-c9a51c6-pinned-express-lane-repair` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 1 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/backlog-batch-beethoven-ccacb00-commit-implementat-slice-1` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/backlog-batch-beethoven-ccacb00-fix-tests-fix-pid-integral-windup` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 1 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/backlog-batch-beethoven-d00ef24-economic-scheduler-revenue-create-revenue-module` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 1 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/backlog-batch-beethoven-d00ef24-economic-scheduler-revenue-verify-full-test-suit` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/backlog-batch-beethoven-d3151d8` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/backlog-batch-beethoven-d3a0846` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 1 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/backlog-batch-beethoven-d4ba22d-resolve-convention-conformance-lints` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 5 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/backlog-batch-beethoven-e34b0f0-slice-4` | RECOVERABLE_VALUE | 0 | 6 unique commit(s) touching 26 file(s) not on origin/main. NO remote branch pres |
| `refs/heads/agent/backlog-batch-beethoven-e63dfee-apply-economic-scheduler-revenue-patch-apply-pat` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/backlog-batch-beethoven-e8afcee-inventory-clean-environment` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 3 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/backlog-batch-tomorrow-9d5e4db-slice-1` | RECOVERABLE_VALUE | 0 | merged into the LOCAL default branch but not into origin/main. The only copy is  |
| `refs/heads/agent/beethoven-followup-dirty-worktree-red-config-suites` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 23 file(s) not on origin/main. A remote branch prese |
| `refs/heads/agent/beethoven-reconcile-followup-deferred-tests-newer-module-versions` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 10 file(s) not on origin/main. A remote branch prese |
| `refs/heads/agent/bugfix-hisanta-conflict-markers-committed-to-master` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 5 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/cade-mirror-negotiation` | RECOVERABLE_VALUE | 0 | 32 unique commit(s) touching 20 file(s) not on origin/main. A remote branch pres |
| `refs/heads/agent/canary-claude-27-slice-1-run-checks` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 4 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/canary-claude-27-slice-3-adapt-prior-merged-patterns-apply-adapted-patch-resolve` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 5 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/canary-claude-27-slice-3-adapt-prior-merged-patterns-apply-adapted-patch-run-ful` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/canary-claude-27-slice-3-update-tests-checks-analyze-patch-behavior-analyze-patc` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 6 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/canary-claude-27-slice-3-update-tests-checks-implement-test-assertions` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 1 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/canary-claude-27-slice-3-update-tests-checks-implement-test-assertions-implement` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 3 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/canary-claude-27-slice-3-update-tests-checks-implement-test-assertions-read-test` | RECOVERABLE_VALUE | 0 | 3 unique commit(s) touching 3 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/canary-claude-27-slice-3-update-tests-checks-verify-test-passes` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 4 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/canary-claude-27-slice-3-update-tests-checks-write-failing-test-analyze-patch-an` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/canary-claude-27-slice-3-verify-patch` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/canary-claude-4-slice-2` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/canary-codex-14` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 1 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/canary-codex-15` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 1 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/canary-codex-16` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 1 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/canary-codex-27` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 3 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/canary-codex-28-verify-behavior-preservation-and-build` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/canary-codex-39` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 5 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/canary-deepseek-1` | RECOVERABLE_VALUE | 0 | 7 unique commit(s) touching 17 file(s) not on origin/main. NO remote branch pres |
| `refs/heads/agent/canary-deepseek-6-run-full-canary-validation-run-integration-tests-debug-and-mod` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/canary-deepseek-6-run-full-canary-validation-run-integration-tests-identify-rele` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 4 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/canary-deepseek-6-run-full-canary-validation-run-integration-tests-pass` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 1 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/canary-deepseek-6-run-full-canary-validation-run-integration-tests-run-relevant-` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/canary-deepseek-6-run-full-canary-validation-run-smoke-tests-pass-fix-env-relate` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/canary-deepseek-6-run-full-canary-validation-run-smoke-tests-pass-fix-logic-rela` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 1 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/canary-deepseek-6-run-full-canary-validation-run-smoke-tests-pass-fix-remaining-` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 1 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/canary-deepseek-6-run-full-canary-validation-run-smoke-tests-pass-triage-and-fix` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 12 file(s) not on origin/main. A remote branch prese |
| `refs/heads/agent/canary-gemini-2-slice-2` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 1 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/canary-gemini-2-slice-5` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/canary-gemini-25-canary-gemini-25-metrics-background-thread-integrate-with-canar` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 1 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/canary-gemini-25-canary-gemini-25-metrics-update-gauge-on-failure-define-failure` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/canary-gemini-25-canary-gemini-25-request-retry-logic` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `refs/heads/agent/canary-gemini-25-canary-gemini-25-validate-add-validation-function-add-logging` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 1 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/canary-gemini-25-canary-gemini-25-validate-add-validation-function-implement-can` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/canary-gemini-25-canary-gemini-25-validate-add-validation-function-return-bool-t` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/canary-gemini-25-canary-gemini-25-validate-integrate-validation-and-exit-code-mo` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/canary-gemini-25-canary-gemini-25-validate-integrate-validation-and-exit-code-ve` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/canary-gemini-25-integrate-with-mainline` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/canary-gemini-25-reconstruct-branch` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/canary-gemini-25-run-tests` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 1 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/canary-gemini-4-slice-2` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 5 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/canary-gpt-mini-1` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 1 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/canary-gpt-mini-3` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `refs/heads/agent/canary-ollama-2-2-slice-5` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 1 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/canary-ollama-2-3-slice-3` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/canary-ollama-2-3-slice-5` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/canary-ollama-4-3` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/canary-ollama-4-32-verify-diff-and-run-tests` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 5 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/canary-ollama-4-5` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 1 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/canary-ollama-6` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/canary-xai-3` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 1 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/canary-xai-6-adapt-proven-diffs` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 1 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/canary-xai-6-add-test-check` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/canary-xai-6-build-and-test` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 1 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/causal-outcome-feedback-slice-3` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/chatgpt-local-reconcile-beethoven-00f6799184ee` | RECOVERABLE_VALUE | 0 | merged into the LOCAL default branch but not into origin/main. The only copy is  |
| `refs/heads/agent/chatgpt-local-reconcile-beethoven-16041039dfad` | RECOVERABLE_VALUE | 0 | 84 unique commit(s) touching 166 file(s) not on origin/main. A remote branch pre |
| `refs/heads/agent/chatgpt-local-reconcile-beethoven-179a43b4d07a` | RECOVERABLE_VALUE | 0 | 71 unique commit(s) touching 113 file(s) not on origin/main. A remote branch pre |
| `refs/heads/agent/chatgpt-local-reconcile-beethoven-1812c7f19d00` | RECOVERABLE_VALUE | 0 | merged into the LOCAL default branch but not into origin/main. The only copy is  |
| `refs/heads/agent/chatgpt-local-reconcile-beethoven-26babe9ae13d` | RECOVERABLE_VALUE | 0 | merged into the LOCAL default branch but not into origin/main. The only copy is  |
| `refs/heads/agent/chatgpt-local-reconcile-beethoven-2735649e88bb` | RECOVERABLE_VALUE | 0 | merged into the LOCAL default branch but not into origin/main. The only copy is  |
| `refs/heads/agent/chatgpt-local-reconcile-beethoven-28e3fe388feb` | RECOVERABLE_VALUE | 0 | merged into the LOCAL default branch but not into origin/main. The only copy is  |
| `refs/heads/agent/chatgpt-local-reconcile-beethoven-3112d322d106` | RECOVERABLE_VALUE | 0 | merged into the LOCAL default branch but not into origin/main. The only copy is  |
| `refs/heads/agent/chatgpt-local-reconcile-beethoven-3145365897a5` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 14 file(s) not on origin/main. A remote branch prese |
| `refs/heads/agent/chatgpt-local-reconcile-beethoven-317e2750d050` | RECOVERABLE_VALUE | 0 | merged into the LOCAL default branch but not into origin/main. The only copy is  |
| `refs/heads/agent/chatgpt-local-reconcile-beethoven-3b50d1e569de` | RECOVERABLE_VALUE | 0 | 88 unique commit(s) touching 180 file(s) not on origin/main. A remote branch pre |
| `refs/heads/agent/chatgpt-local-reconcile-beethoven-454c4d4bc76a` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 14 file(s) not on origin/main. A remote branch prese |
| `refs/heads/agent/chatgpt-local-reconcile-beethoven-48ada8033590` | RECOVERABLE_VALUE | 0 | 86 unique commit(s) touching 174 file(s) not on origin/main. A remote branch pre |
| `refs/heads/agent/chatgpt-local-reconcile-beethoven-48ae8f413643` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 74 file(s) not on origin/main. A remote branch prese |
| `refs/heads/agent/chatgpt-local-reconcile-beethoven-4a838e298f31` | RECOVERABLE_VALUE | 0 | 163 unique commit(s) touching 168 file(s) not on origin/main. A remote branch pr |
| `refs/heads/agent/chatgpt-local-reconcile-beethoven-4b59782756c3` | RECOVERABLE_VALUE | 0 | merged into the LOCAL default branch but not into origin/main. The only copy is  |
| `refs/heads/agent/chatgpt-local-reconcile-beethoven-4b8720f40cee` | RECOVERABLE_VALUE | 0 | merged into the LOCAL default branch but not into origin/main. The only copy is  |
| `refs/heads/agent/chatgpt-local-reconcile-beethoven-4ca585bf4ce0` | RECOVERABLE_VALUE | 0 | merged into the LOCAL default branch but not into origin/main. The only copy is  |
| `refs/heads/agent/chatgpt-local-reconcile-beethoven-506773f44b20` | RECOVERABLE_VALUE | 0 | merged into the LOCAL default branch but not into origin/main. The only copy is  |
| `refs/heads/agent/chatgpt-local-reconcile-beethoven-50a4fcd03802` | RECOVERABLE_VALUE | 0 | merged into the LOCAL default branch but not into origin/main. The only copy is  |
| `refs/heads/agent/chatgpt-local-reconcile-beethoven-527db1a7c960` | RECOVERABLE_VALUE | 0 | merged into the LOCAL default branch but not into origin/main. The only copy is  |
| `refs/heads/agent/chatgpt-local-reconcile-beethoven-53fd7e424376` | RECOVERABLE_VALUE | 0 | 91 unique commit(s) touching 186 file(s) not on origin/main. A remote branch pre |
| `refs/heads/agent/chatgpt-local-reconcile-beethoven-55acd60c79b1` | RECOVERABLE_VALUE | 0 | 82 unique commit(s) touching 162 file(s) not on origin/main. A remote branch pre |
| `refs/heads/agent/chatgpt-local-reconcile-beethoven-567c874a3ee0` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 14 file(s) not on origin/main. A remote branch prese |
| `refs/heads/agent/chatgpt-local-reconcile-beethoven-589a1eff7a3b` | RECOVERABLE_VALUE | 0 | merged into the LOCAL default branch but not into origin/main. The only copy is  |
| `refs/heads/agent/chatgpt-local-reconcile-beethoven-59dc7d2afd37` | RECOVERABLE_VALUE | 0 | merged into the LOCAL default branch but not into origin/main. The only copy is  |
| `refs/heads/agent/chatgpt-local-reconcile-beethoven-5f5d8d3a0e09` | RECOVERABLE_VALUE | 0 | merged into the LOCAL default branch but not into origin/main. The only copy is  |
| `refs/heads/agent/chatgpt-local-reconcile-beethoven-6532f417a112` | RECOVERABLE_VALUE | 0 | merged into the LOCAL default branch but not into origin/main. The only copy is  |
| `refs/heads/agent/chatgpt-local-reconcile-beethoven-671c267eedf3` | RECOVERABLE_VALUE | 0 | 70 unique commit(s) touching 95 file(s) not on origin/main. A remote branch pres |
| `refs/heads/agent/chatgpt-local-reconcile-beethoven-69c61d071bc1` | RECOVERABLE_VALUE | 0 | merged into the LOCAL default branch but not into origin/main. The only copy is  |
| `refs/heads/agent/chatgpt-local-reconcile-beethoven-69fc394993ec` | RECOVERABLE_VALUE | 0 | merged into the LOCAL default branch but not into origin/main. The only copy is  |
| `refs/heads/agent/chatgpt-local-reconcile-beethoven-6c8911116873` | RECOVERABLE_VALUE | 0 | 74 unique commit(s) touching 119 file(s) not on origin/main. A remote branch pre |
| `refs/heads/agent/chatgpt-local-reconcile-beethoven-6e22376c6c4c` | RECOVERABLE_VALUE | 0 | merged into the LOCAL default branch but not into origin/main. The only copy is  |
| `refs/heads/agent/chatgpt-local-reconcile-beethoven-722437a74e52` | RECOVERABLE_VALUE | 0 | merged into the LOCAL default branch but not into origin/main. The only copy is  |
| `refs/heads/agent/chatgpt-local-reconcile-beethoven-73b0c02a3342` | RECOVERABLE_VALUE | 0 | 87 unique commit(s) touching 178 file(s) not on origin/main. A remote branch pre |
| `refs/heads/agent/chatgpt-local-reconcile-beethoven-764fd6ce53c9` | RECOVERABLE_VALUE | 0 | merged into the LOCAL default branch but not into origin/main. The only copy is  |
| `refs/heads/agent/chatgpt-local-reconcile-beethoven-7b6f925e1e7a` | RECOVERABLE_VALUE | 0 | 66 unique commit(s) touching 84 file(s) not on origin/main. NO remote branch pre |
| `refs/heads/agent/chatgpt-local-reconcile-beethoven-7bd5c9d0be16` | RECOVERABLE_VALUE | 0 | 69 unique commit(s) touching 93 file(s) not on origin/main. A remote branch pres |
| `refs/heads/agent/chatgpt-local-reconcile-beethoven-84be6eb0f916` | RECOVERABLE_VALUE | 0 | merged into the LOCAL default branch but not into origin/main. The only copy is  |
| `refs/heads/agent/chatgpt-local-reconcile-beethoven-85d2de799d5d` | RECOVERABLE_VALUE | 0 | 76 unique commit(s) touching 123 file(s) not on origin/main. A remote branch pre |
| `refs/heads/agent/chatgpt-local-reconcile-beethoven-860481810ab8` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 14 file(s) not on origin/main. A remote branch prese |
| `refs/heads/agent/chatgpt-local-reconcile-beethoven-8d0702cbd5aa` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 70 file(s) not on origin/main. A remote branch prese |
| `refs/heads/agent/chatgpt-local-reconcile-beethoven-8e79d6bdcb55` | RECOVERABLE_VALUE | 0 | merged into the LOCAL default branch but not into origin/main. The only copy is  |
| `refs/heads/agent/chatgpt-local-reconcile-beethoven-8ee1c86dad49` | RECOVERABLE_VALUE | 0 | merged into the LOCAL default branch but not into origin/main. The only copy is  |
| `refs/heads/agent/chatgpt-local-reconcile-beethoven-9284e2824803` | RECOVERABLE_VALUE | 0 | merged into the LOCAL default branch but not into origin/main. The only copy is  |
| `refs/heads/agent/chatgpt-local-reconcile-beethoven-933a191b9acb` | RECOVERABLE_VALUE | 0 | merged into the LOCAL default branch but not into origin/main. The only copy is  |
| `refs/heads/agent/chatgpt-local-reconcile-beethoven-962a4e83d49f` | RECOVERABLE_VALUE | 0 | merged into the LOCAL default branch but not into origin/main. The only copy is  |
| `refs/heads/agent/chatgpt-local-reconcile-beethoven-9655bcad9737` | RECOVERABLE_VALUE | 0 | merged into the LOCAL default branch but not into origin/main. The only copy is  |
| `refs/heads/agent/chatgpt-local-reconcile-beethoven-99af307a89b5` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 14 file(s) not on origin/main. A remote branch prese |
| `refs/heads/agent/chatgpt-local-reconcile-beethoven-9b427697d13f` | RECOVERABLE_VALUE | 0 | 85 unique commit(s) touching 168 file(s) not on origin/main. A remote branch pre |
| `refs/heads/agent/chatgpt-local-reconcile-beethoven-9efdd400b3fd` | RECOVERABLE_VALUE | 0 | merged into the LOCAL default branch but not into origin/main. The only copy is  |
| `refs/heads/agent/chatgpt-local-reconcile-beethoven-a0fe527bf1e7` | RECOVERABLE_VALUE | 0 | merged into the LOCAL default branch but not into origin/main. The only copy is  |
| `refs/heads/agent/chatgpt-local-reconcile-beethoven-ae8e6611998d` | RECOVERABLE_VALUE | 0 | merged into the LOCAL default branch but not into origin/main. The only copy is  |
| `refs/heads/agent/chatgpt-local-reconcile-beethoven-b4da5a48b1ee` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 27 file(s) not on origin/main. A remote branch prese |
| `refs/heads/agent/chatgpt-local-reconcile-beethoven-b9135ebdf0cc` | RECOVERABLE_VALUE | 0 | merged into the LOCAL default branch but not into origin/main. The only copy is  |
| `refs/heads/agent/chatgpt-local-reconcile-beethoven-ca93a1b7be55` | RECOVERABLE_VALUE | 0 | 67 unique commit(s) touching 86 file(s) not on origin/main. A remote branch pres |
| `refs/heads/agent/chatgpt-local-reconcile-beethoven-cc5d4cda12c0` | RECOVERABLE_VALUE | 0 | merged into the LOCAL default branch but not into origin/main. The only copy is  |
| `refs/heads/agent/chatgpt-local-reconcile-beethoven-d1db04b249fd` | RECOVERABLE_VALUE | 0 | merged into the LOCAL default branch but not into origin/main. The only copy is  |
| `refs/heads/agent/chatgpt-local-reconcile-beethoven-d6bdec16843f` | RECOVERABLE_VALUE | 0 | merged into the LOCAL default branch but not into origin/main. The only copy is  |
| `refs/heads/agent/chatgpt-local-reconcile-beethoven-d7e56d6c1a9e` | RECOVERABLE_VALUE | 0 | merged into the LOCAL default branch but not into origin/main. The only copy is  |
| `refs/heads/agent/chatgpt-local-reconcile-beethoven-d8dd9f20ff54` | RECOVERABLE_VALUE | 0 | merged into the LOCAL default branch but not into origin/main. The only copy is  |
| `refs/heads/agent/chatgpt-local-reconcile-beethoven-dd50d0c9f1f2` | RECOVERABLE_VALUE | 0 | merged into the LOCAL default branch but not into origin/main. The only copy is  |
| `refs/heads/agent/chatgpt-local-reconcile-beethoven-e38ba5c93978` | RECOVERABLE_VALUE | 0 | merged into the LOCAL default branch but not into origin/main. The only copy is  |
| `refs/heads/agent/chatgpt-local-reconcile-beethoven-e7d1ee05eb18` | RECOVERABLE_VALUE | 0 | merged into the LOCAL default branch but not into origin/main. The only copy is  |
| `refs/heads/agent/chatgpt-local-reconcile-beethoven-e8a51076360d` | RECOVERABLE_VALUE | 0 | merged into the LOCAL default branch but not into origin/main. The only copy is  |
| `refs/heads/agent/chatgpt-local-reconcile-beethoven-ec057abac3d8` | RECOVERABLE_VALUE | 0 | merged into the LOCAL default branch but not into origin/main. The only copy is  |
| `refs/heads/agent/chatgpt-local-reconcile-beethoven-ed25b660ee43` | RECOVERABLE_VALUE | 0 | merged into the LOCAL default branch but not into origin/main. The only copy is  |
| `refs/heads/agent/chatgpt-local-reconcile-beethoven-ee86a2cff698` | RECOVERABLE_VALUE | 0 | 81 unique commit(s) touching 160 file(s) not on origin/main. A remote branch pre |
| `refs/heads/agent/chatgpt-local-reconcile-beethoven-f8c1bb486dd1` | RECOVERABLE_VALUE | 0 | merged into the LOCAL default branch but not into origin/main. The only copy is  |
| `refs/heads/agent/chatgpt-local-reconcile-beethoven-fa219072749e` | RECOVERABLE_VALUE | 0 | 65 unique commit(s) touching 82 file(s) not on origin/main. A remote branch pres |
| `refs/heads/agent/chatgpt-local-reconcile-illuminati-1a6486543894` | RECOVERABLE_VALUE | 0 | merged into the LOCAL default branch but not into origin/main. The only copy is  |
| `refs/heads/agent/chatgpt-local-reconcile-illuminati-b8016ffd3ef1` | RECOVERABLE_VALUE | 0 | merged into the LOCAL default branch but not into origin/main. The only copy is  |
| `refs/heads/agent/chatgpt-local-reconcile-illuminati-d676f8150158` | RECOVERABLE_VALUE | 0 | merged into the LOCAL default branch but not into origin/main. The only copy is  |
| `refs/heads/agent/codex-recover-operator-output-truth-patch-7db8cf82` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 18 file(s) not on origin/main. A remote branch prese |
| `refs/heads/agent/complete-scan-window-truth-remediation` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 7 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/cont-5f9e0e` | RECOVERABLE_VALUE | 0 | 43 unique commit(s) touching 1372 file(s) not on origin/main. A remote branch pr |
| `refs/heads/agent/contracts-smarter` | RECOVERABLE_VALUE | 0 | 51 unique commit(s) touching 1373 file(s) not on origin/main. A remote branch pr |
| `refs/heads/agent/copyfix-beethoven-07151953-slice-2` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/copyfix-beethoven-07151953-slice-5` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 6 file(s) not on origin/main. NO remote branch prese |
| `refs/heads/agent/copyfix-beethoven-07180848-slice-3-public-landing-domain-intent-labels-copy` | RECOVERABLE_VALUE | 0 | 27 unique commit(s) touching 51 file(s) not on origin/main. A remote branch pres |
| `refs/heads/agent/copyfix-beethoven-07180848-slice-3-public-landing-founder-navigation-copy` | RECOVERABLE_VALUE | 0 | 19 unique commit(s) touching 40 file(s) not on origin/main. NO remote branch pre |
| `refs/heads/agent/copyfix-beethoven-07180848-slice-3-public-landing-founder-navigation-copy-clean-140991` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 5 file(s) not on origin/main. NO remote branch prese |
| `refs/heads/agent/copyfix-beethoven-07180848-slice-3-public-landing-hero-control-copy` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 1 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/copyfix-trojun-08171305-guard-false-positives` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/counterfactual-replay` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 1 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/counterfactual-replay-recover` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 3 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/deployfix-darwn-vercel-1783343439` | RECOVERABLE_VALUE | 0 | 47 unique commit(s) touching 1372 file(s) not on origin/main. A remote branch pr |
| `refs/heads/agent/deploysilence-kalepasch-com` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `refs/heads/agent/differential-qa-order-independent` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 3 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/dropbox-beethoven-audit-addendum-two-session-recon-slice-1-integrate-adapted-dif` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 1 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/dropbox-beethoven-audit-addendum-two-session-recon-slice-5-test-and-commit` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 4 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/dropbox-beethoven-audit-addendum-two-session-reconciliation-read-wit-group-5` | RECOVERABLE_VALUE | 0 | 11 unique commit(s) touching 20 file(s) not on origin/main. A remote branch pres |
| `refs/heads/agent/dropbox-beethoven-core-integrity-audit-merge-safet-slice-1` | RECOVERABLE_VALUE | 0 | merged into the LOCAL default branch but not into origin/main. The only copy is  |
| `refs/heads/agent/dropbox-beethoven-core-integrity-audit-merge-safet-slice-2` | RECOVERABLE_VALUE | 0 | 163 unique commit(s) touching 164 file(s) not on origin/main. A remote branch pr |
| `refs/heads/agent/dropbox-beethoven-core-integrity-audit-merge-safet-slice-3` | RECOVERABLE_VALUE | 0 | merged into the LOCAL default branch but not into origin/main. The only copy is  |
| `refs/heads/agent/dropbox-beethoven-core-integrity-audit-merge-safet-slice-4` | RECOVERABLE_VALUE | 0 | merged into the LOCAL default branch but not into origin/main. The only copy is  |
| `refs/heads/agent/dropbox-beethoven-core-integrity-audit-merge-safety-self-protection--group-2-imp` | RECOVERABLE_VALUE | 0 | merged into the LOCAL default branch but not into origin/main. The only copy is  |
| `refs/heads/agent/dropbox-beethoven-fleet-immune-system-throughput-accelerators-operat-1-never-again-lane-daemon-immune-system-p0-recovered` | RECOVERABLE_VALUE | 0 | 89 unique commit(s) touching 182 file(s) not on origin/main. A remote branch pre |
| `refs/heads/agent/dropbox-beethoven-fleet-immune-system-throughput-accelerators-operat-contracts-s` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 1 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/dropbox-beethoven-fleet-immune-system-throughput-accelerators-operat-proofs` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 4 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/dropbox-beethoven-madeus-web-multi-tenant-claude-p-slice-1-configure-operator-s-` | RECOVERABLE_VALUE | 0 | 41 unique commit(s) touching 82 file(s) not on origin/main. NO remote branch pre |
| `refs/heads/agent/dropbox-beethoven-madeus-web-multi-tenant-claude-p-slice-3-commit-the-final-impl` | RECOVERABLE_VALUE | 0 | 42 unique commit(s) touching 83 file(s) not on origin/main. NO remote branch pre |
| `refs/heads/agent/dropbox-economic-scheduler-revenue-revenue-focused-task-prioritizati-group-3` | RECOVERABLE_VALUE | 0 | merged into the LOCAL default branch but not into origin/main. The only copy is  |
| `refs/heads/agent/dropbox-hisanta-mastery-engine-grandma-rail-family-slice-2` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 5 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/dropbox-hisanta-mastery-engine-grandma-rail-family-slice-2-clean-129448` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 11 file(s) not on origin/main. NO remote branch pres |
| `refs/heads/agent/dropbox-hisanta-mastery-engine-grandma-rail-family-slice-3` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 5 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/dropbox-merge-train-throughput-recovery-drive-581-skipped-to-merged--group-1` | RECOVERABLE_VALUE | 0 | merged into the LOCAL default branch but not into origin/main. The only copy is  |
| `refs/heads/agent/dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-governor-ra` | RECOVERABLE_VALUE | 0 | 45 unique commit(s) touching 87 file(s) not on origin/main. NO remote branch pre |
| `refs/heads/agent/dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-governor-ram-floor` | RECOVERABLE_VALUE | 0 | 26 unique commit(s) touching 50 file(s) not on origin/main. A remote branch pres |
| `refs/heads/agent/dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-keepalive-s` | RECOVERABLE_VALUE | 0 | merged into the LOCAL default branch but not into origin/main. The only copy is  |
| `refs/heads/agent/dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-keepalive-single-supervisor` | RECOVERABLE_VALUE | 0 | 24 unique commit(s) touching 46 file(s) not on origin/main. A remote branch pres |
| `refs/heads/agent/dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-p4-deploy-k` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 9 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-p4-deploy-kpi` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 1 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/dropbox-mission-complete-p5-interlock-tests` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/dropbox-operator-gate-amendment-auto-ship-authoriz-slice-2` | RECOVERABLE_VALUE | 0 | 6 unique commit(s) touching 28 file(s) not on origin/main. A remote branch prese |
| `refs/heads/agent/dropbox-pareto-life-goal-autonomy-stack-p2-delegation-firewall` | RECOVERABLE_VALUE | 0 | merged into the LOCAL default branch but not into origin/main. The only copy is  |
| `refs/heads/agent/dropbox-pareto-life-goal-autonomy-stack-p3-micro-sweeps` | RECOVERABLE_VALUE | 0 | merged into the LOCAL default branch but not into origin/main. The only copy is  |
| `refs/heads/agent/dropbox-pareto-life-goal-autonomy-stack-p4-household-legal-doc-updater-notificat` | RECOVERABLE_VALUE | 0 | 90 unique commit(s) touching 184 file(s) not on origin/main. A remote branch pre |
| `refs/heads/agent/dropbox-pareto-p2-delegation-firewall-1-package-and-intake` | RECOVERABLE_VALUE | 0 | merged into the LOCAL default branch but not into origin/main. The only copy is  |
| `refs/heads/agent/dropbox-portfolio-doctrine-shared-services-x-items-slice-1` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 5 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/dropbox-prediction-markets-institute-think-tank-launch-brand-exam-ap-contracts` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 1 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/dropbox-prompt-merged-diff-memory-system-task-spec-group-12-implement-memory-sys` | RECOVERABLE_VALUE | 0 | merged into the LOCAL default branch but not into origin/main. The only copy is  |
| `refs/heads/agent/dropbox-prompt-merged-diff-memory-system-task-spec-group-18` | RECOVERABLE_VALUE | 0 | 64 unique commit(s) touching 78 file(s) not on origin/main. NO remote branch pre |
| `refs/heads/agent/dropbox-prompt-merged-diff-memory-system-task-spec-group-19-wire-merge-detection` | RECOVERABLE_VALUE | 0 | 83 unique commit(s) touching 164 file(s) not on origin/main. A remote branch pre |
| `refs/heads/agent/dropbox-prompt-merged-diff-memory-system-task-spec-group-7-implement-the-parse-d` | RECOVERABLE_VALUE | 0 | merged into the LOCAL default branch but not into origin/main. The only copy is  |
| `refs/heads/agent/dropbox-prompt-merged-diff-memory-system-task-spec-group-7-implement-the-tests-m` | RECOVERABLE_VALUE | 0 | merged into the LOCAL default branch but not into origin/main. The only copy is  |
| `refs/heads/agent/dropbox-prompt-merged-diff-memory-system-task-spec-group-7-split-the-build-task-` | RECOVERABLE_VALUE | 0 | merged into the LOCAL default branch but not into origin/main. The only copy is  |
| `refs/heads/agent/dropbox-prompt-merged-diff-memory-system-task-spec-slice-2` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 3 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/dropbox-release-pipeline-completion-windows-half-l-slice-2-ensure-test-dependenc` | RECOVERABLE_VALUE | 0 | merged into the LOCAL default branch but not into origin/main. The only copy is  |
| `refs/heads/agent/dropbox-release-pipeline-completion-windows-half-l-slice-2-fix-the-authenticatio` | RECOVERABLE_VALUE | 0 | merged into the LOCAL default branch but not into origin/main. The only copy is  |
| `refs/heads/agent/dropbox-release-pipeline-completion-windows-half-l-slice-2-review-and-refactor-t` | RECOVERABLE_VALUE | 0 | merged into the LOCAL default branch but not into origin/main. The only copy is  |
| `refs/heads/agent/dropbox-release-pipeline-completion-windows-half-l-slice-2-write-unit-tests-for-` | RECOVERABLE_VALUE | 0 | merged into the LOCAL default branch but not into origin/main. The only copy is  |
| `refs/heads/agent/dropbox-wave-c-compounding-codegen-platform-spine--slice-1-define-core-types-def` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 3 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/factory-unblock-dropbox-pareto-life-goal-autonomy-stack-p6-earnings-` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/factory-unblock-improve-immediate-auto-merge-on-te-slice-2` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `refs/heads/agent/factory-unblock-improve-immediate-auto-merge-on-te-slice-4-fix-compilation-types` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 3 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/factory-unblock-improve-immediate-auto-merge-on-te-slice-4-fix-quality-gates-ver` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 3 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/factory-unblock-orch-cross-project-depends-fix-remaining-conflicts-r` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `refs/heads/agent/fix-merge-card-amplifier-loop-20260817-mc4a` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 6 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/fix-producer-self-feeding-exclusion` | RECOVERABLE_VALUE | 0 | merged into the LOCAL default branch but not into origin/main. The only copy is  |
| `refs/heads/agent/focused-beethoven-adjudicate-87dbfbd134c7-convention-lint` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 3 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/focused-beethoven-adjudicate-a4c4b321952f-hisanta-mastery-engine` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 5 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/focused-beethoven-orch-rescue-runner-tests-764fd6ce53c9` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 4 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/focused-conflicted-rescue-refs-13-items-5dc36bf5e0-slice-2` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 8 file(s) not on origin/main. NO remote branch prese |
| `refs/heads/agent/followup-fix-merged-diff-test-helper-hardcoded-master-checkout` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `refs/heads/agent/human-decision-host-resume-watch-autounpause-20260820-hrw4` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/improve-automate-configuration-management-slice-1` | RECOVERABLE_VALUE | 0 | 4 unique commit(s) touching 43 file(s) not on origin/main. NO remote branch pres |
| `refs/heads/agent/improve-automated-branch-management-with-gitops-slice-1` | RECOVERABLE_VALUE | 0 | merged into the LOCAL default branch but not into origin/main. The only copy is  |
| `refs/heads/agent/improve-automated-task-state-transition-repair-rep-slice-2-order-the-sub-tasks-t` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 8 file(s) not on origin/main. NO remote branch prese |
| `refs/heads/agent/improve-competitive-scanner-slice-5-update-build-tools-if-necessary` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 5 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/improve-compliance-scheduling-observability` | RECOVERABLE_VALUE | 0 | 73 unique commit(s) touching 117 file(s) not on origin/main. A remote branch pre |
| `refs/heads/agent/improve-enhance-fail-soft-error-handling-mechani-slice-4` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 8 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/improve-enhance-test-automation-for-ci-cd-pipeli-slice-1` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 3 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/improve-enhance-testing-framework-slice-5` | RECOVERABLE_VALUE | 0 | 164 unique commit(s) touching 166 file(s) not on origin/main. A remote branch pr |
| `refs/heads/agent/improve-enhanced-autonomous-error-handling-slice-1` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 8 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/improve-enhanced-error-handling-and-recovery-slice-5` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 20 file(s) not on origin/main. A remote branch prese |
| `refs/heads/agent/improve-enhanced-testing-framework-slice-1` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/improve-implement-advanced-branch-management-recon-slice-4` | RECOVERABLE_VALUE | 0 | merged into the LOCAL default branch but not into origin/main. The only copy is  |
| `refs/heads/agent/improve-implement-advanced-branch-management-zero--slice-2` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 8 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/improve-implement-continuous-testing-automation-slice-1` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/improve-implement-continuous-testing-automation-slice-4` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 6 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/improve-implement-continuous-testing-automation-slice-5` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 3 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/improve-implement-real-time-queue-state-update-slice-1` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/improve-improve-orchestration-with-ai-ml-for-dyn-slice-4` | RECOVERABLE_VALUE | 0 | 163 unique commit(s) touching 164 file(s) not on origin/main. A remote branch pr |
| `refs/heads/agent/improve-improved-ci-cd-pipeline-integration-slice-1-add-a-focused-ci-validation-` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/improve-missing-branch-auto-creator-slice-3-adapt-auto-branch-patch` | RECOVERABLE_VALUE | 0 | 20 unique commit(s) touching 41 file(s) not on origin/main. A remote branch pres |
| `refs/heads/agent/improve-missing-branch-auto-creator-slice-3-finalize-build-and-config` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 11 file(s) not on origin/main. A remote branch prese |
| `refs/heads/agent/improve-missing-branch-auto-creator-slice-3-finalize-build-and-config-clean-015255` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 3 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/improve-missing-branch-auto-creator-slice-3-finalize-build-and-config-clean-039138` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 3 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/improve-missing-branch-auto-creator-slice-3-fix-base-branch-detection-clean-022922` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 3 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/improve-missing-branch-auto-creator-slice-3-locate-decomposition-event-handler-a-clean-043991` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 38 file(s) not on origin/main. A remote branch prese |
| `refs/heads/agent/improve-missing-branch-auto-creator-slice-3-locate-decomposition-event-handler-a-clean-152441` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 4 file(s) not on origin/main. NO remote branch prese |
| `refs/heads/agent/improve-missing-branch-auto-recovery-fleet-wide-slice-3-identify-owner-module` | RECOVERABLE_VALUE | 0 | 14 unique commit(s) touching 33 file(s) not on origin/main. A remote branch pres |
| `refs/heads/agent/improve-missing-branch-auto-recovery-fleet-wide-slice-3-identify-owner-module-co` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/improve-missing-branch-auto-recovery-fleet-wide-slice-3-identify-owner-module-en` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/improve-missing-branch-auto-recovery-fleet-wide-slice-3-identify-owner-module-im` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/improve-missing-branch-auto-recovery-fleet-wide-slice-3-identify-owner-module-is` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/improve-missing-branch-auto-recovery-fleet-wide-slice-3-identify-owner-module-st` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/improve-missing-branch-auto-recovery-fleet-wide-slice-3-identify-owner-module-wi` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/improve-optimize-ci-cd-pipeline-slice-1` | RECOVERABLE_VALUE | 0 | merged into the LOCAL default branch but not into origin/main. The only copy is  |
| `refs/heads/agent/improve-streamline-configuration-management-with-slice-2-integrate-restful-api-l` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 3 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/improve-upgrade-to-a-high-performance-database-slice-3-integrate-new-module` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 3 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/improve-upgrade-to-a-high-performance-database-slice-5` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 1 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/improve-upgrade-to-real-time-configuration-manag-slice-4` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/improve-upgrade-to-real-time-configuration-manag-slice-5` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/improve-value-aware-test-routing-early-exit-r-slice-3-add-early-exit-for-low-ev` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 3 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/improve-value-aware-test-routing-early-exit-r-slice-3-fix-broken-tests` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 4 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/improve-value-aware-test-routing-early-exit-r-slice-3-fix-broken-tests-clean-151469` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 3 file(s) not on origin/main. NO remote branch prese |
| `refs/heads/agent/improve-value-aware-test-routing-early-exit-r-slice-3-fix-broken-tests-commit-fi` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/improve-value-aware-test-routing-early-exit-r-slice-3-fix-broken-tests-ensure-ea` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 1 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/improve-value-aware-test-routing-early-exit-r-slice-3-fix-broken-tests-ensure-fu` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 5 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/improve-value-aware-test-routing-early-exit-r-slice-3-fix-broken-tests-final-gre` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 1 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/improve-value-aware-test-routing-early-exit-r-slice-3-fix-broken-tests-finalize-` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 3 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/improve-value-aware-test-routing-early-exit-r-slice-3-fix-broken-tests-fix-broke` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 1 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/improve-value-aware-test-routing-early-exit-r-slice-3-fix-broken-tests-fix-linte` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/improve-value-aware-test-routing-early-exit-r-slice-3-fix-broken-tests-fix-test-` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 1 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/improve-value-aware-test-routing-early-exit-r-slice-3-fix-broken-tests-fix-tooli` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 3 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/improve-value-aware-test-routing-early-exit-r-slice-3-fix-broken-tests-make-exte` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 7 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/improve-value-aware-test-routing-early-exit-r-slice-3-fix-broken-tests-remove-bl` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 5 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/improve-value-aware-test-routing-early-exit-r-slice-3-fix-broken-tests-repair-or` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/improve-value-aware-test-routing-early-exit-r-slice-3-fix-broken-tests-resolve-r` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 1 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/investigate-audit-anomaly-20260814-p3qz` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/log-p1-queue-clearance-guardrail8-held-20260825-qh7v` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 1 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/log-p1-queue-clearance-guardrail8-held-20260825-r9tz` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 1 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/log-p1-queue-clearance-guardrail8-held-20260825-x8qr` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 1 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/merge-train-attribute-test-failures-to-the-owning-branch` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 2 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/merge-train-blocker-passport-ts-overlay-conflict` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `refs/heads/agent/merged-diff-memory-8-failures` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 3 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/merged-diff-memory-subtask-3-extract-patterns` | RECOVERABLE_VALUE | 0 | merged into the LOCAL default branch but not into origin/main. The only copy is  |
| `refs/heads/agent/oc-autoclear-policy` | RECOVERABLE_VALUE | 0 | 6 unique commit(s) touching 11 file(s) not on origin/main. A remote branch prese |
| `refs/heads/agent/orch-config-consumption` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 3 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/orch-config-consumption-add-targeted-conflict-detector-guard-for` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 5 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/orch-config-consumption-config-consumer-owner-fix-minimal-merge` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/orch-config-consumption-final-verification-run-full-build-tests-` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 5 file(s) not on origin/main. NO remote branch prese |
| `refs/heads/agent/orch-config-consumption-inspect-runner-config-owner` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 3 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/orch-config-consumption-re-run-full-build-test-in-clean-state-to` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 6 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/orch-config-consumption-run-full-build-tests-to-confirm-no-remai` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 4 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/orch-cross-project-depends` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 1 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/orch-cross-project-depends-final-verification-and-cleanup` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/orch-cross-project-depends-fix-any-remaining-merge-fallout-green-ch` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 1 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/orch-cross-project-depends-rebase-cross-project-depends-core-update-planner-py-a` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/perpetual-compliance-hedge-instrument-fix-ts-errors-and-run-tests-run-tests` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 5 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/pinned-express-pause-assertion` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 1 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/prompt-evolution-bandit` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 1 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/qafix-apparently-08172237-prewarm-reason` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/qafix-beethoven-08010307-rebase` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 1 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/qafix-beethoven-08162316` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 1 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/reconcile-conflict-improve-value-aware-test-routing-slice-3` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 2 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/reconcile-evidence-self-feeding` | RECOVERABLE_VALUE | 0 | 3 unique commit(s) touching 11 file(s) not on origin/main. A remote branch prese |
| `refs/heads/agent/reconsider-dropbox-hisanta-mastery-engine-grandma-rail-famil` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 5 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/reconsider-dropbox-recover-the-lease-night-stash-work-branch` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/recover-codex-worktree-orchestrator-session-fabric-current` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 16 file(s) not on origin/main. A remote branch prese |
| `refs/heads/agent/recover-codex-worktree-orchestrator-visibility-remediation` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 14 file(s) not on origin/main. NO remote branch pres |
| `refs/heads/agent/recover-local-tip-value-aware-test-routing-151469` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/recover-missing-branch-backlog-blitz-context-diet-verify` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/recover-missing-branch-crashloop-resilience-mesh-041750c2` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/recover-missing-branch-deployfix-beethoven-07160110` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 2 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/recover-missing-branch-dropbox-v4-global-pass-remediations-cross-app-coor-slice-1` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 3 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/recover-missing-branch-dropbox-wave-c-compounding-codegen-platform-spine-pipeline-structure-part-6-cross-app-platform` | RECOVERABLE_VALUE | 0 | 80 unique commit(s) touching 156 file(s) not on origin/main. A remote branch pre |
| `refs/heads/agent/recover-missing-branch-fix-pinned-express-pause-assertion-not-discriminating` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 1 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/recover-missing-branch-followup-gate-runner-merged-diff-with-merge-candidate-predicate` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 3 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/recover-missing-branch-followup-merge-train-test-output-truncation-breaks-differential-qa` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 3 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/recover-missing-branch-followup-merged-diff-memory-8-genuine-assertion-failures` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 3 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/recover-missing-branch-wire-live-task-owner-into-worktree-reconciler` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 5 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/recover-rescue-refs-group-backlog-batch-and-remainder` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 16 file(s) not on origin/main. A remote branch prese |
| `refs/heads/agent/recover-rescue-refs-group-scanner-and-queue-health` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `refs/heads/agent/recover-rescue-refs-group-session-fabric-and-visibility` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 15 file(s) not on origin/main. A remote branch prese |
| `refs/heads/agent/recover-rescue-refs-group-test-routing-and-relfix` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 1 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/recover-stranded-agent-branches-cowork-20260806-slice-4` | RECOVERABLE_VALUE | 0 | merged into the LOCAL default branch but not into origin/main. The only copy is  |
| `refs/heads/agent/recovery-classifier-supersession-by-touch-date` | RECOVERABLE_VALUE | 0 | merged into the LOCAL default branch but not into origin/main. The only copy is  |
| `refs/heads/agent/release-on-capacity-not-clock-cowork-20260806` | RECOVERABLE_VALUE | 0 | 77 unique commit(s) touching 124 file(s) not on origin/main. A remote branch pre |
| `refs/heads/agent/relfix-pinned-claim-escape-pr-22` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 1 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/relfix-tomorrow-09090552` | RECOVERABLE_VALUE | 0 | merged into the LOCAL default branch but not into origin/main. The only copy is  |
| `refs/heads/agent/relfix-vercel-checks-cache-fix-runner-emit-task-log` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 1 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/remediate-dropbox-beethoven-audit-addendum-two-session-recon-slice-1-verify-beha` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/remediate-dropbox-beethoven-fleet-immune-system-throughput-accelerators-operat-3` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 4 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/remediate-improve-distribute-test-runners-across-fleet-8-slice-3-ensure-prod-bui` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 3 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/remediation-canary-conflict-marker-d12f2155` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 5 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/remediation-canary-real-regression-25eaa900` | RECOVERABLE_VALUE | 0 | 37 unique commit(s) touching 74 file(s) not on origin/main. NO remote branch pre |
| `refs/heads/agent/remediation-canary-real-regression-25eaa900-slice-1` | RECOVERABLE_VALUE | 0 | 124 unique commit(s) touching 110 file(s) not on origin/main. NO remote branch p |
| `refs/heads/agent/remediation-canary-real-regression-9ab9814c` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 8 file(s) not on origin/main. NO remote branch prese |
| `refs/heads/agent/remediation-canary-real-regression-f08dcdfa` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/repair-childless-decompositions-blocking-operator-queue` | RECOVERABLE_VALUE | 0 | 173 unique commit(s) touching 186 file(s) not on origin/main. A remote branch pr |
| `refs/heads/agent/rework-secret-a2a-endpoint-0743615` | RECOVERABLE_VALUE | 0 | 23 unique commit(s) touching 84 file(s) not on origin/main. A remote branch pres |
| `refs/heads/agent/session-proof-of-work` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 3 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/stub-guard-constant-vs-stub` | RECOVERABLE_VALUE | 0 | 3 unique commit(s) touching 7 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/timeout-releasetrain` | RECOVERABLE_VALUE | 0 | 3 unique commit(s) touching 9 file(s) not on origin/main. NO remote branch prese |
| `refs/heads/agent/toolchain-verify-notes-keyerror` | RECOVERABLE_VALUE | 0 | merged into the LOCAL default branch but not into origin/main. The only copy is  |
| `refs/heads/agent/toolchain-worktree-dep-provisioning` | RECOVERABLE_VALUE | 0 | 3 unique commit(s) touching 10 file(s) not on origin/main. A remote branch prese |
| `refs/heads/agent/vercel-json-schema-valid` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 4 file(s) not on origin/main. A remote branch preser |
| `refs/heads/agent/wedged-quarantine` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `refs/heads/backlog-batch-illuminati-1d1b027` | RECOVERABLE_VALUE | 0 | 3 unique commit(s) touching 5 file(s) not on origin/main. NO remote branch prese |
| `refs/heads/backup-node-precatchup2-20260818` | RECOVERABLE_VALUE | 0 | 3 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `refs/heads/chatgpt/chatgpt-local-intake-receipt-safety-20260811-08111725` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. A remote branch preser |
| `refs/heads/chatgpt/chatgpt-local-queue-bridge-20260811-08111602` | RECOVERABLE_VALUE | 0 | 4 unique commit(s) touching 12 file(s) not on origin/main. A remote branch prese |
| `refs/heads/chatgpt/operator-output-truth-session-fabric-20260812-08120203` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 18 file(s) not on origin/main. A remote branch prese |
| `refs/heads/chatgpt/promotion-and-funnel-fixes-20260817-08171915` | RECOVERABLE_VALUE | 0 | 5 unique commit(s) touching 10 file(s) not on origin/main. A remote branch prese |
| `refs/heads/chatgpt/promotion-funnel-and-prod-urls-20260817-08171936` | RECOVERABLE_VALUE | 0 | 6 unique commit(s) touching 10 file(s) not on origin/main. A remote branch prese |
| `refs/heads/chatgpt/promotion-funnel-prod-urls-and-review-fixes-2026-08172022` | RECOVERABLE_VALUE | 0 | 7 unique commit(s) touching 11 file(s) not on origin/main. A remote branch prese |
| `refs/heads/codex/pinned-claim-escape` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 1 file(s) not on origin/main. A remote branch preser |
| `refs/heads/cowork/improvement-loop-repair-20260901` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 20 file(s) not on origin/main. NO remote branch pres |
| `refs/heads/fix-release-train-manifest-import-20260807` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `refs/heads/fix/deps-array-literal` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 1 file(s) not on origin/main. A remote branch preser |
| `refs/heads/fix/merge-truth-prod-evidence-20260817` | RECOVERABLE_VALUE | 0 | 188 unique commit(s) touching 861 file(s) not on origin/main. A remote branch pr |
| `refs/heads/fix/session-20260816-repairs` | RECOVERABLE_VALUE | 0 | 59 unique commit(s) touching 70 file(s) not on origin/main. NO remote branch pre |
| `refs/heads/hotfix/sentinel-rescue-1787143573` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 13 file(s) not on origin/main. A remote branch prese |
| `refs/heads/hotfix/sentinel-rescue-1788655148` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. A remote branch preser |
| `refs/heads/hotfix/sentinel-rescue-1788834648` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. A remote branch preser |
| `refs/heads/hotfix/stash-rescue-1785390774-5c8bda21` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 2 file(s) not on origin/main. A remote branch preser |
| `refs/heads/hotfix/stash-rescue-1785390774-5f879035` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 6 file(s) not on origin/main. A remote branch preser |
| `refs/heads/hotfix/stash-rescue-1785390775-21cf368b` | RECOVERABLE_VALUE | 0 | 3 unique commit(s) touching 14 file(s) not on origin/main. A remote branch prese |
| `refs/heads/hotfix/stash-rescue-1785390775-5a4f8cc1` | RECOVERABLE_VALUE | 0 | 3 unique commit(s) touching 2 file(s) not on origin/main. A remote branch preser |
| `refs/heads/hotfix/stash-rescue-1785390775-60349df1` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 7 file(s) not on origin/main. A remote branch preser |
| `refs/heads/hotfix/stash-rescue-1785390775-74a5da1b` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 2 file(s) not on origin/main. A remote branch preser |
| `refs/heads/hotfix/stash-rescue-1785390775-782d3cc6` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 7 file(s) not on origin/main. A remote branch preser |
| `refs/heads/hotfix/stash-rescue-1785390775-943dc806` | RECOVERABLE_VALUE | 0 | 7 unique commit(s) touching 13 file(s) not on origin/main. A remote branch prese |
| `refs/heads/hotfix/stash-rescue-1785390775-a234ce54` | RECOVERABLE_VALUE | 0 | 3 unique commit(s) touching 9 file(s) not on origin/main. A remote branch preser |
| `refs/heads/hotfix/stash-rescue-1785390775-ac821d4f` | RECOVERABLE_VALUE | 0 | 3 unique commit(s) touching 9 file(s) not on origin/main. A remote branch preser |
| `refs/heads/hotfix/stash-rescue-1785390775-c7c04c0c` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 3 file(s) not on origin/main. A remote branch preser |
| `refs/heads/hotfix/stash-rescue-1785390775-f334ca0f` | RECOVERABLE_VALUE | 0 | 3 unique commit(s) touching 2 file(s) not on origin/main. A remote branch preser |
| `refs/heads/hotfix/stash-rescue-1785390776-242f0814` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. A remote branch preser |
| `refs/heads/hotfix/stash-rescue-1785390776-453f5142` | RECOVERABLE_VALUE | 0 | 3 unique commit(s) touching 3 file(s) not on origin/main. A remote branch preser |
| `refs/heads/hotfix/stash-rescue-1785390776-62cb978c` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. A remote branch preser |
| `refs/heads/hotfix/stash-rescue-1785390776-86a59554` | RECOVERABLE_VALUE | 0 | 3 unique commit(s) touching 2 file(s) not on origin/main. A remote branch preser |
| `refs/heads/hotfix/stash-rescue-1785390776-9c1cf497` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. A remote branch preser |
| `refs/heads/hotfix/stash-rescue-1785390776-d47cc25a` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 5 file(s) not on origin/main. A remote branch preser |
| `refs/heads/hotfix/stash-rescue-1785390776-d8e76ea3` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 2 file(s) not on origin/main. A remote branch preser |
| `refs/heads/hotfix/stash-rescue-1785390776-e20b7728` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. A remote branch preser |
| `refs/heads/hotfix/stash-rescue-1785390777-00d3b013` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. A remote branch preser |
| `refs/heads/hotfix/stash-rescue-1785390777-3449a6c4` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 5 file(s) not on origin/main. A remote branch preser |
| `refs/heads/hotfix/stash-rescue-1785390777-3cf2968d` | RECOVERABLE_VALUE | 0 | 20 unique commit(s) touching 113 file(s) not on origin/main. A remote branch pre |
| `refs/heads/hotfix/stash-rescue-1785390777-47bd6566` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 2 file(s) not on origin/main. A remote branch preser |
| `refs/heads/hotfix/stash-rescue-1785390777-49c1ed3c` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 12 file(s) not on origin/main. A remote branch prese |
| `refs/heads/hotfix/stash-rescue-1785390777-a3f23383` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 2 file(s) not on origin/main. A remote branch preser |
| `refs/heads/hotfix/stash-rescue-1785390777-b23daf80` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 3 file(s) not on origin/main. A remote branch preser |
| `refs/heads/hotfix/stash-rescue-1785390777-dca295aa` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1021 file(s) not on origin/main. A remote branch pre |
| `refs/heads/hotfix/stash-rescue-1785390777-e0d68470` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 8 file(s) not on origin/main. A remote branch preser |
| `refs/heads/hotfix/stash-rescue-1785443042-cba52338` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 2 file(s) not on origin/main. A remote branch preser |
| `refs/heads/hotfix/stash-rescue-1785473643-d220d0a9` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 3 file(s) not on origin/main. A remote branch preser |
| `refs/heads/hotfix/stash-rescue-1785526243-d39b39d6` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. A remote branch preser |
| `refs/heads/hotfix/stash-rescue-1785928364-26716497` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 6 file(s) not on origin/main. A remote branch preser |
| `refs/heads/hotfix/stash-rescue-1787011658-6ca51b97` | RECOVERABLE_VALUE | 0 | 196 unique commit(s) touching 873 file(s) not on origin/main. A remote branch pr |
| `refs/heads/hotfix/stash-rescue-1787026221-a9f38fd7` | RECOVERABLE_VALUE | 0 | 21 unique commit(s) touching 14 file(s) not on origin/main. A remote branch pres |
| `refs/heads/hotfix/stash-rescue-1787040930-80740fe5` | RECOVERABLE_VALUE | 0 | 36 unique commit(s) touching 147 file(s) not on origin/main. A remote branch pre |
| `refs/heads/hotfix/stash-rescue-1788553434-d9cf03a3` | RECOVERABLE_VALUE | 0 | 29 unique commit(s) touching 69 file(s) not on origin/main. A remote branch pres |
| `refs/heads/hotfix/stash-rescue-1788624760-2ba3d617` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 5 file(s) not on origin/main. A remote branch preser |
| `refs/heads/hotfix/stash-rescue-1788856999-793e4b52` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 3 file(s) not on origin/main. A remote branch preser |
| `refs/heads/improve/cost-ledger-fail-soft` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `refs/heads/master` | RECOVERABLE_VALUE | 0 | merged into the LOCAL default branch but not into origin/main. The only copy is  |
| `refs/heads/merge-truth-clean` | RECOVERABLE_VALUE | 0 | 3 unique commit(s) touching 3 file(s) not on origin/main. A remote branch preser |
| `refs/heads/preserve-ec580138-fleet-work` | RECOVERABLE_VALUE | 0 | 26 unique commit(s) touching 85 file(s) not on origin/main. A remote branch pres |
| `refs/heads/preserve-untracked-tests-20260819` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 8 file(s) not on origin/main. A remote branch preser |
| `refs/heads/qa-backup-20260825` | RECOVERABLE_VALUE | 0 | 11 unique commit(s) touching 55 file(s) not on origin/main. NO remote branch pre |
| `refs/heads/rescue/operator-worktree-20260901` | RECOVERABLE_VALUE | 0 | 6 unique commit(s) touching 63 file(s) not on origin/main. NO remote branch pres |
| `refs/heads/salvage/dirty-20260805-1839` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 1 file(s) not on origin/main. A remote branch preser |
| `refs/heads/sweeper-rederive` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 3 file(s) not on origin/main. A remote branch preser |
| `refs/heads/verify/cowork-batch1` | RECOVERABLE_VALUE | 0 | 12 unique commit(s) touching 19 file(s) not on origin/main. NO remote branch pre |
| `refs/heads/verify/solo3` | RECOVERABLE_VALUE | 0 | 3 unique commit(s) touching 7 file(s) not on origin/main. NO remote branch prese |
| `20260803T000716-claude-orchestrator` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 6 file(s) not on origin/main. NO remote branch prese |
| `20260803T000718-breach-remediation` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260803T000719-cade-mirror-negotiation` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260803T000721-cc-mutual-default-fund` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260803T000724-ext-streaming-terms` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260803T000725-oc-autoclear-policy` | RECOVERABLE_VALUE | 0 | 3 unique commit(s) touching 3 file(s) not on origin/main. NO remote branch prese |
| `20260803T000725-pinned-express-lane` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260803T000726-relfix-racefeed-07060650-slice-4` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 4 file(s) not on origin/main. NO remote branch prese |
| `20260803T000751-claude-orchestrator` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 5 file(s) not on origin/main. NO remote branch prese |
| `20260803T001129-claude-orchestrator` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 6 file(s) not on origin/main. NO remote branch prese |
| `20260804T051746-improve-implement-real-time-sync-with-supabase-slice-1-f6528170` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260804T145536-rework-legal-recover-missing-branch-improve-enhanced-testing-pipeline-re-20484dc-366508ee` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `20260804T165021-qafix-beethoven-07230101-8fa6e1aa` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 8 file(s) not on origin/main. NO remote branch prese |
| `20260804T181913-ensemble-on-hard-fc4b8e82` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260805T145454-deployfix-beethoven-07190338-fix-and-verify-vercel-production-build-423c51ca` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260805T150620-deployfix-beethoven-07190338-fix-and-verify-vercel-production-build-6f840dc2` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260805T183028-dropbox-beethoven-audit-addendum-two-session-reconciliation-read-wit-group-1-3a1f3191` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260805T184658-fleet-immune-p0-e6ea22d7` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260805T191227-cc-mutual-default-fund-1d7e8d9a` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1993 file(s) not on origin/main. NO remote branch pr |
| `20260805T191228-cc-solvency-passport-6138fffd` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 355 file(s) not on origin/main. NO remote branch pre |
| `20260805T213902-backlog-batch-apparently-0d157dd-fix-render-decision-briefs-review-deb420f9` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `20260806T061514-backlog-batch-beethoven-e63dfee-apply-economic-scheduler-revenue-patch-test-and--c6abfb86` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260806T062256-backlog-batch-beethoven-e63dfee-apply-economic-scheduler-revenue-patch-test-and--be84d524` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260806T091253-perpetual-compliance-hedge-instrument-fix-ts-errors-and-run-tests-fix-typescript-67a67851` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 9 file(s) not on origin/main. NO remote branch prese |
| `20260806T091547-perpetual-compliance-hedge-instrument-fix-ts-errors-and-run-tests-fix-typescript-90207b25` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 29 file(s) not on origin/main. NO remote branch pres |
| `20260806T093310-relfix-vercel-checks-cache-verify-relfix-vercel-checks-cache-eb142875` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260806T093824-pinned-express-lane-418bb9b8` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260806T100001-canary-gemini-25-canary-gemini-25-setup-add-basic-main-function-setup-import-req-dd1fbbf6` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260806T100003-improve-missing-branch-auto-creator-slice-3-adapt-auto-branch-patch-2ed62263` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260806T100003-improve-missing-branch-auto-creator-slice-3-locate-decomposition-event-handler-a-bedc007c` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260806T100004-improve-value-aware-test-routing-early-exit-r-slice-3-adapt-merged-patterns-65464532` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260806T103718-dropbox-beethoven-audit-addendum-two-session-recon-slice-1-958f7ef5` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `20260806T131026-improve-value-aware-test-routing-early-exit-r-slice-3-adapt-merged-patterns-d09561bf` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1289 file(s) not on origin/main. NO remote branch pr |
| `20260806T153423-dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-governor-ram-floor-5f739408` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `20260806T161111-relfix-release-hold-deadlock-cowork-20260806-e9050616` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 3 file(s) not on origin/main. NO remote branch prese |
| `20260806T162955-dropbox-hisanta-mastery-engine-grandma-rail-family-slice-1-5e34a435` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `20260806T162955-dropbox-hisanta-mastery-engine-grandma-rail-family-slice-3-300e8601` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 3 file(s) not on origin/main. NO remote branch prese |
| `20260806T164930-dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-keepalive-single-supervisor-f1f6e79d` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260806T172735-dropbox-operator-gate-amendment-auto-ship-authoriz-slice-2-9225b0f5` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 3 file(s) not on origin/main. NO remote branch prese |
| `20260806T174624-dropbox-beethoven-fleet-immune-system-throughput-accelerators-operat-2-machine-pipeline-heartbeat-alerts-p0-recovered-21dd6eb0` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260806T181245-dropbox-hisanta-mastery-engine-grandma-rail-family-slice-2-d7e9d285` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 3 file(s) not on origin/main. NO remote branch prese |
| `20260806T181833-dropbox-mission-complete-batch-fusion-unpause-f0a788e3` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260806T184534-backlog-batch-beethoven-ad8643f-99807281` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 5 file(s) not on origin/main. NO remote branch prese |
| `20260806T185750-backlog-batch-beethoven-ad8643f-ef32af11` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 5 file(s) not on origin/main. NO remote branch prese |
| `20260806T185759-pinned-exp-e9572430` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260806T190913-backlog-batch-beethoven-22ee5bc-rework-pinned-express-lane-27ff8b2f` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260806T192819-merged-requires-commit-in-prod-branch-cowork-20260806-6384434a` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 3 file(s) not on origin/main. NO remote branch prese |
| `20260806T193413-merged-requires-commit-in-prod-branch-cowork-20260806-d0eb2024` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260806T193930-merged-requires-commit-in-prod-branch-cowork-20260806-afafdf7b` | RECOVERABLE_VALUE | 0 | 5 unique commit(s) touching 9 file(s) not on origin/main. NO remote branch prese |
| `20260806T193931-release-push-must-fast-forward-cowork-20260806-65f4ad65` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260806T194427-release-on-capacity-not-clock-cowork-20260806-b21f967c` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260806T195448-dropbox-beethoven-audit-addendum-group-4-6aba7288` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260806T201809-improve-value-aware-test-routing-early-exit-r-slice-3-fix-broken-tests-ba304347` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `20260806T202615-improve-value-aware-test-routing-early-exit-r-slice-3-fix-broken-tests-63cf225e` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 3 file(s) not on origin/main. NO remote branch prese |
| `20260806T205258-verify-immune-6079e121` | RECOVERABLE_VALUE | 0 | 4 unique commit(s) touching 6 file(s) not on origin/main. NO remote branch prese |
| `20260806T205901-backlog-batch-beethoven-97e0e39-optimize-prompt-evolution-f1bf84f2` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260806T213005-done-before-card-is-the-stranding-bug-cowork-20260806-267b284a` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 4 file(s) not on origin/main. NO remote branch prese |
| `20260806T213435-auto-resolve-must-not-silently-discard-cowork-20260806-7d26f701` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `20260806T214451-unbounded-scan-window-class-audit-cowork-20260806-16024505` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260806T215006-unbounded-scan-window-class-audit-cowork-20260806-cc95206d` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 4 file(s) not on origin/main. NO remote branch prese |
| `20260806T215726-unbounded-scan-window-class-audit-cowork-20260806-512f19be` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 5 file(s) not on origin/main. NO remote branch prese |
| `20260806T221512-fix-compilation-types-4fb310c6` | RECOVERABLE_VALUE | 0 | 3 unique commit(s) touching 29 file(s) not on origin/main. NO remote branch pres |
| `20260806T222050-pinned-express-lane-7ba11358` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `20260806T222711-pinned-express-lane-cea21305` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 3 file(s) not on origin/main. NO remote branch prese |
| `20260806T223221-backlog-batch-beethoven-d00ef24-prompt-evolution-bandit-verify-build-728d4f32` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `20260806T223225-pinned-express-lane-1c2fe8fa` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 3 file(s) not on origin/main. NO remote branch prese |
| `20260806T223737-pinned-express-lane-3ce88f30` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 3 file(s) not on origin/main. NO remote branch prese |
| `20260806T223741-rt-sync-fbc05b4a` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 3 file(s) not on origin/main. NO remote branch prese |
| `20260806T224241-improve-upgrade-to-a-high-performance-database-slice-3-integrate-new-module-aa3c1231` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 4 file(s) not on origin/main. NO remote branch prese |
| `20260806T224945-relfix-racefeed-07060650-fix-typescript-and-build--slice-4-fix-missing-branch-7d9bd79d` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 2189 file(s) not on origin/main. NO remote branch pr |
| `20260806T225559-backlog-batch-beethoven-d2ada8e-d73f582e` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 3 file(s) not on origin/main. NO remote branch prese |
| `20260806T225912-backlog-batch-beethoven-d2ada8e-fb982c45` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 3 file(s) not on origin/main. NO remote branch prese |
| `20260806T230745-stale-backlog-456-bd2f3690` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `20260806T230931-backlog-batch-beethoven-22ee5bc-recover-pinned-express-lane-add-tests-and-verify-e9112995` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `20260806T231518-crashloop-387dfa7-f6d7d910` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `20260806T232444-promotion-window-ec6cc8e5` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260806T234145-backlog-batch-beethoven-18fa8e4-slice-1-d1056822` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260806T235317-is-merge-commit-55f2d959` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260806T235539-aud2-f28fa31f` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `20260806T235543-wire-merge-detection-823acc38` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260807T001224-testcmd-5b2603af` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `20260807T001758-low-ev-early-exit-b706cb92` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260807T003642-backlog-batch-beethoven-ccacb00-fix-failing-tests-identify-failing-tests-3c9337d5` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 129 file(s) not on origin/main. NO remote branch pre |
| `20260807T015247-dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-p4-releasetrain-vercel-9c79f8f6` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1439 file(s) not on origin/main. NO remote branch pr |
| `20260807T122439-orchestrator-visibility-remediation-4b69f115` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 6 file(s) not on origin/main. NO remote branch prese |
| `20260807T125256-orchestrator-visibility-remediation-15d8c552` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 15 file(s) not on origin/main. NO remote branch pres |
| `20260807T130647-orchestrator-visibility-remediation-a05140c3` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 16 file(s) not on origin/main. NO remote branch pres |
| `20260807T220546-improve-automate-branch-management-slice-3-310c54b3` | RECOVERABLE_VALUE | 0 | 25 unique commit(s) touching 1654 file(s) not on origin/main. NO remote branch p |
| `20260808T040916-improve-immediate-auto-merge-on-test-pass-low-r-slice-3-implement-test-completio-7bf524c4` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 256 file(s) not on origin/main. NO remote branch pre |
| `20260808T184515-cade-mirror-negotiation-5d33743e` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1786 file(s) not on origin/main. NO remote branch pr |
| `20260808T184519-canary-claude-27-slice-3-update-tests-checks-analyze-patch-behavior-analyze-patc-a4a7ec82` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 851 file(s) not on origin/main. NO remote branch pre |
| `20260811T152527-orchestrator-session-fabric-current-364b3d7a` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 15 file(s) not on origin/main. NO remote branch pres |
| `20260811T162001-chatgpt-local-queue-pr20-db762eff` | RECOVERABLE_VALUE | 0 | 3 unique commit(s) touching 12 file(s) not on origin/main. NO remote branch pres |
| `20260813T034449-orchestrator-session-fabric-current-7ba40cac` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 18 file(s) not on origin/main. NO remote branch pres |
| `20260813T040144-pareto-regime-c6ea23ef` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 3 file(s) not on origin/main. NO remote branch prese |
| `20260813T040706-pareto-regime-06849eb0` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 3 file(s) not on origin/main. NO remote branch prese |
| `20260813T045320-reconcile-beethoven-55acd60c-ed040682` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 18 file(s) not on origin/main. NO remote branch pres |
| `20260813T050645-chatgpt-local-reconcile-beethoven-fa5a31393f8a-9f3eda19` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `20260813T051504-chatgpt-local-reconcile-beethoven-fa5a31393f8a-23f42304` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `20260813T061443-chatgpt-local-reconcile-beethoven-10d6c3591091-5e72e360` | RECOVERABLE_VALUE | 0 | 3 unique commit(s) touching 3 file(s) not on origin/main. NO remote branch prese |
| `20260813T062515-chatgpt-local-reconcile-beethoven-6c8911116873-c2310664` | RECOVERABLE_VALUE | 0 | 4 unique commit(s) touching 5 file(s) not on origin/main. NO remote branch prese |
| `20260813T062516-dropbox-beethoven-audit-addendum-two-session-recon-slice-5-7c947218` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260813T063106-chatgpt-local-reconcile-beethoven-6c8911116873-36ff050f` | RECOVERABLE_VALUE | 0 | 4 unique commit(s) touching 5 file(s) not on origin/main. NO remote branch prese |
| `20260813T070224-chatgpt-local-reconcile-beethoven-e4b9212494ba-7abaa1b7` | RECOVERABLE_VALUE | 0 | 5 unique commit(s) touching 7 file(s) not on origin/main. NO remote branch prese |
| `20260813T081208-chatgpt-local-reconcile-beethoven-e0945946bd0d-2d85c63a` | RECOVERABLE_VALUE | 0 | 8 unique commit(s) touching 9 file(s) not on origin/main. NO remote branch prese |
| `20260813T081746-chatgpt-local-reconcile-beethoven-e0945946bd0d-45fefc8b` | RECOVERABLE_VALUE | 0 | 8 unique commit(s) touching 9 file(s) not on origin/main. NO remote branch prese |
| `20260813T084725-fix-canonical-enqueue-trigger-regression-20260812-7bf01722` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `20260813T085137-fix-canonical-enqueue-trigger-regression-20260812-cd80d50c` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `20260813T085754-_fix_rc-17ef9902` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `20260813T091206-canary-claude-27-slice-3-adapt-prior-merged-patterns-extract-proven-diffs-docume-ed55d2b0` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260813T201101-pinned-express-814604f7` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260813T201603-pinned-express-dcf328aa` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260813T202221-backlog-batch-beethoven-22ee5bc-prompt-evolution-bandit-add-bandit-algorithm-8097f70d` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260813T202224-pinned-express-739d0d24` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260813T202811-backlog-batch-beethoven-22ee5bc-prompt-evolution-bandit-add-bandit-algorithm-f0469fa3` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260813T213903-dropbox-beethoven-fleet-immune-system-throughput-accelerators-operat-3-speed-triage-routing-accelerators-p0-28c0982f` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260813T224156-dropbox-beethoven-fleet-immune-system-throughput-accelerators-operat-3-speed-triage-routing-accelerators-p0-603a5082` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `20260813T231931-backlog-batch-beethoven-22ee5bc-convention-conform-slice-2-8309febb-1eda3309` | RECOVERABLE_VALUE | 0 | 34 unique commit(s) touching 59 file(s) not on origin/main. NO remote branch pre |
| `20260813T233826-c27-minimal-680be7c7` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260813T234327-c27-minimal-649efcae` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260814T001131-b4-lane1-df8c6e43` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `20260814T001133-improve-missing-branch-auto-recovery-fleet-wide-slice-3-validate-repository-d8dda29a` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260814T001817-b4-lane1-b79234ec` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 3 file(s) not on origin/main. NO remote branch prese |
| `20260814T001818-canary-claude-27-slice-1-run-checks-90a1e704` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 8 file(s) not on origin/main. NO remote branch prese |
| `20260814T001818-improve-missing-branch-auto-recovery-fleet-wide-slice-3-validate-repository-21f2500e` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260814T003141-backlog-batch-beethoven-288ebe8-f1013477` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260814T010041-crashloop-credresolver-40a109f3` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260814T013845-crashloop-integration-sweeper-cae1d4c9-4f89e3d0` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260814T015051-canary-codex-34-retry-fix-17d73864` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260814T020157-backlog-batch-beethoven-a85e307-28ace672` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260814T020901-backlog-batch-beethoven-a85e307-13e9eddf` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260814T020902-crashloop-cluster-049e2f00-5f82f285` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260814T021406-crashloop-cluster-049e2f00-0fc00d4e` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `20260814T023751-fix-sweeper-branch-name-truncation-1689c7f9` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260814T024437-fix-sweeper-branch-name-truncation-b6295086` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260814T024438-remediate-dropbox-wave-c-compounding-codegen-platform-spine--ca8794-a3a6c0d6` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260814T025058-fix-sweeper-branch-name-truncation-4da759e5` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260814T030759-dropbox-beethoven-fleet-immune-system-1-99437bcf` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260814T032024-fleet-immune-1-abc7b03c` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 3 file(s) not on origin/main. NO remote branch prese |
| `20260814T033735-competitive-scanner-5-55556b63` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 3 file(s) not on origin/main. NO remote branch prese |
| `20260814T034302-competitive-scanner-5-cbc66ea1` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 3 file(s) not on origin/main. NO remote branch prese |
| `20260814T034919-competitive-scanner-5-1e6883f1` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 3 file(s) not on origin/main. NO remote branch prese |
| `20260814T040129-canary-codex-34-210aee22` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260814T040650-competitive-scanner-5-946f7445` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 4 file(s) not on origin/main. NO remote branch prese |
| `20260814T040651-canary-codex-34-8d4eedd4` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260814T041842-canary-codex-34-4375ef4a` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260814T043640-backlog-batch-beethoven-a86bb21-recover-pinned-exp-slice-1-26b72d0b` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `20260814T044159-backlog-batch-beethoven-a86bb21-recover-pinned-exp-slice-1-50dd28e3` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 3 file(s) not on origin/main. NO remote branch prese |
| `20260814T045028-dropbox-recover-lease-night-g1-95167518` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260814T045028-improve-queue-prevent-live-runner-merge-conflicts-slice-1-74bf0115` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260814T045028-recover-missing-branch-dropbox-wave-c-compounding-codegen-platform-spine-pipeline-structure-part-6-cross-app-platform-eb1518dd` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `20260814T045639-backlog-batch-beethoven-d3151d8-d2055a73` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260814T045644-improve-queue-prevent-live-runner-merge-conflicts-slice-1-0e014e1e` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260814T045646-recover-missing-branch-dropbox-wave-c-compounding-codegen-platform-spine-pipeline-structure-part-6-cross-app-platform-1d159448` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 3 file(s) not on origin/main. NO remote branch prese |
| `20260814T050204-backlog-batch-beethoven-d3151d8-87d761c1` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260814T051247-improve-queue-prevent-live-runner-merge-conflicts-slice-1-2442bcd8` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `20260814T072712-leasenight-7071d96c` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260814T072717-wavec-p4-51a1a5e0` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260814T080719-phantom-56758536` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260815T115159-recover-unregistered-repo-trojun-orchestrator-misclone-68475f49` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260815T151339-subscription-tier-monitor-b307d447` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260815T151939-subscription-tier-monitor-2efa858f` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `20260815T155037-backlog-batch-beethoven-a86bb21-recover-pinned-exp-slice-1-3568709e` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `20260815T155824-backlog-batch-beethoven-a86bb21-recover-pinned-exp-slice-1-519f71f7` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 3 file(s) not on origin/main. NO remote branch prese |
| `20260815T160343-backlog-batch-beethoven-a86bb21-recover-pinned-exp-slice-1-6383c3a4` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 3 file(s) not on origin/main. NO remote branch prese |
| `20260815T160936-backlog-batch-beethoven-a86bb21-recover-pinned-exp-slice-1-fb89ac45` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 4 file(s) not on origin/main. NO remote branch prese |
| `20260815T163223-fix-core-rpc-retry-51ae4ecf` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260815T172219-safe-edit-ae2679f4` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260815T172816-safe-edit-5fd01eef` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `20260815T173917-safe-edit-71279f29` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260815T174546-safe-edit-17e023a8` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `20260815T180824-canary-gemini-25-canary-gemini-25-setup-install-dependencies-7171a247` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260815T181331-canary-gemini-25-canary-gemini-25-setup-install-dependencies-97ff52d0` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 3 file(s) not on origin/main. NO remote branch prese |
| `20260815T181909-canary-gemini-25-canary-gemini-25-setup-install-dependencies-ea35b8b0` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 4 file(s) not on origin/main. NO remote branch prese |
| `20260815T194233-safe-edit-cbfca7c1` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 3 file(s) not on origin/main. NO remote branch prese |
| `20260815T200110-canary-gemini-25-canary-gemini-25-setup-install-dependencies-85fe983d` | RECOVERABLE_VALUE | 0 | 5 unique commit(s) touching 4 file(s) not on origin/main. NO remote branch prese |
| `20260815T201040-dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-batch-fusion-unpause-f728f655` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260815T230609-chatgpt-local-reconcile-beethoven-fa219072749e-06d3b538` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260815T231152-chatgpt-local-reconcile-beethoven-fa219072749e-0efcd03c` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260816T230458-safe-edit-e6b8d2b8` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 685 file(s) not on origin/main. NO remote branch pre |
| `20260816T231100-safe-edit-768fbf8d` | RECOVERABLE_VALUE | 0 | 29 unique commit(s) touching 33 file(s) not on origin/main. NO remote branch pre |
| `20260817T000523-safe-edit-42706744` | RECOVERABLE_VALUE | 0 | 55 unique commit(s) touching 61 file(s) not on origin/main. NO remote branch pre |
| `20260817T010232-chatgpt-local-reconcile-beethoven-55acd60c79b1-3214adae` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260817T013843-chatgpt-local-reconcile-beethoven-84fc83c513d9-cfdb9ef4` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260817T014953-chatgpt-local-reconcile-beethoven-84fc83c513d9-7ec82b2c` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260817T015601-chatgpt-local-reconcile-beethoven-8d0702cbd5aa-fb7d0c1d` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `20260817T035848-release-on-capacity-not-clock-cowork-20260806-3805ac77` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260817T043934-chatgpt-local-reconcile-beethoven-8d0702cbd5aa-99b90f7e` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 69 file(s) not on origin/main. NO remote branch pres |
| `20260817T044527-chatgpt-local-reconcile-beethoven-8d0702cbd5aa-bf68cd93` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 68 file(s) not on origin/main. NO remote branch pres |
| `20260817T055034-immune-p0-3fcda7b3` | RECOVERABLE_VALUE | 0 | 3 unique commit(s) touching 4 file(s) not on origin/main. NO remote branch prese |
| `20260817T055035-p4-household-5fdeb7e6` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `20260818T103648-contracts-smarter-add95f9a` | RECOVERABLE_VALUE | 0 | 34 unique commit(s) touching 1574 file(s) not on origin/main. NO remote branch p |
| `20260818T122151-regen-improve-enhance-automated-testing-and-integratio-slice-5-4247669a` | RECOVERABLE_VALUE | 0 | 53 unique commit(s) touching 2006 file(s) not on origin/main. NO remote branch p |
| `20260818T122208-regen-improve-enhance-testing-framework-slice-5-be5ab02f` | RECOVERABLE_VALUE | 0 | 53 unique commit(s) touching 1504 file(s) not on origin/main. NO remote branch p |
| `20260818T122214-regen-recover-missing-branch-backlog-blitz-context-diet-verify-2d556ab2` | RECOVERABLE_VALUE | 0 | 53 unique commit(s) touching 2149 file(s) not on origin/main. NO remote branch p |
| `20260818T122220-smarter-5-95-600d016e` | RECOVERABLE_VALUE | 0 | 34 unique commit(s) touching 763 file(s) not on origin/main. NO remote branch pr |
| `20260818T122238-stub-recover-missing-branch-backlog-blitz-context-diet-verify-5bd230e2` | RECOVERABLE_VALUE | 0 | 53 unique commit(s) touching 2205 file(s) not on origin/main. NO remote branch p |
| `20260818T125128-rework-secret-a2a-endpoint-0743615-a53b0c69` | RECOVERABLE_VALUE | 0 | 25 unique commit(s) touching 1216 file(s) not on origin/main. NO remote branch p |
| `20260818T131320-improve-streamline-merge-workflow-with-ai-based-slice-4-cceb0701` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 2371 file(s) not on origin/main. NO remote branch pr |
| `20260818T203212-session-proof-of-work-01b79c13` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 25 file(s) not on origin/main. NO remote branch pres |
| `20260818T223719-contracts-smarter-59a7cfc5` | RECOVERABLE_VALUE | 0 | 53 unique commit(s) touching 1373 file(s) not on origin/main. NO remote branch p |
| `20260819T003723-wt-origin-a1536958` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260819T010708-wt-canary-b7193028` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260819T013345-wt-inert-cefa4814` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `20260819T013753-reconcile-wt-2b229a51` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 5 file(s) not on origin/main. NO remote branch prese |
| `20260819T125713-wt-fix1-8f286893` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 3 file(s) not on origin/main. NO remote branch prese |
| `20260819T130211-wt-fix1-cba9c902` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 4 file(s) not on origin/main. NO remote branch prese |
| `20260819T130833-wt-fix2-169dbc99` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `20260819T132117-wt-fix3-fb07d366` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 3 file(s) not on origin/main. NO remote branch prese |
| `20260824T040740-beethoven-reconcile-followup-deferred-tests-newer-module-versions-0dee1f8e` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 6 file(s) not on origin/main. NO remote branch prese |
| `20260824T043045-self-feeding-evidence-f3cc57cf` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 4 file(s) not on origin/main. NO remote branch prese |
| `20260901T144153-claude-orchestrator-e8c5817c` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 10 file(s) not on origin/main. NO remote branch pres |
| `20260901T144210-5bee398fbf584c3252b3-55a7693a` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 410 file(s) not on origin/main. NO remote branch pre |
| `20260901T150450-claude-orchestrator-2c152b07` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 16 file(s) not on origin/main. NO remote branch pres |
| `20260901T151536-claude-orchestrator-5097904a` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 18 file(s) not on origin/main. NO remote branch pres |
| `20260901T152048-claude-orchestrator-ec2248c0` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 18 file(s) not on origin/main. NO remote branch pres |
| `20260901T152554-claude-orchestrator-3db29dbb` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 19 file(s) not on origin/main. NO remote branch pres |
| `20260901T155237-claude-orchestrator-1502bdfd` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 20 file(s) not on origin/main. NO remote branch pres |
| `20260901T155814-claude-orchestrator-964f5ec1` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 20 file(s) not on origin/main. NO remote branch pres |
| `20260901T160316-claude-orchestrator-5a14e4c1` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 21 file(s) not on origin/main. NO remote branch pres |
| `20260901T161409-claude-orchestrator-dc0051ec` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 22 file(s) not on origin/main. NO remote branch pres |
| `20260901T170603-claude-orchestrator-1e9239b2` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 25 file(s) not on origin/main. NO remote branch pres |
| `20260901T172142-claude-orchestrator-ba861bff` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 26 file(s) not on origin/main. NO remote branch pres |
| `20260901T172649-claude-orchestrator-78867275` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 26 file(s) not on origin/main. NO remote branch pres |
| `20260901T173203-claude-orchestrator-bfe844b8` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 26 file(s) not on origin/main. NO remote branch pres |
| `20260901T183403-claude-orchestrator-f176fac5` | RECOVERABLE_VALUE | 0 | 3 unique commit(s) touching 33 file(s) not on origin/main. NO remote branch pres |
| `20260901T191048-claude-orchestrator-5ccbb46d` | RECOVERABLE_VALUE | 0 | 3 unique commit(s) touching 34 file(s) not on origin/main. NO remote branch pres |
| `20260901T191533-claude-orchestrator-2e30b87e` | RECOVERABLE_VALUE | 0 | 4 unique commit(s) touching 35 file(s) not on origin/main. NO remote branch pres |
| `20260901T193617-claude-orchestrator-28f12e55` | RECOVERABLE_VALUE | 0 | 4 unique commit(s) touching 35 file(s) not on origin/main. NO remote branch pres |
| `20260901T194650-claude-orchestrator-427aa23a` | RECOVERABLE_VALUE | 0 | 5 unique commit(s) touching 36 file(s) not on origin/main. NO remote branch pres |
| `20260901T195718-claude-orchestrator-76a4ef4c` | RECOVERABLE_VALUE | 0 | 5 unique commit(s) touching 36 file(s) not on origin/main. NO remote branch pres |
| `20260901T200236-claude-orchestrator-c0551b92` | RECOVERABLE_VALUE | 0 | 6 unique commit(s) touching 37 file(s) not on origin/main. NO remote branch pres |
| `20260901T220142-claude-orchestrator-7bdf88ff` | RECOVERABLE_VALUE | 0 | 7 unique commit(s) touching 40 file(s) not on origin/main. NO remote branch pres |
| `20260901T221151-claude-orchestrator-9f415250` | RECOVERABLE_VALUE | 0 | 7 unique commit(s) touching 40 file(s) not on origin/main. NO remote branch pres |
| `20260902T002413-claude-orchestrator-344d45b4` | RECOVERABLE_VALUE | 0 | 7 unique commit(s) touching 41 file(s) not on origin/main. NO remote branch pres |
| `20260902T010629-claude-orchestrator-c9e30061` | RECOVERABLE_VALUE | 0 | 9 unique commit(s) touching 33 file(s) not on origin/main. NO remote branch pres |
| `20260902T010756-5bee398fbf584c3252b3-040fda95` | RECOVERABLE_VALUE | 0 | 7 unique commit(s) touching 28 file(s) not on origin/main. NO remote branch pres |
| `20260902T011959-claude-orchestrator-5d4c01eb` | RECOVERABLE_VALUE | 0 | 9 unique commit(s) touching 35 file(s) not on origin/main. NO remote branch pres |
| `20260902T013843-claude-orchestrator-6db29fa4` | RECOVERABLE_VALUE | 0 | 13 unique commit(s) touching 38 file(s) not on origin/main. NO remote branch pre |
| `20260902T023110-claude-orchestrator-339eda17` | RECOVERABLE_VALUE | 0 | 19 unique commit(s) touching 49 file(s) not on origin/main. NO remote branch pre |
| `20260902T112049-claude-orchestrator-8f04aa00` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `20260902T112614-claude-orchestrator-2b3b1f81` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 3 file(s) not on origin/main. NO remote branch prese |
| `20260902T112614-rel-refresh-9mx2hehr-07a8242f` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 57 file(s) not on origin/main. NO remote branch pres |
| `20260902T112623-5bee398fbf584c3252b3-run-10089-1788347009456346000-83bbd88a` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 3933 file(s) not on origin/main. NO remote branch pr |
| `20260902T115033-claude-orchestrator-c064f67f` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260902T120712-claude-orchestrator-60a9a820` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260902T122840-claude-orchestrator-9e5f4b71` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `20260902T123459-claude-orchestrator-c21bae9c` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 3 file(s) not on origin/main. NO remote branch prese |
| `20260902T124051-claude-orchestrator-3ae7acf0` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 7 file(s) not on origin/main. NO remote branch prese |
| `20260902T125943-claude-orchestrator-eb0d5a95` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260902T145004-rel-refresh-ijgrex6_-2467d02a` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 65 file(s) not on origin/main. NO remote branch pres |
| `20260902T145605-claude-orchestrator-80421d57` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `20260902T160916-claude-orchestrator-acc48b98` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260902T163857-claude-orchestrator-a384092f` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260902T165551-claude-orchestrator-547c0bda` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 5 file(s) not on origin/main. NO remote branch prese |
| `20260902T172702-claude-orchestrator-c8925476` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260902T173743-claude-orchestrator-91320ef3` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `20260902T174857-claude-orchestrator-31c65ecb` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `20260902T175436-claude-orchestrator-00df1b2d` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260902T180401-claude-orchestrator-a7ab2a23` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `20260902T181259-claude-orchestrator-96b62021` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260902T190352-claude-orchestrator-2b32989f` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `20260902T191540-claude-orchestrator-0df3662d` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `20260902T192156-claude-orchestrator-b0b71ca2` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260902T193349-claude-orchestrator-20ceeaf6` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260902T213712-claude-orchestrator-2d747c7f` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260902T220057-canary-pin-87b70ea1` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1121 file(s) not on origin/main. NO remote branch pr |
| `20260903T014558-claude-orchestrator-df742537` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260903T180242-claude-orchestrator-bd4bbf0f` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260903T181421-claude-orchestrator-13ee23f8` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 3 file(s) not on origin/main. NO remote branch prese |
| `20260903T183203-claude-orchestrator-67baacfd` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260903T184221-claude-orchestrator-4ac7a231` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `20260903T185745-claude-orchestrator-bf200211` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260903T190405-claude-orchestrator-255ded46` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `20260903T195456-claude-orchestrator-54f8b933` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260903T202639-claude-orchestrator-27f7da40` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `20260903T205751-claude-orchestrator-2e3fbeb2` | RECOVERABLE_VALUE | 0 | 3 unique commit(s) touching 7 file(s) not on origin/main. NO remote branch prese |
| `20260903T210318-claude-orchestrator-55622df1` | RECOVERABLE_VALUE | 0 | 4 unique commit(s) touching 12 file(s) not on origin/main. NO remote branch pres |
| `20260903T214608-claude-orchestrator-b1b97d03` | RECOVERABLE_VALUE | 0 | 38 unique commit(s) touching 80 file(s) not on origin/main. NO remote branch pre |
| `20260903T224035-claude-orchestrator-2e8bb545` | RECOVERABLE_VALUE | 0 | 40 unique commit(s) touching 81 file(s) not on origin/main. NO remote branch pre |
| `20260903T224727-minimal-task-gnyhzfcc-748846d3` | RECOVERABLE_VALUE | 0 | 3 unique commit(s) touching 3274 file(s) not on origin/main. NO remote branch pr |
| `20260903T224757-5bee398fbf584c3252b3-run-84045-1788475165585027000-d981e8a9` | RECOVERABLE_VALUE | 0 | 3 unique commit(s) touching 250 file(s) not on origin/main. NO remote branch pre |
| `20260903T231442-claude-orchestrator-69614822` | RECOVERABLE_VALUE | 0 | 44 unique commit(s) touching 83 file(s) not on origin/main. NO remote branch pre |
| `20260903T233135-claude-orchestrator-ad0c9a62` | RECOVERABLE_VALUE | 0 | 44 unique commit(s) touching 84 file(s) not on origin/main. NO remote branch pre |
| `20260903T234555-claude-orchestrator-27924255` | RECOVERABLE_VALUE | 0 | 43 unique commit(s) touching 86 file(s) not on origin/main. NO remote branch pre |
| `20260904T000414-claude-orchestrator-c0ae475f` | RECOVERABLE_VALUE | 0 | 44 unique commit(s) touching 86 file(s) not on origin/main. NO remote branch pre |
| `20260904T001811-5bee398fbf584c3252b3-run-83585-1788480575538227000-98d9424d` | RECOVERABLE_VALUE | 0 | 3 unique commit(s) touching 157 file(s) not on origin/main. NO remote branch pre |
| `20260904T024606-5bee398fbf584c3252b3-run-72149-1788489433337543000-40509a11` | RECOVERABLE_VALUE | 0 | 3 unique commit(s) touching 355 file(s) not on origin/main. NO remote branch pre |
| `20260904T041031-5bee398fbf584c3252b3-run-70327-1788494953423110000-a07d5c12` | RECOVERABLE_VALUE | 0 | 3 unique commit(s) touching 404 file(s) not on origin/main. NO remote branch pre |
| `20260904T043201-minimal-task-hvh32mig-34a1d64e` | RECOVERABLE_VALUE | 0 | 3 unique commit(s) touching 3418 file(s) not on origin/main. NO remote branch pr |
| `20260904T051502-claude-orchestrator-abb08ed6` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260904T052441-claude-orchestrator-1b4546c5` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260904T053329-claude-orchestrator-11d34f87` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `20260904T053439-5bee398fbf584c3252b3-run-61697-1788499947595714000-a71c0f2b` | RECOVERABLE_VALUE | 0 | 3 unique commit(s) touching 250 file(s) not on origin/main. NO remote branch pre |
| `20260904T055009-claude-orchestrator-c9689758` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `20260904T060928-claude-orchestrator-240699b2` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260904T062421-5bee398fbf584c3252b3-run-61697-1788499947595714000-f5e9ad7c` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 4 file(s) not on origin/main. NO remote branch prese |
| `20260904T062422-5bee398fbf584c3252b3-run-70327-1788494953423110000-84c1c07d` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `20260904T062423-5bee398fbf584c3252b3-run-72149-1788489433337543000-8a58a074` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `20260904T073020-claude-orchestrator-b397e306` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260904T073032-5bee398fbf584c3252b3-run-69198-1788506702742473000-0668e07d` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `20260904T073822-5bee398fbf584c3252b3-run-69198-1788506702742473000-0f986a00` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `20260904T074956-5bee398fbf584c3252b3-run-69198-1788506702742473000-84b04809` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `20260904T075528-5bee398fbf584c3252b3-run-29208-1788508027427749000-60cc6111` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260904T083727-5bee398fbf584c3252b3-run-82798-1788510671234112000-b1984ab9` | RECOVERABLE_VALUE | 0 | 3 unique commit(s) touching 248 file(s) not on origin/main. NO remote branch pre |
| `20260904T090425-5bee398fbf584c3252b3-run-67150-1788512392138289000-3de71a0c` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `20260904T093141-5bee398fbf584c3252b3-run-67150-1788512392138289000-bede04c8` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260904T100640-5bee398fbf584c3252b3-run-62844-1788516131936712000-cb097126` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260904T103737-5bee398fbf584c3252b3-run-62844-1788516131936712000-5f3fa197` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 3 file(s) not on origin/main. NO remote branch prese |
| `20260904T110004-claude-orchestrator-12d038fb` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `20260904T110020-5bee398fbf584c3252b3-run-13073-1788509484600141000-73d87439` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `20260904T111907-5bee398fbf584c3252b3-run-23935-1788520578085240000-6fb3ba1d` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 4 file(s) not on origin/main. NO remote branch prese |
| `20260904T112359-5bee398fbf584c3252b3-run-44085-1788520965128890000-cdbc5073` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `20260904T113452-5bee398fbf584c3252b3-run-44085-1788520965128890000-e5338d97` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 4 file(s) not on origin/main. NO remote branch prese |
| `20260904T114410-5bee398fbf584c3252b3-run-69068-1788522082754622000-d844cf5b` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 3 file(s) not on origin/main. NO remote branch prese |
| `20260904T115006-canary-deepseek-1-a8218d4f` | RECOVERABLE_VALUE | 0 | 5 unique commit(s) touching 25 file(s) not on origin/main. NO remote branch pres |
| `20260904T151005-claude-orchestrator-0c1cf91f` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 3 file(s) not on origin/main. NO remote branch prese |
| `20260904T151955-claude-orchestrator-850cda49` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `20260904T154450-claude-orchestrator-d14117e4` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `20260904T155639-claude-orchestrator-39256b91` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 3 file(s) not on origin/main. NO remote branch prese |
| `20260904T155649-canary-deepseek-1-35da1bce` | RECOVERABLE_VALUE | 0 | 9 unique commit(s) touching 18 file(s) not on origin/main. NO remote branch pres |
| `20260904T163137-claude-orchestrator-7526a136` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 4 file(s) not on origin/main. NO remote branch prese |
| `20260904T164023-claude-orchestrator-b33ee60f` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 3 file(s) not on origin/main. NO remote branch prese |
| `20260904T165657-claude-orchestrator-00b08173` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 3 file(s) not on origin/main. NO remote branch prese |
| `20260904T165711-canary-gpt-mini-3-84a96869` | RECOVERABLE_VALUE | 0 | 3 unique commit(s) touching 1237 file(s) not on origin/main. NO remote branch pr |
| `20260904T171940-cade-mirror-negotiation-65c33ec2` | RECOVERABLE_VALUE | 0 | 34 unique commit(s) touching 1571 file(s) not on origin/main. NO remote branch p |
| `20260904T182241-claude-orchestrator-3b381da3` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 8 file(s) not on origin/main. NO remote branch prese |
| `20260904T182847-claude-orchestrator-3e9b6095` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260904T191318-claude-orchestrator-9d8a9e3d` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 3 file(s) not on origin/main. NO remote branch prese |
| `20260904T191810-claude-orchestrator-d6d84651` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 4 file(s) not on origin/main. NO remote branch prese |
| `20260904T192410-claude-orchestrator-2198bae1` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 5 file(s) not on origin/main. NO remote branch prese |
| `20260904T194424-claude-orchestrator-6793d691` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 5 file(s) not on origin/main. NO remote branch prese |
| `20260904T202633-claude-orchestrator-e2045d98` | RECOVERABLE_VALUE | 0 | 27 unique commit(s) touching 45 file(s) not on origin/main. NO remote branch pre |
| `20260904T203607-claude-orchestrator-1c8270ae` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260904T215428-claude-orchestrator-df7ef335` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `20260904T215439-canary-deepseek-1-8e66fee4` | RECOVERABLE_VALUE | 0 | 9 unique commit(s) touching 18 file(s) not on origin/main. NO remote branch pres |
| `20260904T222429-claude-orchestrator-9217bd78` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 4 file(s) not on origin/main. NO remote branch prese |
| `20260904T222431-lint-base-7a1b4f85` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `20260904T223023-claude-orchestrator-c0dcfd83` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260904T230039-claude-orchestrator-cc131152` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `20260904T233540-claude-orchestrator-deecf6d1` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `20260905T002743-claude-orchestrator-3917fa69` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 633 file(s) not on origin/main. NO remote branch pre |
| `20260905T005818-canary-deepseek-1-e10b9d15` | RECOVERABLE_VALUE | 0 | 9 unique commit(s) touching 19 file(s) not on origin/main. NO remote branch pres |
| `20260905T010131-5bee398fbf584c3252b3-run-92737-1788569735363546000-5e594bee` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 436 file(s) not on origin/main. NO remote branch pre |
| `20260905T022340-claude-orchestrator-c2b0cddb` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `20260905T025326-claude-orchestrator-14b5e4c2` | RECOVERABLE_VALUE | 0 | 3 unique commit(s) touching 3 file(s) not on origin/main. NO remote branch prese |
| `20260905T032050-claude-orchestrator-03de61b7` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `20260905T060122-canary-pin-bc8e4f53` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 4436 file(s) not on origin/main. NO remote branch pr |
| `20260905T071448-claude-orchestrator-535cab0e` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `20260905T103553-claude-orchestrator-4963a6d1` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 4 file(s) not on origin/main. NO remote branch prese |
| `20260905T112144-canary-deepseek-1-0aa1329e` | RECOVERABLE_VALUE | 0 | 9 unique commit(s) touching 19 file(s) not on origin/main. NO remote branch pres |
| `20260905T164837-claude-orchestrator-84e741ee` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `20260905T204901-claude-orchestrator-2392b4f3` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `20260905T210240-claude-orchestrator-67605998` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 3 file(s) not on origin/main. NO remote branch prese |
| `20260906-dropped-automerge-6d74b1df` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 8 file(s) not on origin/main. NO remote branch prese |
| `20260906T095231-claude-orchestrator-ba41be2f` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260906T160304-claude-orchestrator-8e48dbf1` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 5 file(s) not on origin/main. NO remote branch prese |
| `20260906T161418-claude-orchestrator-3e872779` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260906T163739-claude-orchestrator-29337aba` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 3 file(s) not on origin/main. NO remote branch prese |
| `20260906T164414-claude-orchestrator-24aed9ab` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260906T170346-claude-orchestrator-4c034c97` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 4 file(s) not on origin/main. NO remote branch prese |
| `20260906T180814-claude-orchestrator-3a560e9f` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260906T183200-claude-orchestrator-d35bd019` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `20260906T184708-claude-orchestrator-63c0735d` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 3 file(s) not on origin/main. NO remote branch prese |
| `20260906T185433-claude-orchestrator-f3b89a13` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 4 file(s) not on origin/main. NO remote branch prese |
| `20260906T200352-claude-orchestrator-e01fb802` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260906T234525-claude-orchestrator-67c9d1c7` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260906T235543-claude-orchestrator-4940675d` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `20260907T014930-claude-orchestrator-43739da8` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260907T034421-oc-autoclear-policy-713dd094` | RECOVERABLE_VALUE | 0 | 6 unique commit(s) touching 10 file(s) not on origin/main. NO remote branch pres |
| `20260907T074827-claude-orchestrator-434a3056` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 11 file(s) not on origin/main. NO remote branch pres |
| `20260907T094809-claude-orchestrator-3c2c1905` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 12 file(s) not on origin/main. NO remote branch pres |
| `20260907T160539-claude-orchestrator-bbb18aba` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 13 file(s) not on origin/main. NO remote branch pres |
| `20260907T161447-claude-orchestrator-e2e60b26` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 17 file(s) not on origin/main. NO remote branch pres |
| `20260907T162656-claude-orchestrator-46acb388` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 17 file(s) not on origin/main. NO remote branch pres |
| `20260907T180637-claude-orchestrator-c2348297` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260907T231316-claude-orchestrator-32c8f523` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 12 file(s) not on origin/main. NO remote branch pres |
| `20260907T232400-claude-orchestrator-8b2036d8` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 16 file(s) not on origin/main. NO remote branch pres |
| `20260907T235408-claude-orchestrator-635e8604` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260908T002327-5bee398fbf584c3252b3-run-95881-1788824413096639000-e73b6317` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 695 file(s) not on origin/main. NO remote branch pre |
| `20260908T005236-claude-orchestrator-ca1fb88a` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 12 file(s) not on origin/main. NO remote branch pres |
| `20260908T011037-claude-orchestrator-aca90551` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 11 file(s) not on origin/main. NO remote branch pres |
| `20260908T014446-claude-orchestrator-f48e34e6` | RECOVERABLE_VALUE | 0 | 3 unique commit(s) touching 12 file(s) not on origin/main. NO remote branch pres |
| `20260908T020706-claude-orchestrator-3a4393c0` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 14 file(s) not on origin/main. NO remote branch pres |
| `20260908T021354-5bee398fbf584c3252b3-run-66305-1788832658052891000-04360627` | RECOVERABLE_VALUE | 0 | 3 unique commit(s) touching 4002 file(s) not on origin/main. NO remote branch pr |
| `20260908T022304-claude-orchestrator-f940b29a` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 3 file(s) not on origin/main. NO remote branch prese |
| `20260908T031542-claude-orchestrator-01358045` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 4 file(s) not on origin/main. NO remote branch prese |
| `20260908T042342-rework-legal-cont-batch-darwn-277f0bd-9657042-2585e8a9` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260908T091235-improve-enhance-testing-framework-slice-5-04d4b238` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `20260908T094656-claude-orchestrator-aa94af48` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 4 file(s) not on origin/main. NO remote branch prese |
| `20260908T100107-improve-enhance-testing-framework-slice-5-487afb7d` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 3 file(s) not on origin/main. NO remote branch prese |
| `20260908T100126-5bee398fbf584c3252b3-run-58098-1788861542170040000-f63e7e8b` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 3898 file(s) not on origin/main. NO remote branch pr |
| `20260908T113337-canary-self-deploy-live-slice-1-a044eac5` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 3 file(s) not on origin/main. NO remote branch prese |
| `20260908T125618-claude-orchestrator-7529f6bd` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 4 file(s) not on origin/main. NO remote branch prese |
| `20260908T131112-claude-orchestrator-0f02b4f6` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 4 file(s) not on origin/main. NO remote branch prese |
| `20260908T154147-claude-orchestrator-8fc77607` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 4 file(s) not on origin/main. NO remote branch prese |
| `20260908T162028-5bee398fbf584c3252b3-run-11848-1788883528475544000-095fa7b5` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 5592 file(s) not on origin/main. NO remote branch pr |
| `20260908T164830-5eed4d232cc6fd3c7073-run-66824-1788871359866084000-9e78c704` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 4 file(s) not on origin/main. NO remote branch prese |
| `20260908T170523-claude-orchestrator-39352a1d` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 4 file(s) not on origin/main. NO remote branch prese |
| `20260908T172055-claude-orchestrator-e3e08c51` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 4 file(s) not on origin/main. NO remote branch prese |
| `20260908T175539-claude-orchestrator-2d139500` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 4 file(s) not on origin/main. NO remote branch prese |
| `20260909T043656-dropbox-release-pipeline-completion-windows-half-l-slice-2-ensure-test-dependenc-b57ed629` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260909T044919-reconcile-f8c1bb486dd1-587e3029` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `20260909T051200-chatgpt-local-reconcile-beethoven-c59669efa6f0-65218e2c` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260909T051747-oauth-refresh-fix-04d559e7` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 3 file(s) not on origin/main. NO remote branch prese |
| `20260909T053448-claude-orchestrator-db5d2124` | RECOVERABLE_VALUE | 0 | 3 unique commit(s) touching 8 file(s) not on origin/main. NO remote branch prese |
| `20260909T053454-dropbox-release-pipeline-completion-windows-half-l-slice-2-ensure-test-dependenc-9a13a684` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 3 file(s) not on origin/main. NO remote branch prese |
| `20260909T054256-fullsuite-wt-d911a891` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 3 file(s) not on origin/main. NO remote branch prese |
| `20260909T054308-5bee398fbf584c3252b3-6bb0189f` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 2234 file(s) not on origin/main. NO remote branch pr |
| `20260909T054309-5bee398fbf584c3252b3-run-57309-1788931317076138000-18c7d5eb` | RECOVERABLE_VALUE | 0 | 4 unique commit(s) touching 10 file(s) not on origin/main. NO remote branch pres |
| `20260909T062026-5bee398fbf584c3252b3-run-62391-1788934084200059000-1fde5d39` | RECOVERABLE_VALUE | 0 | 3 unique commit(s) touching 9 file(s) not on origin/main. NO remote branch prese |
| `20260909T063017-relfix-identity-daa307d4` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 17 file(s) not on origin/main. NO remote branch pres |
| `20260909T095325-claude-orchestrator-b270b854` | RECOVERABLE_VALUE | 0 | 3 unique commit(s) touching 8 file(s) not on origin/main. NO remote branch prese |
| `20260909T121254-claude-orchestrator-3581ce58` | RECOVERABLE_VALUE | 0 | 3 unique commit(s) touching 8 file(s) not on origin/main. NO remote branch prese |
| `20260909T122938-improve-automated-branch-management-with-gitops-slice-1-11da635f` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 8 file(s) not on origin/main. NO remote branch prese |
| `20260909T122940-improve-enhanced-testing-infrastructure-slice-4-bbc5f606` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 8 file(s) not on origin/main. NO remote branch prese |
| `20260909T122941-improve-implement-real-time-sync-between-web-and-slice-4-117a7c24` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 8 file(s) not on origin/main. NO remote branch prese |
| `20260909T132842-improve-improve-orchestration-with-ai-ml-for-dyn-slice-4-b5978208` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 8 file(s) not on origin/main. NO remote branch prese |
| `20260909T145156-claude-orchestrator-c7643cfd` | RECOVERABLE_VALUE | 0 | 4 unique commit(s) touching 9 file(s) not on origin/main. NO remote branch prese |
| `20260909T145227-5bee398fbf584c3252b3-run-75398-1788965032925518000-890feb9f` | RECOVERABLE_VALUE | 0 | 5 unique commit(s) touching 12 file(s) not on origin/main. NO remote branch pres |
| `20260909T151052-5bee398fbf584c3252b3-run-6139-1788966431398720000-82833d33` | RECOVERABLE_VALUE | 0 | 4 unique commit(s) touching 10 file(s) not on origin/main. NO remote branch pres |
| `20260909T152638-claude-orchestrator-7a476b84` | RECOVERABLE_VALUE | 0 | 4 unique commit(s) touching 9 file(s) not on origin/main. NO remote branch prese |
| `20260909T154742-improve-automated-branch-management-with-gitops-slice-1-4cd3d60f` | RECOVERABLE_VALUE | 0 | 3 unique commit(s) touching 9 file(s) not on origin/main. NO remote branch prese |
| `20260909T154753-improve-enhanced-testing-infrastructure-slice-4-9dc7c00d` | RECOVERABLE_VALUE | 0 | 3 unique commit(s) touching 9 file(s) not on origin/main. NO remote branch prese |
| `20260909T154755-improve-implement-real-time-sync-between-web-and-slice-4-bd27545d` | RECOVERABLE_VALUE | 0 | 3 unique commit(s) touching 9 file(s) not on origin/main. NO remote branch prese |
| `20260909T154756-improve-improve-orchestration-with-ai-ml-for-dyn-slice-4-4ba191ce` | RECOVERABLE_VALUE | 0 | 3 unique commit(s) touching 9 file(s) not on origin/main. NO remote branch prese |
| `20260909T155704-claude-orchestrator-ac51ae8c` | RECOVERABLE_VALUE | 0 | 4 unique commit(s) touching 10 file(s) not on origin/main. NO remote branch pres |
| `20260909T155812-5bee398fbf584c3252b3-run-24735-1788969128060907000-fab7191f` | RECOVERABLE_VALUE | 0 | 5 unique commit(s) touching 18 file(s) not on origin/main. NO remote branch pres |
| `20260909T171133-improve-enhance-testing-framework-slice-5-6b55b183` | RECOVERABLE_VALUE | 0 | 4 unique commit(s) touching 11 file(s) not on origin/main. NO remote branch pres |
| `20260909T224758-dropbox-pareto-p2-delegation-firewall-5-digest-34778329` | RECOVERABLE_VALUE | 0 | merged into the LOCAL default branch but not into origin/main. The only copy is  |
| `20260909T230000-toolchain-worktree-dep-provisioning-decae144` | RECOVERABLE_VALUE | 0 | 4 unique commit(s) touching 9 file(s) not on origin/main. NO remote branch prese |
| `20260910T000634-claude-orchestrator-b25d3fa0` | RECOVERABLE_VALUE | 0 | merged into the LOCAL default branch but not into origin/main. The only copy is  |
| `20260910T003058-claude-orchestrator-16e4d6dd` | RECOVERABLE_VALUE | 0 | merged into the LOCAL default branch but not into origin/main. The only copy is  |
| `20260910T003136-5bee398fbf584c3252b3-run-67776-1788998826259073000-76c89792` | RECOVERABLE_VALUE | 0 | 22 unique commit(s) touching 26 file(s) not on origin/main. NO remote branch pre |
| `20260910T010505-claude-orchestrator-ba166e76` | RECOVERABLE_VALUE | 0 | merged into the LOCAL default branch but not into origin/main. The only copy is  |
| `20260910T010513-chatgpt-local-reconcile-beethoven-4ca585bf4ce0-cba65cfa` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260910T010533-canary-pin-bc7c91e1` | RECOVERABLE_VALUE | 0 | 158 unique commit(s) touching 142 file(s) not on origin/main. NO remote branch p |
| `20260910T010537-5bee398fbf584c3252b3-run-28519-1789001679715324000-90636a8e` | RECOVERABLE_VALUE | 0 | 154 unique commit(s) touching 139 file(s) not on origin/main. NO remote branch p |
| `20260910T010539-5bee398fbf584c3252b3-run-96830-1789000937237836000-dc3155f5` | RECOVERABLE_VALUE | 0 | 141 unique commit(s) touching 128 file(s) not on origin/main. NO remote branch p |
| `20260910T011704-claude-orchestrator-8e4b0da9` | RECOVERABLE_VALUE | 0 | merged into the LOCAL default branch but not into origin/main. The only copy is  |
| `20260910T011728-canary-pin-4adf2cf8` | RECOVERABLE_VALUE | 0 | 162 unique commit(s) touching 162 file(s) not on origin/main. NO remote branch p |
| `20260910T011732-5bee398fbf584c3252b3-run-29227-1789002578368772000-eee74e33` | RECOVERABLE_VALUE | 0 | 160 unique commit(s) touching 160 file(s) not on origin/main. NO remote branch p |
| `20260910T013040-repair-childless-decompositions-blocking-operator-queue-70d623d0` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `20260910T013051-canary-pin-dba45dc4` | RECOVERABLE_VALUE | 0 | 164 unique commit(s) touching 165 file(s) not on origin/main. NO remote branch p |
| `20260910T013118-5bee398fbf584c3252b3-run-48291-1789003690994293000-3d413042` | RECOVERABLE_VALUE | 0 | 165 unique commit(s) touching 166 file(s) not on origin/main. NO remote branch p |
| `20260910T031934-repair-childless-decompositions-blocking-operator-queue-88bd9141` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 4 file(s) not on origin/main. NO remote branch prese |
| `20260910T033654-5bee398fbf584c3252b3-run-21029-1789011128447381000-fa0d70ab` | RECOVERABLE_VALUE | 0 | 165 unique commit(s) touching 170 file(s) not on origin/main. NO remote branch p |
| `20260910T041527-reconcile-4a838e298f31-fix-01edfc63` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 5 file(s) not on origin/main. NO remote branch prese |
| `20260910T042524-reconcile-4a838e298f31-fix-728d06ec` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 6 file(s) not on origin/main. NO remote branch prese |
| `20260910T043026-reconcile-4a838e298f31-fix-baffc82b` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 6 file(s) not on origin/main. NO remote branch prese |
| `refs/rescue/slot-untracked-20260904` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 11 file(s) not on origin/main. NO remote branch pres |
| `refs/rescue/unreferenced-20260904/2-1eabddf7` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `refs/rescue/unreferenced-20260904/3-b9262403` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/backlog-batch-beethoven-01b6ed7/1786660426` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 4 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/backlog-batch-beethoven-04cfd39/1786587641` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 3 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/backlog-batch-beethoven-0c516d2/1786589785` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 5 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/backlog-batch-beethoven-1d2e0cf/1786573139` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 3 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/backlog-batch-beethoven-22ee5bc-convention-conform-slice-1/1786573536` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 4 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/backlog-batch-beethoven-22ee5bc-convention-conform-slice-2/1786606400` | RECOVERABLE_VALUE | 0 | 22 unique commit(s) touching 42 file(s) not on origin/main. NO remote branch pre |
| `refs/archive/agent/backlog-batch-beethoven-22ee5bc-convention-conform-slice-5/1786573348` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 3 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/backlog-batch-beethoven-22ee5bc-convention-conform-slice-5/1786592962` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 3 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/backlog-batch-beethoven-22ee5bc-prompt-evolution-bandit-update-claude-interface/1786589726` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/backlog-batch-beethoven-2863be9-merge-changes-slice-2/1786589847` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/backlog-batch-beethoven-2863be9-recover-economic-scheduler-revenue/1786587907` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/backlog-batch-beethoven-2863be9-update-tests-slice-2/1786591334` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/backlog-batch-beethoven-35584ad/1786591681` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/backlog-batch-beethoven-665c06d/1786574709` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 3 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/backlog-batch-beethoven-7b53616-apply-orch-config-patch/1786923212` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/backlog-batch-beethoven-a86bb21-recover-economic-scheduler-revenue-commit-fix-an/1786659314` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/backlog-batch-beethoven-a86bb21-recover-pinned-exp-slice-2/1786589633` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/backlog-batch-beethoven-a86bb21-recover-pinned-express-lane-apply-fix-and-valida/1786923328` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/backlog-batch-beethoven-c9a51c6-pinned-express-lane-repair/1786923011` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/backlog-batch-beethoven-ccacb00-repair-build-tools-check-build-tools/1786923274` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/backlog-batch-beethoven-e8afcee-inventory-clean-environment/1786923238` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/backlog-batch-beethoven-ea327e9/1786589584` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/canary-claude-27-slice-3-adapt-prior-merged-patterns-extract-proven-diffs-extrac/1786591607` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/canary-claude-27-slice-3-update-tests-checks-write-failing-test-analyze-patch-an/1786587686` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/canary-codex-24/1786106107` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/canary-codex-34/1786122181` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 3 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/canary-gemini-25-canary-gemini-25-metrics-create-gauge-set-gauge-to-0-on-validat/1786658197` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/canary-gemini-25-canary-gemini-25-metrics-http-server-setup/1786660604` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/canary-gemini-25-canary-gemini-25-request-invalid-key-error/1786591490` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/canary-gemini-25-canary-gemini-25-validate-add-validation-function-add-validate-/1786571501` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/canary-gemini-25-canary-gemini-25-validate-add-validation-function-implement-val/1786587776` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 3 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/canary-gemini-25-canary-gemini-25-validate-add-validation-function-implement-val/1786661719` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 3 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/canary-gemini-25-canary-gemini-25-validate-add-validation-function-implement-val/1786922989` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 5 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/canary-gemini-25-integrate-with-mainline/1786571755` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/canary-ollama-2-3-slice-3/1788496023` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/chatgpt-local-reconcile-beethoven-179a43b4d07a/1786928154` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 392 file(s) not on origin/main. NO remote branch pre |
| `refs/archive/agent/chatgpt-local-reconcile-beethoven-1b0973366143/1789003947` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/chatgpt-local-reconcile-beethoven-48ada8033590/1786943778` | RECOVERABLE_VALUE | 0 | 4 unique commit(s) touching 81 file(s) not on origin/main. NO remote branch pres |
| `refs/archive/agent/chatgpt-local-reconcile-beethoven-48ae8f413643/1786939899` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/chatgpt-local-reconcile-beethoven-55acd60c79b1/1786941047` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 4 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/chatgpt-local-reconcile-beethoven-671c267eedf3/1786923646` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 4 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/chatgpt-local-reconcile-beethoven-73b0c02a3342/1786943016` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 4 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/chatgpt-local-reconcile-beethoven-c54c216bc5d3/1786922801` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/chatgpt-local-reconcile-beethoven-c59669efa6f0/1789004106` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/chatgpt-local-reconcile-beethoven-ca93a1b7be55/1786923620` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 4 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/chatgpt-local-reconcile-beethoven-d854da55ab98/1786922793` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/chatgpt-local-reconcile-beethoven-fa219072749e/1786922889` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 4 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/codex-recover-operator-output-truth-patch-7db8cf82/1786585718` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 18 file(s) not on origin/main. NO remote branch pres |
| `refs/archive/agent/codex-recover-session-fabric-broken-worktree-7db8cf82/1786573059` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/codex-recover-session-fabric-broken-worktree-7db8cf82/1786587593` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/copyfix-beethoven-07180848-slice-3/1786122690` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/done-to-merged-is-the-new-bottleneck-cowork-20260806/1786210919` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 4 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/done-to-merged-is-the-new-bottleneck-cowork-20260806/1786941060` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 4 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/dropbox-beethoven-audit-addendum-two-session-recon-slice-1-adapt-patch-template/1786466175` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/dropbox-beethoven-audit-addendum-two-session-recon-slice-1-integrate-core-logic/1786467030` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 3 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/dropbox-beethoven-audit-addendum-two-session-recon-slice-1-integrate-core-logic/1786569578` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 3 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/dropbox-beethoven-audit-addendum-two-session-recon-slice-1-refactor-for-cleanlin/1786466936` | RECOVERABLE_VALUE | 0 | 3 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/dropbox-beethoven-audit-addendum-two-session-recon-slice-1-refactor-for-cleanlin/1786569773` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/dropbox-beethoven-audit-addendum-two-session-recon-slice-1-refactor-for-cleanlin/1786577670` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/dropbox-beethoven-audit-addendum-two-session-recon-slice-1-verify-behavioral-equ/1786466529` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/dropbox-beethoven-audit-addendum-two-session-recon-slice-1-verify-behavioral-equ/1786569671` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/dropbox-beethoven-audit-addendum-two-session-recon-slice-2-recovered/1786043439` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 4 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/dropbox-beethoven-audit-addendum-two-session-recon-slice-3-recovered/1786042469` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 4 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/dropbox-beethoven-audit-addendum-two-session-recon-slice-5-analyze-existing-bran/1786578587` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/dropbox-beethoven-audit-addendum-two-session-recon-slice-5-recreate-content/1786467779` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/dropbox-beethoven-audit-addendum-two-session-recon-slice-5/1786023288` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 3 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/dropbox-beethoven-audit-addendum-two-session-reconciliation-read-wit-group-1/1786026470` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 5 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/dropbox-beethoven-audit-addendum-two-session-reconciliation-read-wit-group-3/1786026463` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 4 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/dropbox-beethoven-audit-addendum-two-session-reconciliation-read-wit-group-4/1786026465` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 5 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/dropbox-beethoven-audit-addendum-two-session-reconciliation-read-wit-group-5/1786092058` | RECOVERABLE_VALUE | 0 | 10 unique commit(s) touching 20 file(s) not on origin/main. NO remote branch pre |
| `refs/archive/agent/dropbox-beethoven-core-integrity-audit-merge-safet-slice-2/1788984556` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 3 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/dropbox-beethoven-fleet-immune-system-throughput-accelerators-operat-2-machine-pipeline-heartbeat-alerts-p0-recovered/1786051640` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 4 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/dropbox-beethoven-fleet-immune-system-throughput-accelerators-operat-2-machine-pipeline-heartbeat-alerts-p0/1786092336` | RECOVERABLE_VALUE | 0 | 13 unique commit(s) touching 28 file(s) not on origin/main. NO remote branch pre |
| `refs/archive/agent/dropbox-beethoven-fleet-immune-system-throughput-accelerators-operat-3-speed-triage-routing-accelerators-p0/1786122053` | RECOVERABLE_VALUE | 0 | 14 unique commit(s) touching 31 file(s) not on origin/main. NO remote branch pre |
| `refs/archive/agent/dropbox-beethoven-fleet-immune-system-throughput-accelerators-operat-contracts-c/1786587348` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 11 file(s) not on origin/main. NO remote branch pres |
| `refs/archive/agent/dropbox-beethoven-fleet-immune-system-throughput-accelerators-operat-contracts-c/1786590568` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 5 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/dropbox-beethoven-fleet-immune-system-throughput-accelerators-operat-contracts/1786026468` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 4 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/dropbox-beethoven-fleet-immune-system-throughput-accelerators-operat-proofs/1786121965` | RECOVERABLE_VALUE | 0 | 15 unique commit(s) touching 32 file(s) not on origin/main. NO remote branch pre |
| `refs/archive/agent/dropbox-hisanta-mastery-engine-grandma-rail-family-slice-1/1786113250` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 7 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/dropbox-hisanta-mastery-engine-grandma-rail-family-slice-2/1786113209` | RECOVERABLE_VALUE | 0 | 3 unique commit(s) touching 19 file(s) not on origin/main. NO remote branch pres |
| `refs/archive/agent/dropbox-hisanta-mastery-engine-grandma-rail-family-slice-3/1786121566` | RECOVERABLE_VALUE | 0 | 3 unique commit(s) touching 16 file(s) not on origin/main. NO remote branch pres |
| `refs/archive/agent/dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-batch-fusion-unpause/1786114419` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-billing-guard-scope/1786113195` | RECOVERABLE_VALUE | 0 | 21 unique commit(s) touching 43 file(s) not on origin/main. NO remote branch pre |
| `refs/archive/agent/dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-bulk-integrate-shelf/1786087699` | RECOVERABLE_VALUE | 0 | 25 unique commit(s) touching 48 file(s) not on origin/main. NO remote branch pre |
| `refs/archive/agent/dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-governor-ram-floor/1786033856` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/dropbox-pareto-life-goal-autonomy-stack-p4-household-legal-doc-updater-notificat/1786088230` | RECOVERABLE_VALUE | 0 | 5 unique commit(s) touching 23 file(s) not on origin/main. NO remote branch pres |
| `refs/archive/agent/dropbox-pareto-life-goal-autonomy-stack-p4-household-legal-regime-consumer-with-/1786055409` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 6 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/dropbox-prompt-merged-diff-memory-system-task-spec-slice-5/1786463324` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/dropbox-recover-the-lease-night-stash-work-branch-hotfix-stash-rescu-group-2-recovered/1786043555` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/dropbox-recover-the-lease-night-stash-work-branch-hotfix-stash-rescu-group-2/1786092027` | RECOVERABLE_VALUE | 0 | 11 unique commit(s) touching 21 file(s) not on origin/main. NO remote branch pre |
| `refs/archive/agent/dropbox-recover-the-lease-night-stash-work-branch-hotfix-stash-rescu-group-3/1786026460` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 3 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/dropbox-recover-the-lease-night-stash-work-branch-hotfix-stash-rescu-group-4/1786092779` | RECOVERABLE_VALUE | 0 | 16 unique commit(s) touching 35 file(s) not on origin/main. NO remote branch pre |
| `refs/archive/agent/dropbox-recover-the-lease-night-stash-work-branch-hotfix-stash-rescu-group-5/1786092665` | RECOVERABLE_VALUE | 0 | 15 unique commit(s) touching 34 file(s) not on origin/main. NO remote branch pre |
| `refs/archive/agent/dropbox-wave-c-compounding-codegen-platform-spine--slice-1-define-core-types-cre/1786468526` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/dropbox-wave-c-compounding-codegen-platform-spine--slice-1-define-core-types-cre/1786569521` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/dropbox-wave-c-compounding-codegen-platform-spine--slice-1-define-core-types-def/1786468688` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 3 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/dropbox-wave-c-compounding-codegen-platform-spine--slice-1-define-core-types-def/1786569720` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 9 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/dropbox-wave-c-compounding-codegen-platform-spine--slice-1-recovered/1786042221` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 5 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/dropbox-wave-c-compounding-codegen-platform-spine--slice-2-reuse-project-helpers/1786468022` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/dropbox-wave-c-compounding-codegen-platform-spine--slice-2/1786023291` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 4 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/dropbox-wave-c-compounding-codegen-platform-spine--slice-3/1786023294` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 4 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/dropbox-wave-c-compounding-codegen-platform-spine--slice-3/1786033426` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 4 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/dropbox-wave-c-compounding-codegen-platform-spine--slice-3/1786052437` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 4 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/dropbox-wave-c-compounding-codegen-platform-spine--slice-4/1786023296` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 3 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/dropbox-wave-c-compounding-codegen-platform-spine--slice-5-refactor-passport-dar/1786465504` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/dropbox-wave-c-compounding-codegen-platform-spine--slice-5-update-passport-tests/1786467114` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/dropbox-wave-c-compounding-codegen-platform-spine--slice-5-update-passport-tests/1786577496` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/dropbox-wave-c-compounding-codegen-platform-spine--slice-5/1786023299` | RECOVERABLE_VALUE | 0 | 3 unique commit(s) touching 6 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/factory-unblock-improve-immediate-auto-merge-on-te-slice-4-fix-compilation-types/1786922331` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 29 file(s) not on origin/main. NO remote branch pres |
| `refs/archive/agent/fix-canonical-enqueue-trigger-regression-20260812/1786571450` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 3 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/improve-compliance-scheduling-observability/1786928196` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 6 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/improve-immediate-auto-merge-on-test-pass-low-r-slice-3-switch-scheduling-from-h/1786923033` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 4 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/improve-implement-real-time-sync-between-web-and-slice-2-integrate-real-time-syn/1786573575` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 3 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/improve-missing-branch-auto-recovery-fleet-wide-slice-3-validate-repository/1786122621` | RECOVERABLE_VALUE | 0 | 19 unique commit(s) touching 40 file(s) not on origin/main. NO remote branch pre |
| `refs/archive/agent/improve-optimize-ci-cd-pipeline-slice-1/1788482170` | RECOVERABLE_VALUE | 0 | 12 unique commit(s) touching 57 file(s) not on origin/main. NO remote branch pre |
| `refs/archive/agent/improve-optimize-task-queue-processing-slice-5/1789003897` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 1 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/improve-queue-dirty-checkout-auto-recovery/1786571386` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/improve-queue-prevent-darwin-passport-conflicts/1786570488` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 4 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/improve-queue-prevent-live-runner-merge-conflicts/1786570526` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/improve-queue-prevent-live-runner-merge-conflicts/1786574511` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 3 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/improve-release-deploy-ui-evidence-closure/1786573297` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/improve-runner-credential-capacity-failover/1786570436` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 3 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/improve-runner-credential-capacity-failover/1786574426` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 3 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/improve-runner-supervisor-single-owner/1786573243` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 3 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/improve-runner-supervisor-single-owner/1786592640` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 3 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/recover-bridge-artifact-operator-output-truth-session-fabric/1786922367` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 8 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/recover-stranded-agent-branches-cowork-20260806-slice-4/1786572994` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/recover-stranded-agent-branches-cowork-20260806-slice-4/1788968389` | RECOVERABLE_VALUE | 0 | 3 unique commit(s) touching 9 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/relfix-beethoven-299c6b3c3bc6-recovered/1786109957` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 69 file(s) not on origin/main. NO remote branch pres |
| `refs/archive/agent/relfix-beethoven-299c6b3c3bc6-recovered/1786570632` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 186 file(s) not on origin/main. NO remote branch pre |
| `refs/archive/agent/relfix-pinned-claim-escape-pr-22/1786570783` | RECOVERABLE_VALUE | 0 | 2 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/relfix-pinned-claim-escape-pr-22/1786587432` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/remediate-dropbox-wave-c-compounding-codegen-platform-spine--ca8794/1786587823` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 2 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/agent/repair-childless-decompositions-blocking-operator-queue/1789011133` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 7 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/origin/agent/chatgpt-local-reconcile-beethoven-ee86a2cff698/1788928744` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 4 file(s) not on origin/main. NO remote branch prese |
| `refs/archive/origin/agent/cont-5f9e0e/1788928764` | RECOVERABLE_VALUE | 0 | 175 unique commit(s) touching 844 file(s) not on origin/main. NO remote branch p |
| `refs/archive/origin/agent/rework-secret-tax-return-optimization-cc57fda/1788928832` | RECOVERABLE_VALUE | 0 | 192 unique commit(s) touching 865 file(s) not on origin/main. NO remote branch p |
| `refs/archive/origin/agent/runner-heartbeat-fix/1788928837` | RECOVERABLE_VALUE | 0 | 1 unique commit(s) touching 3 file(s) not on origin/main. NO remote branch prese |
| `stash@{1}` | RECOVERABLE_VALUE | 0 | On master: other agent's work, set aside for 65a2caba promotion |
| `stash@{3}` | RECOVERABLE_VALUE | 0 | On master: other agent's work, set aside for f9ffdc45 promotion |
| `stash@{5}` | RECOVERABLE_VALUE | 0 | WIP on agent/canary-deepseek-1-conftest-restore: 6cec1792 Merge branch 'agent/im |
| `stash@{8}` | RECOVERABLE_VALUE | 0 | On master: strays-2159 |
| `stash@{9}` | RECOVERABLE_VALUE | 0 | On master: strays-20260901-2140 |

## Notes

- `ACTIVE_IN_ANOTHER_TASK` items are already carried by a live `agent/*` branch; re-applying them here would duplicate queued work.
- `SUPERSEDED_BY_NEWER` is decided by commit time on the base for every source file the rescue commit touches — the newest/most complete implementation wins.
- Refs whose only content is generated (`node_modules`, `.vite`, `.nuxt`, `dist`, `coverage`, …) are classified `ALREADY_PRESENT`: a vitest cache is build noise, not lost work, and must not spawn a follow-up task that can never produce a meaningful diff.
