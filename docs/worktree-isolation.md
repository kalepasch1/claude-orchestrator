# Worktree Isolation Convention

All executor task work happens in isolated git worktrees, never in the main repo checkout.

## Why

The main checkout (`{repo_path}`) is shared by multiple executors, the runner, and sentinel.py. Checking out branches in the main repo causes conflicts, stash collisions, and sentinel resets.

## Convention

```
{repo_path}-wt/{slug}/    ← isolated worktree per task
```

Example:
```
/Users/dev/beethoven/claude-orchestrator-wt/canary-gpt-51/
```

## Lifecycle

1. **Create**: `git worktree add --force "$WT" -B agent/{slug} origin/{base}`
2. **Work**: All file edits, commits happen inside `$WT`
3. **Push**: `git push origin HEAD:agent/{slug} --force`
4. **Cleanup**: `git worktree remove --force "$WT"` — the branch survives on the remote

## Rules

- Never run `git checkout` or `git stash` in `{repo_path}`
- Always `git worktree prune` before creating new worktrees
- If creation fails due to stale lock, prune and retry
