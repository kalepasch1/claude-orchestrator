# Worktree Isolation Convention

All executor task work happens in per-task git worktrees, never in the main
repo checkout. This prevents branch-switching conflicts between concurrent
executors, the runner, and `sentinel.py` (which stashes and resets any
non-base checkout it detects in the main repo).

## Directory layout

```
{repo_path}/                     # main checkout — stays on default branch
{repo_path}-wt/{slug}/           # per-task worktree
```

## Lifecycle

1. `git worktree add --force "$WT" -B agent/{slug} origin/{base}` creates it.
2. All file reads, writes, and commits happen inside `$WT`.
3. After push, `git worktree remove --force "$WT"` cleans up the directory.
4. The `agent/{slug}` branch survives removal and holds the pushed work.

## Why not checkout in the main repo?

`sentinel.py` monitors the main checkout and force-resets it to the default
branch if it detects a different branch checked out. Running `git checkout`
in the main repo races with sentinel and other executors, causing lost work.
