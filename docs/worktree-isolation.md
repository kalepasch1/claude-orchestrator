# Worktree Isolation Convention

All executor task work happens in isolated git worktrees, never in the
primary checkout. This prevents conflicts with other executors, the runner,
and sentinel.py (which stashes and resets non-base checkouts it detects).

## Layout

```
{repo_path}/                        # primary checkout — DO NOT modify
{repo_path}-wt/{slug}/              # per-task worktree
```

## Lifecycle

1. `git worktree add --force "$WT" -B agent/{slug} origin/{base_branch}`
2. Implement changes inside `$WT`
3. Commit and push from `$WT`
4. `git worktree remove --force "$WT"` — the branch survives on the remote

## Rules

- Never run `git checkout` or `git stash` in the primary checkout.
- If worktree creation fails due to a stale lock, run `git worktree prune` first.
- Always remove the worktree after push to prevent `-wt` directory accumulation.
