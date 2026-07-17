# Worktree Isolation Pattern

## Why Worktrees
The executor never checks out branches in the main repo clone.
All task work happens in a temporary git worktree so that:
- Multiple tasks can run concurrently without branch conflicts.
- The main repo stays on its default branch at all times.
- A crashed task cannot leave the main repo in a dirty state.

## Lifecycle
1. `git worktree add --force <path> -B agent/<slug> origin/<base>` — create isolated copy.
2. Implement, commit inside the worktree.
3. `git push origin HEAD:agent/<slug> --force` — publish the branch.
4. `git worktree remove --force <path>` — clean up; the branch survives on the remote.

## Lock File Recovery
If a prior crash left `.lock` files, `git worktree prune` plus manual
lock-file removal is required before creating new worktrees.
