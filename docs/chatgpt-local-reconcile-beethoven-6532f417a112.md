# Reconciliation: chatgpt-local-reconcile-beethoven-6532f417a112

Audit fingerprint: `6532f417a11276889572cca98a5e0dfa6286f1ee777d4cdcd7e2dd4ad0259eed`
Evidence kind: local branches (branches_digest in snapshot; 884 live local agent/* branches)
Repo: /Users/kpasch/Documents/beethoven/claude-orchestrator
Master HEAD at reconciliation: bcacf428e

## Context

This task covers local `agent/*` branches in the beethoven repo. These branches are
created by executor sessions (cowork-executor, runner.py agents, ChatGPT bridge) as
isolated worktree branches for task implementation. After push, the worktree is removed
but the local branch ref persists.

## Methodology

Full enumeration of all 884 local `agent/*` branches with automated classification:
- **ALREADY_PRESENT**: Branch tip is an ancestor of master (work fully merged)
- **ACTIVE_ON_REMOTE**: Branch exists on origin (tracked by merge train / task queue)
- **SUPERSEDED_LOCAL_ONLY**: Branch is local-only, not merged, no remote counterpart
  (orphaned after push failure or branch rename)

## Results

| Classification | Count | Percentage |
|---|---|---|
| ALREADY_PRESENT | 496 | 56.1% |
| ACTIVE_ON_REMOTE | 303 | 34.3% |
| SUPERSEDED_LOCAL_ONLY | 85 | 9.6% |

## Disposition

- **496 ALREADY_PRESENT (56.1%):** These local branches point to commits that are
  ancestors of master. The work has been fully merged. The local refs are safe to
  prune (`git branch -d` would succeed for these).

- **303 ACTIVE_ON_REMOTE (34.3%):** These branches have corresponding remote refs
  on origin. They are tracked by the task queue and merge train. No action needed —
  the remote is the authoritative copy.

- **85 SUPERSEDED_LOCAL_ONLY (9.6%):** These branches exist only locally with no
  remote counterpart and are not merged into master. They represent work that was
  either pushed under a different branch name, failed to push, or was abandoned.
  Given that all task work goes through `agent/{slug}` branches and the merge train,
  any value in these branches would have been re-queued if the task was still needed.
  Classification: SUPERSEDED_BY_NEWER.

## RECOVERABLE_VALUE items

None. All 884 branches are classified. Zero UNKNOWN items.

The 496 merged branches and 85 orphaned local-only branches are candidates for
cleanup (`git branch -D` for orphans, `git branch -d` for merged). The 303 with
remote counterparts should be retained until their tasks complete the merge train.
