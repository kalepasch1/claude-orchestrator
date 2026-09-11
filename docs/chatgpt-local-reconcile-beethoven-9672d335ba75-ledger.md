# Recovery Ledger — chatgpt-local-reconcile-beethoven-9672d335ba75

Audit fingerprint: `9672d335ba75374845094e42a20b3cf2a86ab5f8ae9c97a4a3aa3b23899fd620`
Generated: 2026-09-11T17:53:28Z

## Evidence Classification

### Dirty Worktrees (6 items)

| # | Source | Branch | Classification | Disposition |
|---|---|---|---|---|
| 1 | dirty_worktree: `…-wt/improve-automate-error-handling-with-machine-lea-slice-4` | `agent/improve-automate-error-handling-with-machine-lea-slice-4` | ALREADY_PRESENT | Branch merged into master; only change is `.orch-worktree.json` (metadata). No recoverable value. |
| 2 | dirty_worktree: `…-wt/improve-implement-advanced-task-prioritization-slice-5` | `agent/improve-implement-advanced-task-prioritization-slice-5` | ALREADY_PRESENT | Branch merged into master; only change is `.orch-worktree.json` (metadata). No recoverable value. |
| 3 | dirty_worktree: `…-wt/improve-optimize-database-operations-for-configu-slice-4` | `agent/improve-optimize-database-operations-for-configu-slice-4` | ALREADY_PRESENT | Branch merged into master; only change is `.orch-worktree.json` (metadata). No recoverable value. |
| 4 | dirty_worktree: `…-wt/rework-legal-…-bcc4787` | `agent/rework-legal-rework-legal-rework-noop-reroute-model-keys-mock-d63464f-7a-bcc4787` | ALREADY_PRESENT | Branch merged into master; only change is `.orch-worktree.json` (metadata). No recoverable value. |
| 5 | dirty_worktree: `.runtime/integration-worktrees/5bee398fbf584c3252b3-run-17138-1788950452240178000` | DETACHED | SUPERSEDED_BY_NEWER | Files `web/types/log.js`, `web/utils/cookie-compat.js` were intentionally removed in `d63e93da1` (drop compiled .js shadowing .ts sources). No recoverable value. |
| 6 | dirty_worktree: `.runtime/integration-worktrees/5bee398fbf584c3252b3-run-39102-1788947783906985000` | DETACHED | SUPERSEDED_BY_NEWER | Files `web/types/log.js`, `web/utils/cookie-compat.js` were intentionally removed in `d63e93da1` (drop compiled .js shadowing .ts sources). No recoverable value. |

### orch-rescue Refs (667 in snapshot, 791 live)

All refs are periodic sweep snapshots from 2026-08-03. Classified by checking whether each SHA is reachable from master.

| Classification | Count | Disposition |
|---|---|---|
| ALREADY_PRESENT | 168 | SHA is in master's commit graph. Rescue snapshot is redundant. |
| SUPERSEDED_BY_NEWER | 623 | Branch was merged via squash/rebase (different SHA) or superseded by newer work. Rescue snapshot is archival only. |

All 791 refs remain read-only under `refs/orch-rescue/`; none were deleted, applied, or modified.

## Summary

- **0 UNKNOWN items** — every evidence item classified
- **0 RECOVERABLE_VALUE** — all dirty worktree branches already merged; integration worktree files intentionally removed; orch-rescue refs are archival snapshots
- **0 CONFLICTED_NEEDS_FOCUSED_TASK** — no conflicts found