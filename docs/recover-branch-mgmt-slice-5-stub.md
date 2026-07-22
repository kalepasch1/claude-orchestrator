# Recovery stub: improve-automated-branch-management-slice-5

**Status:** Branch missing, original prompt non-actionable. This stub documents what exists so the work can be re-planned.

## Existing branch management modules (134 files reference "branch")

| Module | Purpose |
|---|---|
| `runner/git_auto_branch.py` | Automated branch lifecycle: auto-create, auto-delete after grace period, auto-rebase stale branches. (Slice 3) |
| `runner/branch_materializer.py` | Post-decompose branch creation guarantee — ensures each task has a real git branch before entering QUEUED state. |
| `runner/branch_naming.py` | Centralised branch-name generation (`feature/` and `agent/` prefixes, slug deduplication). |
| `runner/missing_branch_audit.py` | Standalone diagnostic checking DONE tasks for genuinely missing branches vs. false positives from unlocalized repo paths. |
| `runner/merge_train.py` | Merge orchestration (uses branch refs). |
| `runner/approval_merge.py` | Approval-gated merge flow. |
| `runner/merge_test_gate.py` | Pre-merge test gating. |
| `runner/worktree_gc.py` | Git worktree garbage collection. |

## What slice 5 likely intended

Given slices 1-3 already cover naming, materialisation, and lifecycle (create/delete/rebase), slice 5 probably targeted one of:
- **Advanced conflict prevention** (pre-merge conflict detection, auto-resolution)
- **Branch health metrics / SLO integration** (staleness dashboards, alerts)
- **Cross-repo branch coordination** (multi-project branch sync)
- **Branch protection rule enforcement** (automated policy checks)

## Next steps

Re-plan this slice with a concrete, actionable prompt based on actual gaps in the modules above.
