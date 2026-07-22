# Worktree GC — Environment Variables

Quick reference for tunable knobs in `runner/worktree_gc.py`.

| Variable | Default | Purpose |
|---|---|---|
| `WORKTREE_GC_GIT_TIMEOUT` | `90` (seconds) | Timeout for each git subprocess invocation during GC |
| `WORKTREE_GC_MIN_AGE_MIN` | `180` (minutes) | Minimum age before a worktree is eligible for cleanup |
| `ORCH_SHARE_AGENT_BRANCHES` | `true` | Push agent branches to origin before removing the worktree |

## Fail-closed behavior

- If the task DB is unreachable, GC is skipped entirely (no worktrees are removed).
- If a worktree has uncommitted changes, it is never removed.
- If a worktree was active within `MIN_AGE_MIN`, it is never removed.
- Only worktrees on `agent/*` branches whose task is in a terminal state are candidates.
