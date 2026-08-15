# Recovery ledger — beethoven — dirty/broken worktrees + bridge artifacts

- audit fingerprint: `71a638adb6ea028ddb01ad932b2f6c8d65f985744cbcffd78ae726ca0b5adc09`
- base: `origin/master`
- evidence items classified: **27**
- UNKNOWN remaining: **0**

Every rescue ref was treated as read-only. No ref, stash or worktree
was deleted, reset, cleaned, popped or moved by this reconciliation.

## Classification summary

| classification | count |
| --- | ---: |
| RECOVERABLE_VALUE | 9 |
| CONFLICTED_NEEDS_FOCUSED_TASK | 1 |
| ALREADY_PRESENT | 17 |

## Items needing follow-up

| ref | sha | class | files | disposition |
| --- | --- | --- | ---: | --- |
| `/Users/kpasch/Documents/beethoven/claude-orchestrator` | `371ac7f487` | RECOVERABLE_VALUE | 339 | 339 untracked new file(s) with no tracked counterpart; review and land through an agent branch. Source left untouched. |
| `/Users/kpasch/Documents/beethoven/claude-orchestrator-wt/backlog-batch-beethoven-22ee5bc-convention-conform-slice-2 8309febb` | `1eda33098a` | RECOVERABLE_VALUE | 2 | 2 uncommitted path(s); tracked diff applies to base. Recover via a new isolated worktree + agent branch. Source worktree left untouched. |
| `/Users/kpasch/Documents/beethoven/claude-orchestrator-wt/backlog-batch-beethoven-22ee5bc-prompt-evolution-bandit-update-claude-interface 67280171` | `76d068867d` | RECOVERABLE_VALUE | 2 | 2 uncommitted path(s); tracked diff applies to base. Recover via a new isolated worktree + agent branch. Source worktree left untouched. |
| `/Users/kpasch/Documents/beethoven/claude-orchestrator-wt/canary-claude-27-slice-3-adapt-prior-merged-patterns-extract-proven-diffs-extrac 15227eb7` | `ba57d64f0f` | RECOVERABLE_VALUE | 2 | 2 uncommitted path(s); tracked diff applies to base. Recover via a new isolated worktree + agent branch. Source worktree left untouched. |
| `/Users/kpasch/Documents/beethoven/claude-orchestrator-wt/never-again-lane-daemon` | `9a14f09438` | RECOVERABLE_VALUE | 9 | 9 uncommitted path(s); tracked diff applies to base. Recover via a new isolated worktree + agent branch. Source worktree left untouched. |
| `/Users/kpasch/Documents/beethoven/claude-orchestrator-wt/spine-types-x2` | `987e5280e7` | RECOVERABLE_VALUE | 1 | 1 untracked new file(s) with no tracked counterpart; review and land through an agent branch. Source left untouched. |
| `/Users/kpasch/Documents/Codex/2026-08-06/figu/work/orchestrator-visibility-remediation` | `fbb735b3cf` | RECOVERABLE_VALUE | 17 | 17 uncommitted path(s); tracked diff applies to base. Recover via a new isolated worktree + agent branch. Source worktree left untouched. |
| `/Users/kpasch/Documents/Codex/2026-08-07/cons/work/orchestrator-session-fabric-current` | `59de85f238` | RECOVERABLE_VALUE | 18 | 18 uncommitted path(s); tracked diff applies to base. Recover via a new isolated worktree + agent branch. Source worktree left untouched. |
| `/Users/kpasch/Documents/chatgpt-dropbox/_applied/20260812-020326--claude-orchestrator--operator-output-truth-session-fabric-20260812.patch` | `889cdfd161` | RECOVERABLE_VALUE | 18 | bridge marked this applied, but the patch still applies to origin/master -- the change never reached the default branch. Recover through an agent branch. |
| `/Users/kpasch/Documents/chatgpt-dropbox/_failed/20260807-085521--smarter--apparently-framework-merge.patch` | `6b8f95f50a` | CONFLICTED_NEEDS_FOCUSED_TASK | 68 | failed bridge artifact whose patch no longer applies; queue a focused follow-up rather than forcing an overwrite |

## Disposition rules applied

- `ALREADY_PRESENT` — reachable from base, patch-identical to base, or an
  empty sweep commit. No action.
- `SUPERSEDED_BY_NEWER` — every touched path was rewritten in base after the
  ref was cut. Newest implementation wins; no action.
- `ACTIVE_IN_ANOTHER_TASK` — the commit is contained in a live `agent/*`
  branch. Left to that task; not duplicated here.
- `RECOVERABLE_VALUE` — diff still applies. Recover through an isolated
  worktree and the normal agent-branch + merge-train path.
- `CONFLICTED_NEEDS_FOCUSED_TASK` — diff no longer applies. A focused
  follow-up is queued instead of forcing an overwrite.
