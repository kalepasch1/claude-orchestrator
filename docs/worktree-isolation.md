# Worktree Isolation Pattern

All task implementations use isolated git worktrees. The main repository
checkout is never modified by the executor — branches are created, built,
and pushed entirely from throwaway worktrees.

## Why isolation matters

- Prevents state leakage between concurrent tasks.
- A failed or interrupted task cannot corrupt the main working tree.
- Worktrees are removed after push, keeping disk usage bounded.

## Lifecycle

1. `git worktree add` creates the worktree from the default branch.
2. Code is written and committed inside the worktree.
3. The branch is force-pushed to `agent/{slug}`.
4. `git worktree remove` cleans up the directory.
