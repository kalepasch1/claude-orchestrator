# Worktree Isolation Guide

All executor task work happens in isolated git worktrees, never in the main
checkout. This prevents branch-switching conflicts between concurrent executors,
the runner, and sentinel.py.

## Convention

Worktrees are created at `{repo}-wt/{slug}` adjacent to the main repo directory.

```
~/Documents/beethoven/claude-orchestrator/       # main checkout (master)
~/Documents/beethoven/claude-orchestrator-wt/     # worktree container
  canary-gpt-48/                                  # one worktree per task
  bugfix-runner-lock/                             # another task
```

## Lifecycle

1. **Create**: `git worktree add --force "$WT" -B agent/{slug} origin/{base}`
2. **Work**: all file edits happen inside `$WT`
3. **Commit**: `git add -A && git commit` inside `$WT`
4. **Push**: `git push origin HEAD:agent/{slug} --force`
5. **Remove**: `git worktree remove --force "$WT"` (branch survives on remote)

## Rules

- Never run `git checkout` or `git stash` in the main repo directory.
- Always run `git worktree prune` before creating new worktrees.
- If worktree creation fails due to a locked branch, prune stale entries first.
- sentinel.py will stash+reset any non-base checkout it finds in the main repo.
