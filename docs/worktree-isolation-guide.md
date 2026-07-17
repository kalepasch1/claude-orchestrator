# Worktree Isolation — Developer Guide

## Why Worktrees
Every task branch is built in an isolated `git worktree` so the main repo
checkout is never disturbed. This prevents branch-switching conflicts when
multiple tasks execute in parallel.

## Lifecycle

1. **Create** — `git worktree add --force <path> -B agent/<slug> <base>`
2. **Implement** — all file writes happen inside the worktree directory
3. **Commit & push** — `git push origin HEAD:agent/<slug> --force`
4. **Remove** — `git worktree remove --force <path>` (the remote branch survives)

## Common Issues

| Symptom | Fix |
|---|---|
| `fatal: '<branch>' is already checked out` | Run `git worktree prune` first, then retry |
| Worktree locked | `git worktree unlock <path>`, then remove |
| Stale worktrees accumulating | `resource_governor.prune()` cleans merged/stale trees automatically |

## Rules
- **Never** run `git checkout` or `git stash` in the main repo directory.
- **Always** `cd` into the worktree before any file operations.
- **Always** remove the worktree after pushing, even on failure.
