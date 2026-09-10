# Dirty-worktree reconciliation — beethoven

Audit fingerprint: `a8452a1f6114b1e0d3e0f8ba0e78e46b2e0e1e03d0a83f5c2e4b8e2f19a3c7d61`

Base: `origin/master` @ `bcacf428ecb1` · generated 2026-09-10T05:03:04.368Z

Regenerate with:

```bash
node scripts/reconcile-dirty-worktrees.mjs \
  --base origin/master \
  --fingerprint a8452a1f6114b1e0d3e0f8ba0e78e46b2e0e1e03d0a83f5c2e4b8e2f19a3c7d61 \
  --json /tmp/dirty-owned.json
```

## Result

**95 worktrees classified, 0 UNKNOWN.** **767 uncommitted path(s) exist only on this disk** — no branch, no rescue ref and no remote carries them. Nothing was popped, dropped, reset or moved.

| Classification | Worktrees |
|---|---:|
| RECOVERABLE_VALUE | 7 |
| ALREADY_PRESENT | 68 |
| ACTIVE_IN_ANOTHER_TASK | 13 |
| CONFLICTED_NEEDS_FOCUSED_TASK | 7 |

## Worktrees holding the only copy, with no live task to claim it

| Worktree | Branch | Unique | Dirty |
|---|---|---:|---:|
| `/Users/kpasch/Documents/beethoven/claude-orchestrator/.runtime/integration-worktrees/5bee398fbf584c3252b3` | DETACHED | 705 | 2238 |
| `/Users/kpasch/Documents/beethoven/claude-orchestrator` | refs/heads/master | 22 | 22 |
| `/Users/kpasch/Documents/Codex/2026-08-07/cons/work/orchestrator-session-fabric-current` | refs/heads/codex/orchestrator-session-fabric | 18 | 18 |
| `/Users/kpasch/Documents/Codex/2026-08-06/figu/work/orchestrator-visibility-remediation` | refs/heads/codex/operator-visibility-remediation | 16 | 17 |
| `/Users/kpasch/Documents/beethoven/claude-orchestrator-wt/backlog-batch-beethoven-22ee5bc-convention-conform-slice-2 8309febb` | DETACHED | 2 | 2 |
| `/Users/kpasch/Documents/beethoven/claude-orchestrator-wt/backlog-batch-beethoven-22ee5bc-prompt-evolution-bandit-update-claude-interface 67280171` | DETACHED | 2 | 2 |
| `/Users/kpasch/Documents/beethoven/claude-orchestrator-wt/canary-claude-27-slice-3-adapt-prior-merged-patterns-extract-proven-diffs-extrac 15227eb7` | DETACHED | 2 | 2 |

## Dirty, but another live task owns it — do not touch

13 worktree(s), 20 uncommitted path(s). These are open tasks mid-edit, not lost work. Carrying their edits onto a second branch is the duplication the coordination rule exists to prevent.

| Worktree | Owned by | Unique |
|---|---|---:|
| `/Users/kpasch/Documents/beethoven/claude-orchestrator-wt/canary-deepseek-1` | `agent/canary-deepseek-1` | 5 |
| `/Users/kpasch/Documents/beethoven/claude-orchestrator-wt/canary-self-deploy-live-slice-1` | `agent/canary-self-deploy-live-slice-1` | 3 |
| `/Users/kpasch/Documents/beethoven/claude-orchestrator-wt/chatgpt-local-reconcile-beethoven-a8452a1f6114` | `agent/chatgpt-local-reconcile-beethoven-a8452a1f6114` | 2 |
| `/Users/kpasch/Documents/beethoven/claude-orchestrator-wt/chatgpt-local-reconcile-beethoven-2829958769f3` | `agent/chatgpt-local-reconcile-beethoven-2829958769f3` | 1 |
| `/Users/kpasch/Documents/beethoven/claude-orchestrator-wt/chatgpt-local-reconcile-beethoven-91e42592f158` | `agent/chatgpt-local-reconcile-beethoven-91e42592f158` | 1 |
| `/Users/kpasch/Documents/beethoven/claude-orchestrator-wt/chatgpt-local-reconcile-beethoven-c870b59c7ec8` | `agent/chatgpt-local-reconcile-beethoven-c870b59c7ec8` | 1 |
| `/Users/kpasch/Documents/beethoven/claude-orchestrator-wt/chatgpt-local-reconcile-beethoven-f7b45f3f90ad` | `agent/chatgpt-local-reconcile-beethoven-f7b45f3f90ad` | 1 |
| `/Users/kpasch/Documents/beethoven/claude-orchestrator-wt/improve-enhance-branch-management-with-automated-r-slice-2` | `agent/improve-enhance-branch-management-with-automated-r-slice-2` | 1 |
| `/Users/kpasch/Documents/beethoven/claude-orchestrator-wt/improve-enhance-test-automation-for-ci-cd-pipeli-slice-5` | `agent/improve-enhance-test-automation-for-ci-cd-pipeli-slice-5` | 1 |
| `/Users/kpasch/Documents/beethoven/claude-orchestrator-wt/improve-enhanced-testing-pipeline-fix-source-confi-slice-4` | `agent/improve-enhanced-testing-pipeline-fix-source-confi-slice-4` | 1 |
| `/Users/kpasch/Documents/beethoven/claude-orchestrator-wt/improve-enhanced-testing-pipeline-inspect-local-br-slice-2` | `agent/improve-enhanced-testing-pipeline-inspect-local-br-slice-2` | 1 |
| `/Users/kpasch/Documents/beethoven/claude-orchestrator-wt/improve-implement-real-time-queue-state-update-slice-5` | `agent/improve-implement-real-time-queue-state-update-slice-5` | 1 |
| `/Users/kpasch/Documents/beethoven/claude-orchestrator-wt/rework-legal-cont-batch-darwn-277f0bd-9657042` | `agent/rework-legal-cont-batch-darwn-277f0bd-9657042` | 1 |

## Unreadable — unknown is not "fine"

- `/Users/kpasch/Documents/beethoven/claude-orchestrator/.runtime/integration-worktrees/5bee398fbf584c3252b3-run-11848-1788883528475544000`
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

