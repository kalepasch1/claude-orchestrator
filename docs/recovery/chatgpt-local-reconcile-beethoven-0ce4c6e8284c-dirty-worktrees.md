# Dirty-worktree reconciliation — beethoven

Audit fingerprint: `0ce4c6e8284c4155d1188f39e5090d874ef75a139d7b3111a311f701c35d841e`

Base: `origin/master` @ `bcacf428ecb1` · generated 2026-09-10T04:57:12.497Z

Regenerate with:

```bash
node scripts/reconcile-dirty-worktrees.mjs \
  --base origin/master \
  --fingerprint 0ce4c6e8284c4155d1188f39e5090d874ef75a139d7b3111a311f701c35d841e \
  --json docs/recovery/chatgpt-local-reconcile-beethoven-0ce4c6e8284c-dirty-worktrees.json
```

## Result

**95 worktrees classified, 0 UNKNOWN.** **787 uncommitted path(s) exist only on this disk** — no branch, no rescue ref and no remote carries them. Nothing was popped, dropped, reset or moved.

| Classification | Worktrees |
|---|---:|
| RECOVERABLE_VALUE | 20 |
| ALREADY_PRESENT | 67 |
| CONFLICTED_NEEDS_FOCUSED_TASK | 8 |

## Worktrees holding the only copy

| Worktree | Branch | Unique | Dirty |
|---|---|---:|---:|
| `/Users/kpasch/Documents/beethoven/claude-orchestrator/.runtime/integration-worktrees/5bee398fbf584c3252b3` | DETACHED | 705 | 2238 |
| `/Users/kpasch/Documents/beethoven/claude-orchestrator` | refs/heads/master | 22 | 22 |
| `/Users/kpasch/Documents/Codex/2026-08-07/cons/work/orchestrator-session-fabric-current` | refs/heads/codex/orchestrator-session-fabric | 18 | 18 |
| `/Users/kpasch/Documents/Codex/2026-08-06/figu/work/orchestrator-visibility-remediation` | refs/heads/codex/operator-visibility-remediation | 16 | 17 |
| `/Users/kpasch/Documents/beethoven/claude-orchestrator-wt/canary-deepseek-1` | refs/heads/agent/canary-deepseek-1 | 5 | 6 |
| `/Users/kpasch/Documents/beethoven/claude-orchestrator-wt/canary-self-deploy-live-slice-1` | refs/heads/agent/canary-self-deploy-live-slice-1 | 3 | 4 |
| `/Users/kpasch/Documents/beethoven/claude-orchestrator-wt/backlog-batch-beethoven-22ee5bc-convention-conform-slice-2 8309febb` | DETACHED | 2 | 2 |
| `/Users/kpasch/Documents/beethoven/claude-orchestrator-wt/backlog-batch-beethoven-22ee5bc-prompt-evolution-bandit-update-claude-interface 67280171` | DETACHED | 2 | 2 |
| `/Users/kpasch/Documents/beethoven/claude-orchestrator-wt/canary-claude-27-slice-3-adapt-prior-merged-patterns-extract-proven-diffs-extrac 15227eb7` | DETACHED | 2 | 2 |
| `/Users/kpasch/Documents/beethoven/claude-orchestrator-wt/chatgpt-local-reconcile-beethoven-0ce4c6e8284c` | refs/heads/agent/chatgpt-local-reconcile-beethoven-0ce4c6e8284c | 2 | 2 |
| `/Users/kpasch/Documents/beethoven/claude-orchestrator-wt/chatgpt-local-reconcile-beethoven-2829958769f3` | refs/heads/agent/chatgpt-local-reconcile-beethoven-2829958769f3 | 1 | 1 |
| `/Users/kpasch/Documents/beethoven/claude-orchestrator-wt/chatgpt-local-reconcile-beethoven-91e42592f158` | refs/heads/agent/chatgpt-local-reconcile-beethoven-91e42592f158 | 1 | 1 |
| `/Users/kpasch/Documents/beethoven/claude-orchestrator-wt/chatgpt-local-reconcile-beethoven-c870b59c7ec8` | refs/heads/agent/chatgpt-local-reconcile-beethoven-c870b59c7ec8 | 1 | 1 |
| `/Users/kpasch/Documents/beethoven/claude-orchestrator-wt/chatgpt-local-reconcile-beethoven-f7b45f3f90ad` | refs/heads/agent/chatgpt-local-reconcile-beethoven-f7b45f3f90ad | 1 | 1 |
| `/Users/kpasch/Documents/beethoven/claude-orchestrator-wt/improve-enhance-branch-management-with-automated-r-slice-2` | refs/heads/agent/improve-enhance-branch-management-with-automated-r-slice-2 | 1 | 1 |
| `/Users/kpasch/Documents/beethoven/claude-orchestrator-wt/improve-enhance-test-automation-for-ci-cd-pipeli-slice-5` | refs/heads/agent/improve-enhance-test-automation-for-ci-cd-pipeli-slice-5 | 1 | 1 |
| `/Users/kpasch/Documents/beethoven/claude-orchestrator-wt/improve-enhanced-testing-pipeline-fix-source-confi-slice-4` | refs/heads/agent/improve-enhanced-testing-pipeline-fix-source-confi-slice-4 | 1 | 1 |
| `/Users/kpasch/Documents/beethoven/claude-orchestrator-wt/improve-enhanced-testing-pipeline-inspect-local-br-slice-2` | refs/heads/agent/improve-enhanced-testing-pipeline-inspect-local-br-slice-2 | 1 | 1 |
| `/Users/kpasch/Documents/beethoven/claude-orchestrator-wt/improve-implement-real-time-queue-state-update-slice-5` | refs/heads/agent/improve-implement-real-time-queue-state-update-slice-5 | 1 | 1 |
| `/Users/kpasch/Documents/beethoven/claude-orchestrator-wt/rework-legal-cont-batch-darwn-277f0bd-9657042` | refs/heads/agent/rework-legal-cont-batch-darwn-277f0bd-9657042 | 1 | 1 |

## Unreadable — unknown is not "fine"

- `/Users/kpasch/Documents/beethoven/claude-orchestrator/.runtime/integration-worktrees/5bee398fbf584c3252b3-run-11848-1788883528475544000`
- `/Users/kpasch/Documents/beethoven/claude-orchestrator/.runtime/integration-worktrees/5bee398fbf584c3252b3-run-21029-1789011128447381000`
- `/Users/kpasch/Documents/beethoven/claude-orchestrator/.runtime/integration-worktrees/5bee398fbf584c3252b3-run-32151-1788452851448094000`
- `/Users/kpasch/Documents/beethoven/claude-orchestrator/.runtime/integration-worktrees/5bee398fbf584c3252b3-run-52066-1788892819208861000`
- `/Users/kpasch/Documents/beethoven/claude-orchestrator/.runtime/integration-worktrees/5bee398fbf584c3252b3-run-52103-1788892389709540000`
- `/Users/kpasch/Documents/beethoven/claude-orchestrator/.runtime/integration-worktrees/5bee398fbf584c3252b3-run-66305-1788832658052891000`
- `/Users/kpasch/Documents/beethoven/claude-orchestrator/.runtime/integration-worktrees/5bee398fbf584c3252b3-run-92737-1788569735363546000`
- `/Users/kpasch/Documents/beethoven/claude-orchestrator/.runtime/integration-worktrees/5bee398fbf584c3252b3-run-95881-1788824413096639000`

## Why a separate pass

`reconcile-evidence.mjs` compares *committed* trees, on the correct principle that
a worktree is a checkout rather than a copy. That is why every worktree in its ledger
is ALREADY_PRESENT. Uncommitted work is the case with no ref behind it, and `status`
is not on that script's allowlist, so there the question cannot even be asked.

