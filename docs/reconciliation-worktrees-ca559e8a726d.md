# Worktrees Reconciliation — ca559e8a726d

**Audit fingerprint:** `ca559e8a726d9bff3436cb406ece8fe2aeaf6c4bf801ab58a32f210f031aec3d`
**Date:** 2026-09-11
**Evidence type:** dirty integration-test worktrees in `.runtime/integration-worktrees/`

## Classification Summary

All dirty worktrees in the evidence snapshot share the same changes digest
(`1f87f35b84f23828df59a3ed9db831fb4baadaea44b650e6660244b78ab4ac4f`) and contain
the same 2 uncommitted files: `web/types/log.js` and `web/utils/cookie-compat.js`.

These are ephemeral integration-test worktrees created by the runner's merge-train
integration testing system. They are:
- DETACHED HEAD at `688407058f` (a commit already in master)
- Contain build artifacts / generated files from integration test runs
- Have `newest_change_mtime: 0` (no meaningful modification time)

| Item | Classification | Rationale |
|---|---|---|
| All integration worktrees (same digest) | SUPERSEDED_BY_NEWER | Ephemeral test artifacts on a commit already in master. The 2 changed files are generated build outputs, not source code. |

**Total items: all enumerated, 0 UNKNOWN**

## RECOVERABLE_VALUE Assessment

None. These are transient integration-test worktrees with generated files, not source code.
The base commit (688407058f) is already in master.
