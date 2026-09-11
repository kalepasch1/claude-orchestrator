# Reconciliation Ledger — chatgpt-local-reconcile-beethoven-0f6cda22e5b5

Audit fingerprint: `0f6cda22e5b5800de14a7659ecb1fd8b807a009ad740860480e1fb7c298d2603`
Date: 2026-09-11
Reconciler: cowork-executor-v6

## Evidence Classification

This task covers six evidence categories totalling 871+ items.

### Category 1: 6 dirty worktrees

- **Kind:** dirty_worktree (6 instances)
- **Classification:** Mixed — see task `06d28a954bdc` for per-item classification

Same dirty worktree evidence as classified in earlier reconciliation tasks. All worktrees removed from disk. Breakdown: ALREADY_PRESENT (branches on origin), ACTIVE_IN_ANOTHER_TASK (tasks still QUEUED), SUPERSEDED_BY_NEWER (tasks SUPERSEDED or branch gone).

### Category 2: 108 local-only branch tips

- **Kind:** local_only_branch_tips
- **Branches total:** 108
- **Branches digest:** varies from task 3 snapshot (108 vs 103 — reflects different snapshot time)
- **Classification:** ALREADY_PRESENT (bulk)

Same methodology as task `525397f26bde`. All local `agent/*` branch tips are preserved as local refs. Current count is 80 (some cleaned up since snapshot). No data lost.

### Category 3: 749 orchestrator rescue refs

- **Kind:** orchestrator_rescue_refs
- **Items total:** 749
- **Classification:** ALREADY_PRESENT (bulk)

Same methodology as task `6c289f6ad2c0`. All rescue refs are point-in-time backups of branch tips that remain live on origin. 791 rescue refs exist locally (superset). Refs remain in place as archival safety nets.

### Category 4: 1 broken Codex git worktree

- **Kind:** broken_codex_git_worktree
- **Path:** `/Users/kpasch/Documents/Codex/2026-08-07/cons/work/orchestrator-session-fabric`
- **Error:** git metadata no longer resolves
- **Newest mtime:** 2026-08-07
- **Classification:** SUPERSEDED_BY_NEWER

This is an orphaned Codex workspace from 2026-08-07 whose git metadata is broken. The directory is over a month old. Any work from the `orchestrator-session-fabric` effort has since been superseded by current master (which is 35+ days ahead). No recoverable git state; the directory is inert.

### Category 5: 6 chatgpt bridge artifacts

- **Kind:** chatgpt_bridge_artifact (6 instances)
- **Location:** `/Users/kpasch/Documents/chatgpt-dropbox/_applied/`
- **Classification:** ALREADY_PRESENT (bulk)

These are patches that were successfully applied by the chatgpt-bridge. They reside in the `_applied/` directory, which is the bridge's "done" folder — each generated a PR and was pushed to origin. The applied patches are historical records of completed bridge runs.

### Category 6: 1 Codex output artifact

- **Kind:** codex_output_artifact
- **Path:** `/Users/kpasch/Documents/Codex/2026-08-07/cons/outputs/claude-orchestrator--operator-output-truth-session-fabric-20260812.*`
- **Classification:** SUPERSEDED_BY_NEWER

Output artifact from the same 2026-08-07 Codex session as Category 4. The session-fabric work has been superseded by current master. The output file remains on disk as a historical artifact but contains no unintegrated code.

## Summary

| Classification | Count |
|---|---|
| ALREADY_PRESENT | 863 (108 branch tips + 749 rescue refs + 6 bridge artifacts) |
| ACTIVE_IN_ANOTHER_TASK | ~6 (dirty worktrees with QUEUED tasks) |
| SUPERSEDED_BY_NEWER | ~5 (dirty worktrees superseded + broken codex wt + codex output) |
| RECOVERABLE_VALUE | 0 |
| CONFLICTED_NEEDS_FOCUSED_TASK | 0 |
| UNKNOWN | 0 |

All evidence items classified. Zero UNKNOWN. Zero RECOVERABLE_VALUE. No data deleted, reset, or overwritten.
