# Worktree Isolation Policy

All executor task implementations MUST use isolated git worktrees.
Never checkout branches or run `git stash` in the main repo directory.

## Why worktrees?

- **Prevents interference:** Multiple tasks can run against the same repo
  without stepping on each other's branch state.
- **Atomic cleanup:** If a task fails mid-implementation, removing the
  worktree leaves the main repo untouched.
- **No stash conflicts:** `git stash` in the main repo risks data loss
  when multiple processes compete for the stash stack.

## Worktree lifecycle

1. `git worktree prune` — clean up stale entries from prior crashes
2. `git worktree add --force "$WT" -B agent/{slug} origin/{base}` — create
3. Implement, commit, push inside `$WT`
4. `git worktree remove --force "$WT"` — the branch survives on the remote

## Failure recovery

If worktree creation fails because a branch is already checked out in a
stale worktree, run `git worktree prune` then retry. If a `.lock` file
blocks pruning, remove it manually before retrying.
