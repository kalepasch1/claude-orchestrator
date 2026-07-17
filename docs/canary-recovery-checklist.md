# Recovery Branch Reconstruction Checklist

When a tested-but-not-integrated agent branch is missing from the remote,
follow this minimal-patch recovery procedure:

1. **Check cache/transplant context** — look for prior diffs in the task
   record's `note`, `reuse_notes`, or `PATCH TRANSPLANT` field before
   drafting from scratch.

2. **Create the branch from base** — `git worktree add` from the project's
   `default_base` (usually `main` or `master`).

3. **Apply the smallest equivalent patch** — adapt the prior diff to the
   current HEAD. Do not add new scope.

4. **Run the project build/tests** — ensure the patch doesn't break
   existing behavior.

5. **Push and let the merge train integrate** — push to
   `agent/<recovery-slug>` only; never push to main/master directly.

## Common Pitfalls

- **Similarity < 0.5**: The transplant may not apply cleanly. Manual
  adaptation is expected.
- **Stale worktrees**: Run `git worktree prune` before creating new ones.
- **Binary PATCH TEMPLATE stubs**: Quarantine these — they have no
  readable implementation intent.
